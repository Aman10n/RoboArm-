from fastapi.testclient import TestClient

import backend.main as api_module
from backend.main import app


def test_health_and_robot_metadata():
    with TestClient(app) as client:
        health = client.get("/api/health")
        robot = client.get("/api/robot")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert robot.status_code == 200
    assert robot.json()["num_joints"] == 7


def test_responses_include_request_correlation_metadata():
    with TestClient(app) as client:
        response = client.get("/api/health", headers={"X-Request-ID": "test-request-42"})

    assert response.headers["X-Request-ID"] == "test-request-42"
    assert float(response.headers["X-Process-Time-Ms"]) >= 0


def test_readiness_reports_runtime_dependencies():
    with TestClient(app) as client:
        response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": True, "simulation": True},
    }


def test_joint_payload_validation_and_emergency_stop():
    with TestClient(app) as client:
        invalid = client.post("/api/joints/set", json={"angles": [0, 0]})
        stopped = client.post("/api/emergency-stop")
        blocked = client.post("/api/joints/set", json={"angles": [0] * 7})
        reset = client.post("/api/reset")
        accepted = client.post("/api/joints/set", json={"angles": [0.1] * 7})

    assert invalid.status_code == 422
    assert stopped.status_code == 200
    assert blocked.status_code == 409
    assert reset.status_code == 200
    assert accepted.status_code == 200


def test_websocket_sends_metadata_and_telemetry():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry") as websocket:
            metadata = websocket.receive_json()
            telemetry = websocket.receive_json()

    assert metadata["type"] == "robot_info"
    assert metadata["data"]["num_joints"] == 7
    assert telemetry["type"] == "telemetry"
    assert len(telemetry["data"]["joint_angles"]) == 7


def test_websocket_validates_commands_and_correlates_responses():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry") as websocket:
            websocket.receive_json()
            websocket.receive_json()
            websocket.send_json({"command": "set_joints", "angles": [0.0]})
            invalid = websocket.receive_json()
            websocket.send_json({"command": "ping", "request_id": "heartbeat-1"})
            pong = websocket.receive_json()

    assert invalid["type"] == "error"
    assert "at least 7 items" in invalid["message"]
    assert pong == {"type": "pong", "request_id": "heartbeat-1"}


def test_non_finite_motion_values_are_rejected():
    payload = '{"angles":[NaN,0,0,0,0,0,0]}'
    with TestClient(app) as client:
        response = client.post(
            "/api/joints/set",
            content=payload,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422


def test_workspace_object_names_cannot_be_overwritten():
    payload = {
        "name": "fixture",
        "shape": "box",
        "position": [0.4, 0.0, 0.05],
        "size": [0.1, 0.1, 0.1],
        "color": [0.2, 0.6, 0.9, 1.0],
        "mass": 0.1,
    }
    with TestClient(app) as client:
        created = client.post("/api/objects/add", json=payload)
        duplicate = client.post("/api/objects/add", json=payload)

    assert created.status_code == 200
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


def test_stopping_trajectory_returns_to_manual_mode():
    with TestClient(app) as client:
        client.post("/api/mode/playback")
        stopped = client.post("/api/trajectory/stop")
        mode = client.get("/api/mode")

    assert stopped.status_code == 200
    assert mode.json() == {"mode": "manual"}


def test_deleting_an_inactive_safety_zone_returns_not_found():
    payload = {
        "name": "temporary-zone",
        "zone_type": "keep_out",
        "min_bounds": [-0.1, -0.1, 0.0],
        "max_bounds": [0.1, 0.1, 0.2],
    }
    with TestClient(app) as client:
        created = client.post("/api/safety-zones", json=payload)
        zone_id = created.json()["zone_id"]
        deleted = client.delete(f"/api/safety-zones/{zone_id}")
        deleted_again = client.delete(f"/api/safety-zones/{zone_id}")

    assert created.status_code == 200
    assert deleted.status_code == 200
    assert deleted_again.status_code == 404


def test_telemetry_recording_is_throttled(monkeypatch):
    recorded = []
    monkeypatch.setattr(api_module, "current_session_id", 42)
    monkeypatch.setattr(api_module, "_telemetry_sample_count", 0)
    monkeypatch.setattr(
        api_module.SessionManager,
        "log_telemetry",
        lambda *values: recorded.append(values),
    )
    sample = {
        "sim_time": 1.25,
        "joint_angles": [0.0] * 7,
        "joint_velocities": [0.0] * 7,
        "joint_torques": [0.0] * 7,
        "end_effector_pos": [0.0, 0.0, 1.0],
        "end_effector_orn": [0.0, 0.0, 0.0, 1.0],
    }

    for _ in range(api_module.settings.telemetry_log_interval):
        api_module._record_telemetry(sample)

    assert len(recorded) == 1
    assert recorded[0][0:2] == (42, 1.25)


def test_session_history_exposes_summary_and_validates_limits():
    with TestClient(app) as client:
        sessions = client.get("/api/sessions", params={"limit": 1})
        session_id = sessions.json()[0]["id"]
        summary = client.get(f"/api/sessions/{session_id}")
        invalid_limit = client.get("/api/sessions", params={"limit": 0})
        missing = client.get("/api/sessions/999999999")

    assert sessions.status_code == 200
    assert len(sessions.json()) == 1
    assert summary.status_code == 200
    assert summary.json()["telemetry_samples"] >= 0
    assert summary.json()["collision_count"] >= 0
    assert invalid_limit.status_code == 422
    assert missing.status_code == 404


def test_keep_out_zone_blocks_motion_target():
    zone = {
        "name": "home-tool-keep-out",
        "zone_type": "keep_out",
        "min_bounds": [-0.05, 0.15, 0.60],
        "max_bounds": [0.05, 0.25, 0.66],
    }
    with TestClient(app) as client:
        created = client.post("/api/safety-zones", json=zone)
        zone_id = created.json()["zone_id"]
        blocked = client.post("/api/joints/set", json={"angles": [0.0] * 7})
        client.delete(f"/api/safety-zones/{zone_id}")

    assert created.status_code == 200
    assert blocked.status_code == 409
    assert "safety zone" in blocked.json()["detail"]


def test_telemetry_includes_current_safety_violations(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "_active_safety_zones",
        [
            {
                "name": "tool-guard",
                "zone_type": "keep_out",
                "min_x": -0.1,
                "min_y": -0.1,
                "min_z": 0.5,
                "max_x": 0.1,
                "max_y": 0.1,
                "max_z": 0.7,
            }
        ],
    )

    payload = api_module._decorate_telemetry({"end_effector_pos": [0.0, 0.0, 0.6]})

    assert payload["control_mode"] == api_module.control_mode
    assert payload["safety_violations"][0]["zone"] == "tool-guard"


def test_trajectory_endpoint_returns_actionable_limit_error():
    with TestClient(app) as client:
        response = client.post(
            "/api/trajectory/plan",
            json={"target_angles": [1.0] * 7, "duration": 0.1},
        )

    assert response.status_code == 422
    assert "too short" in response.json()["detail"]


def test_trajectory_execution_preflights_safety_zones():
    zone = {
        "name": "trajectory-start-guard",
        "zone_type": "keep_out",
        "min_bounds": [-0.05, 0.15, 0.60],
        "max_bounds": [0.05, 0.25, 0.66],
    }
    with TestClient(app) as client:
        created = client.post("/api/safety-zones", json=zone)
        zone_id = created.json()["zone_id"]
        response = client.post(
            "/api/trajectory/execute",
            json={"target_angles": [0.1] * 7, "duration": 2.0},
        )
        mode = client.get("/api/mode")
        client.delete(f"/api/safety-zones/{zone_id}")

    assert response.status_code == 409
    assert "waypoint 1" in response.json()["detail"]
    assert mode.json() == {"mode": "manual"}


def test_multi_point_trajectory_can_be_executed():
    with TestClient(app) as client:
        response = client.post(
            "/api/trajectory/multi/execute",
            json={
                "via_points": [[0.0] * 7, [0.1] * 7, [0.0] * 7],
                "segment_duration": 1.0,
                "num_points_per_segment": 10,
            },
        )
        status = client.get("/api/trajectory/status")
        client.post("/api/trajectory/stop")

    assert response.status_code == 200
    assert response.json()["trajectory"]["num_segments"] == 2
    assert status.json()["state"] == "executing"
