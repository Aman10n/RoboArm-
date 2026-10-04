"""FastAPI application for the RoboArm AI digital-twin simulator."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, FiniteFloat, model_validator

from backend.config import settings
from backend.db import SafetyZoneManager, SessionManager, init_db
from backend.simulation.env import RoboArmSimulation, get_simulation
from backend.simulation.kinematics import KinematicsEngine
from backend.simulation.trajectory import TrajectoryExecutor, TrajectoryPlanner

logger = logging.getLogger("roboarm.api")

sim: RoboArmSimulation | None = None
kinematics: KinematicsEngine | None = None
trajectory_planner: TrajectoryPlanner | None = None
trajectory_executor: TrajectoryExecutor | None = None
connected_clients: set[WebSocket] = set()
current_session_id: int | None = None
control_mode = "manual"

_broadcast_queue: asyncio.Queue | None = None
_event_loop: asyncio.AbstractEventLoop | None = None


def _enqueue_latest(data: dict) -> None:
    """Put the latest telemetry sample on the async queue without blocking."""
    if _broadcast_queue is None:
        return
    if _broadcast_queue.full():
        with suppress(asyncio.QueueEmpty):
            _broadcast_queue.get_nowait()
    with suppress(asyncio.QueueFull):
        _broadcast_queue.put_nowait(data)


def _queue_broadcast(data: dict) -> None:
    """Safely hand telemetry from the simulation thread to the API loop."""
    if _event_loop and _event_loop.is_running():
        _event_loop.call_soon_threadsafe(
            _enqueue_latest, {**data, "control_mode": control_mode}
        )


async def _broadcast_loop() -> None:
    """Broadcast telemetry samples to all connected WebSocket clients."""
    while True:
        data = await _broadcast_queue.get()
        if not connected_clients:
            continue

        message = json.dumps({"type": "telemetry", "data": data})
        disconnected: list[WebSocket] = []
        for client in tuple(connected_clients):
            try:
                await client.send_text(message)
            except Exception:
                disconnected.append(client)
        connected_clients.difference_update(disconnected)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize and cleanly shut down the simulation and background tasks."""
    global sim, kinematics, trajectory_planner, trajectory_executor
    global current_session_id, _broadcast_queue, _event_loop

    init_db()
    _event_loop = asyncio.get_running_loop()
    _broadcast_queue = asyncio.Queue(maxsize=2)
    broadcast_task = asyncio.create_task(_broadcast_loop())

    sim = get_simulation()
    robot_info = sim.initialize()
    sim.clear_callbacks()
    kinematics = KinematicsEngine(sim)
    trajectory_planner = TrajectoryPlanner(sim)
    trajectory_executor = TrajectoryExecutor(sim)
    sim.add_step_callback(trajectory_executor.update)
    sim.add_telemetry_callback(_queue_broadcast)

    current_session_id = SessionManager.create_session("Automatic session", control_mode)
    sim.start_loop(real_time=True)
    logger.info(
        "Simulation started: %s (%s joints)",
        robot_info["robot_name"],
        robot_info["num_joints"],
    )

    try:
        yield
    finally:
        if trajectory_executor:
            trajectory_executor.stop()
        if sim:
            sim.cleanup()
        if current_session_id:
            SessionManager.end_session(current_session_id)
        broadcast_task.cancel()
        with suppress(asyncio.CancelledError):
            await broadcast_task
        connected_clients.clear()
        _broadcast_queue = None
        _event_loop = None


app = FastAPI(
    title=settings.app_name,
    summary="Real-time API for a 7-DOF robotic-arm digital twin",
    description=(
        "Control a mathematical KUKA LBR iiwa-inspired model, solve forward and "
        "inverse kinematics, and generate smooth joint-space trajectories."
    ),
    version=settings.app_version,
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_, exc: RequestValidationError):
    """Return JSON-safe validation details without echoing untrusted values."""
    errors = []
    for error in exc.errors():
        sanitized = {key: value for key, value in error.items() if key != "input"}
        errors.append(sanitized)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


class JointAnglesRequest(BaseModel):
    angles: list[FiniteFloat] = Field(min_length=7, max_length=7)
    force: FiniteFloat | None = Field(default=None, gt=0)


class SingleJointRequest(BaseModel):
    joint_index: int = Field(ge=0, lt=7)
    angle: FiniteFloat
    force: FiniteFloat | None = Field(default=None, gt=0)


class IKRequest(BaseModel):
    target_position: list[FiniteFloat] = Field(min_length=3, max_length=3)
    target_orientation: list[FiniteFloat] | None = Field(
        default=None, min_length=4, max_length=4
    )


class TrajectoryRequest(BaseModel):
    target_angles: list[FiniteFloat] = Field(min_length=7, max_length=7)
    duration: FiniteFloat = Field(default=2.0, gt=0, le=60)
    method: Literal["linear", "cubic", "quintic"] = "quintic"
    num_points: int = Field(default=100, ge=2, le=10_000)


class MultiTrajectoryRequest(BaseModel):
    via_points: list[list[FiniteFloat]] = Field(min_length=2, max_length=100)
    segment_duration: FiniteFloat = Field(default=1.5, gt=0, le=60)
    num_points_per_segment: int = Field(default=50, ge=2, le=10_000)

    @model_validator(mode="after")
    def validate_points(self):
        if any(len(point) != 7 for point in self.via_points):
            raise ValueError("Every via point must contain exactly 7 joint angles")
        return self


class WorkspaceObjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[\w -]+$")
    shape: Literal["box", "sphere", "cylinder"] = "box"
    position: list[FiniteFloat] = Field(
        default_factory=lambda: [0.5, 0.0, 0.05], min_length=3, max_length=3
    )
    size: list[FiniteFloat] = Field(
        default_factory=lambda: [0.05, 0.05, 0.05], min_length=3, max_length=3
    )
    color: list[FiniteFloat] = Field(
        default_factory=lambda: [1.0, 0.0, 0.0, 1.0], min_length=4, max_length=4
    )
    mass: FiniteFloat = Field(default=0.1, ge=0)

    @model_validator(mode="after")
    def validate_object(self):
        if any(value <= 0 for value in self.size):
            raise ValueError("Object dimensions must be positive")
        if any(not 0 <= value <= 1 for value in self.color):
            raise ValueError("Color values must be between 0 and 1")
        return self


class SafetyZoneRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    zone_type: Literal["keep_in", "keep_out"]
    min_bounds: list[FiniteFloat] = Field(min_length=3, max_length=3)
    max_bounds: list[FiniteFloat] = Field(min_length=3, max_length=3)
    color: str = Field(default="#ff000080", pattern=r"^#[0-9a-fA-F]{8}$")

    @model_validator(mode="after")
    def validate_bounds(self):
        if any(low >= high for low, high in zip(self.min_bounds, self.max_bounds)):
            raise ValueError("Every minimum bound must be lower than its maximum")
        return self


def _require_simulation() -> RoboArmSimulation:
    if sim is None:
        raise HTTPException(status_code=503, detail="Simulation is not initialized")
    return sim


@app.get("/api/status", tags=["system"])
async def get_status():
    active_sim = _require_simulation()
    return {
        "simulation_running": active_sim.running,
        "emergency_stopped": active_sim.emergency_stopped,
        "control_mode": control_mode,
        "session_id": current_session_id,
        "connected_clients": len(connected_clients),
        "sim_time": active_sim.sim_time,
        "step_count": active_sim.step_count,
    }


@app.get("/api/health", tags=["system"])
async def health_check():
    return {"status": "ok", "service": "roboarm-api", "version": app.version}


@app.get("/api/robot", tags=["robot"])
async def get_robot_info():
    return _require_simulation().get_robot_info()


@app.get("/api/joints", tags=["robot"])
async def get_joint_states():
    return _require_simulation().get_joint_states()


@app.get("/api/links", tags=["robot"])
async def get_link_states():
    return _require_simulation().get_link_states()


@app.post("/api/joints/set", tags=["robot"])
async def set_joint_angles(req: JointAnglesRequest):
    active_sim = _require_simulation()
    try:
        active_sim.set_joint_angles(req.angles, req.force)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "angles": req.angles}


@app.post("/api/joints/single", tags=["robot"])
async def set_single_joint(req: SingleJointRequest):
    active_sim = _require_simulation()
    try:
        active_sim.set_single_joint(req.joint_index, req.angle, req.force)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "joint_index": req.joint_index, "angle": req.angle}


@app.post("/api/reset", tags=["robot"])
async def reset_simulation():
    if trajectory_executor:
        trajectory_executor.stop()
    _require_simulation().reset()
    _set_control_mode("manual")
    return {"success": True, "message": "Robot reset to its home position"}


@app.post("/api/emergency-stop", tags=["robot"])
async def emergency_stop():
    _require_simulation().emergency_stop()
    if trajectory_executor:
        trajectory_executor.stop()
    _set_control_mode("manual")
    return {"success": True, "message": "Emergency stop engaged"}


@app.get("/api/fk", tags=["kinematics"])
async def forward_kinematics():
    if not kinematics:
        raise HTTPException(status_code=503, detail="Kinematics engine is not initialized")
    return kinematics.forward_kinematics()


@app.post("/api/fk", tags=["kinematics"])
async def forward_kinematics_custom(req: JointAnglesRequest):
    if not kinematics:
        raise HTTPException(status_code=503, detail="Kinematics engine is not initialized")
    return kinematics.forward_kinematics(req.angles)


@app.post("/api/ik", tags=["kinematics"])
async def inverse_kinematics_endpoint(req: IKRequest):
    if not kinematics:
        raise HTTPException(status_code=503, detail="Kinematics engine is not initialized")
    result = kinematics.inverse_kinematics(req.target_position, req.target_orientation)
    if result["success"]:
        try:
            _require_simulation().set_joint_angles(result["joint_angles"])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result


@app.post("/api/ik/check", tags=["kinematics"])
async def check_reachability(req: IKRequest):
    if not kinematics:
        raise HTTPException(status_code=503, detail="Kinematics engine is not initialized")
    return kinematics.workspace_reachability(req.target_position)


@app.get("/api/jacobian", tags=["kinematics"])
async def get_jacobian():
    if not kinematics:
        raise HTTPException(status_code=503, detail="Kinematics engine is not initialized")
    return kinematics.jacobian()


def _plan_trajectory(req: TrajectoryRequest) -> dict:
    if not trajectory_planner:
        raise HTTPException(status_code=503, detail="Trajectory planner is not initialized")
    start_angles = _require_simulation().get_joint_states()["joint_angles"]
    planners = {
        "linear": trajectory_planner.linear_interpolation,
        "cubic": trajectory_planner.cubic_spline,
        "quintic": trajectory_planner.quintic_polynomial,
    }
    return planners[req.method](
        start_angles, req.target_angles, req.duration, req.num_points
    )


@app.post("/api/trajectory/plan", tags=["trajectory"])
async def plan_trajectory(req: TrajectoryRequest):
    return _plan_trajectory(req)


@app.post("/api/trajectory/execute", tags=["trajectory"])
async def execute_trajectory(req: TrajectoryRequest):
    if not trajectory_executor:
        raise HTTPException(status_code=503, detail="Trajectory executor is not initialized")
    trajectory = _plan_trajectory(req)
    _set_control_mode("playback")
    trajectory_executor.load_trajectory(
        trajectory, on_complete=lambda: _set_control_mode("manual")
    )
    trajectory_executor.start()
    return {"success": True, "trajectory": trajectory}


@app.post("/api/trajectory/multi", tags=["trajectory"])
async def plan_multi_trajectory(req: MultiTrajectoryRequest):
    if not trajectory_planner:
        raise HTTPException(status_code=503, detail="Trajectory planner is not initialized")
    return trajectory_planner.multi_point_trajectory(
        req.via_points, req.segment_duration, req.num_points_per_segment
    )


@app.post("/api/trajectory/stop", tags=["trajectory"])
async def stop_trajectory():
    if trajectory_executor:
        trajectory_executor.stop()
    _set_control_mode("manual")
    return {"success": True}


@app.get("/api/trajectory/status", tags=["trajectory"])
async def trajectory_status():
    return trajectory_executor.get_status() if trajectory_executor else {"state": "idle"}


@app.post("/api/objects/add", tags=["workspace"])
async def add_object(req: WorkspaceObjectRequest):
    try:
        object_id = _require_simulation().add_workspace_object(
            req.name, req.shape, req.position, req.size, req.color, req.mass
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "object_id": object_id, "name": req.name}


@app.delete("/api/objects/{name}", tags=["workspace"])
async def remove_object(name: str):
    removed = _require_simulation().remove_workspace_object(name)
    if not removed:
        raise HTTPException(status_code=404, detail="Workspace object not found")
    return {"success": True, "name": name}


@app.get("/api/objects", tags=["workspace"])
async def list_objects():
    return _require_simulation().get_workspace_objects()


@app.post("/api/safety-zones", tags=["safety"])
async def create_safety_zone(req: SafetyZoneRequest):
    zone_id = SafetyZoneManager.create_zone(
        req.name, req.zone_type, req.min_bounds, req.max_bounds, req.color
    )
    return {"success": True, "zone_id": zone_id}


@app.get("/api/safety-zones", tags=["safety"])
async def list_safety_zones():
    return SafetyZoneManager.get_zones()


@app.delete("/api/safety-zones/{zone_id}", tags=["safety"])
async def delete_safety_zone(zone_id: int):
    if not SafetyZoneManager.delete_zone(zone_id):
        raise HTTPException(status_code=404, detail="Safety zone not found")
    return {"success": True}


@app.get("/api/sessions", tags=["sessions"])
async def list_sessions():
    return SessionManager.get_sessions()


@app.get("/api/sessions/{session_id}/telemetry", tags=["sessions"])
async def get_telemetry(session_id: int, limit: int = 1000):
    return SessionManager.get_telemetry(session_id, min(max(limit, 1), 10_000))


@app.get("/api/sessions/{session_id}/collisions", tags=["sessions"])
async def get_collisions(session_id: int):
    return SessionManager.get_collisions(session_id)


def _set_control_mode(mode: str) -> None:
    global control_mode
    valid_modes = {"manual", "ai", "playback", "script"}
    if mode not in valid_modes:
        raise ValueError(f"Mode must be one of: {', '.join(sorted(valid_modes))}")
    control_mode = mode


@app.get("/api/mode", tags=["system"])
async def get_mode():
    return {"mode": control_mode}


@app.post("/api/mode/{mode}", tags=["system"])
async def set_mode(mode: str):
    try:
        _set_control_mode(mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "mode": mode}


@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)

    active_sim = _require_simulation()
    await websocket.send_text(
        json.dumps({"type": "robot_info", "data": active_sim.get_robot_info()})
    )
    state = active_sim.get_joint_states()
    state["links"] = active_sim.get_link_states()
    state["objects"] = active_sim.get_workspace_objects()
    await websocket.send_text(json.dumps({"type": "telemetry", "data": state}))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                await _handle_ws_command(json.loads(raw), websocket)
            except json.JSONDecodeError:
                await _send_ws_error(websocket, "Invalid JSON payload")
            except (TypeError, ValueError) as exc:
                await _send_ws_error(websocket, str(exc))
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)


async def _send_ws_error(websocket: WebSocket, message: str) -> None:
    await websocket.send_text(json.dumps({"type": "error", "message": message}))


async def _handle_ws_command(message: dict, websocket: WebSocket) -> None:
    active_sim = _require_simulation()
    command = message.get("command")

    if command == "set_joints":
        active_sim.set_joint_angles(message.get("angles", []))
    elif command == "set_single_joint":
        active_sim.set_single_joint(
            int(message.get("joint_index", -1)), float(message.get("angle", 0.0))
        )
    elif command == "ik_move":
        target = message.get("target_position")
        if not kinematics or not isinstance(target, list) or len(target) != 3:
            raise ValueError("target_position must contain exactly 3 values")
        result = kinematics.inverse_kinematics(target)
        if result["success"]:
            active_sim.set_joint_angles(result["joint_angles"])
        await websocket.send_text(json.dumps({"type": "ik_result", "data": result}))
        return
    elif command == "set_mode":
        _set_control_mode(str(message.get("mode", "")))
        await websocket.send_text(
            json.dumps({"type": "mode_changed", "data": {"mode": control_mode}})
        )
        return
    elif command == "emergency_stop":
        active_sim.emergency_stop()
        if trajectory_executor:
            trajectory_executor.stop()
        _set_control_mode("manual")
    elif command == "reset":
        if trajectory_executor:
            trajectory_executor.stop()
        active_sim.reset()
        _set_control_mode("manual")
    elif command == "get_state":
        state = active_sim.get_joint_states()
        state["links"] = active_sim.get_link_states()
        await websocket.send_text(json.dumps({"type": "state", "data": state}))
        return
    else:
        raise ValueError(f"Unknown command: {command}")

    await websocket.send_text(json.dumps({"type": "ack", "command": command}))


def _mount_production_frontend() -> None:
    """Serve a pre-built frontend when a deployment directory is configured."""
    static_dir = settings.static_directory
    if static_dir is None:
        return

    if not static_dir.is_dir():
        logger.warning("ROBOARM_STATIC_DIR does not exist: %s", static_dir)
        return

    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    logger.info("Serving the production frontend from %s", static_dir)


_mount_production_frontend()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
