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
