import math

import pytest

from backend.simulation.env import RoboArmSimulation
from backend.simulation.kinematics import KinematicsEngine
from backend.simulation.trajectory import TrajectoryExecutor, TrajectoryPlanner


@pytest.fixture
def simulation():
    instance = RoboArmSimulation()
    instance.initialize()
    return instance


def test_robot_exposes_seven_valid_joint_limits(simulation):
    info = simulation.get_robot_info()
    assert info["num_joints"] == 7
    assert len(info["joint_limits"]) == 7
    assert all(limit["lower"] < limit["upper"] for limit in info["joint_limits"])


def test_joint_targets_are_clamped_to_physical_limits(simulation):
    simulation.set_joint_angles([100.0] * 7)
    expected = [limit["upper"] for limit in simulation.joint_limits]
    assert simulation.target_angles == expected


def test_invalid_joint_command_is_rejected(simulation):
    with pytest.raises(ValueError, match="Expected 7 angles"):
        simulation.set_joint_angles([0.0, 0.0])
    with pytest.raises(ValueError, match="Joint index"):
        simulation.set_single_joint(7, 0.0)


def test_emergency_stop_latches_motion_until_reset(simulation):
    simulation.set_joint_angles([0.5] * 7)
    simulation.step()
    simulation.emergency_stop()

    assert simulation.emergency_stopped is True
    assert simulation.target_angles == simulation.joint_angles
    assert simulation.joint_velocities == [0.0] * 7
    with pytest.raises(ValueError, match="Emergency stop"):
        simulation.set_joint_angles([0.0] * 7)

    simulation.reset()
    simulation.set_joint_angles([0.1] * 7)
    assert simulation.emergency_stopped is False


def test_forward_kinematics_returns_finite_tool_pose(simulation):
    pose = KinematicsEngine(simulation).forward_kinematics([0.0] * 7)
    assert len(pose["position"]) == 3
    assert len(pose["orientation"]) == 4
    assert all(math.isfinite(value) for value in pose["position"])


def test_quintic_trajectory_has_rest_endpoints(simulation):
    planner = TrajectoryPlanner(simulation)
    trajectory = planner.quintic_polynomial([0.0] * 7, [0.5] * 7, 2.0, 21)

    assert trajectory["waypoints"][0] == [0.0] * 7
    assert trajectory["waypoints"][-1] == [0.5] * 7
    assert trajectory["velocities"][0] == pytest.approx([0.0] * 7)
    assert trajectory["velocities"][-1] == pytest.approx([0.0] * 7, abs=1e-12)
    assert trajectory["accelerations"][0] == pytest.approx([0.0] * 7)
    assert trajectory["accelerations"][-1] == pytest.approx([0.0] * 7, abs=1e-12)


def test_executor_advances_using_elapsed_simulation_time(simulation):
    planner = TrajectoryPlanner(simulation)
    executor = TrajectoryExecutor(simulation)
    completed = []
    trajectory = planner.linear_interpolation([0.0] * 7, [0.4] * 7, 1.0, 5)

    executor.load_trajectory(trajectory, on_complete=lambda: completed.append(True))
    executor.start()
    executor.update(0.5)
    assert executor.get_status()["progress"] == pytest.approx(0.6)

    executor.update(0.5)
    assert executor.get_status()["state"] == "completed"
    assert simulation.target_angles == pytest.approx([0.4] * 7)
    assert completed == [True]


def test_trajectory_rejects_non_finite_angles(simulation):
    planner = TrajectoryPlanner(simulation)

    with pytest.raises(ValueError, match="finite"):
        planner.quintic_polynomial([0.0] * 7, [math.inf] * 7, 2.0, 20)


def test_workspace_objects_are_unique_and_returned_as_snapshots(simulation):
    simulation.add_workspace_object("fixture", position=[0.4, 0.0, 0.05])

    with pytest.raises(ValueError, match="already exists"):
        simulation.add_workspace_object("fixture")

    snapshot = simulation.get_workspace_objects()
    snapshot["fixture"]["position"][0] = 99
    assert simulation.get_workspace_objects()["fixture"]["position"][0] == 0.4
