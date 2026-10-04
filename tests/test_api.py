from fastapi.testclient import TestClient

from backend.main import app


def test_health_and_robot_metadata():
    with TestClient(app) as client:
        health = client.get("/api/health")
        robot = client.get("/api/robot")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert robot.status_code == 200
    assert robot.json()["num_joints"] == 7


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
