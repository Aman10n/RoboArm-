"""
Forward & Inverse Kinematics Engine for RoboArm AI
Wraps the mathematical model from the simulation environment.
"""

from backend.simulation.env import RoboArmSimulation


class KinematicsEngine:
    """
    Kinematics solver wrapping the robot model.
    Provides FK and IK via the mathematical DH-parameter model.
    """

    def __init__(self, simulation: RoboArmSimulation):
        self.sim = simulation

    def forward_kinematics(self, joint_angles: list = None):
        """Compute end-effector position from joint angles."""
        if joint_angles is None:
            joint_angles = self.sim.joint_angles
        return self.sim.robot.get_end_effector(joint_angles)

    def inverse_kinematics(self, target_position: list,
                           target_orientation: list = None,
                           max_iterations: int = 200,
                           residual_threshold: float = 1e-3):
        """Compute joint angles to reach a target position."""
        result = self.sim.robot.inverse_kinematics(
            target_position,
            target_orientation,
            initial_angles=self.sim.joint_angles,
            max_iterations=max_iterations,
            tolerance=residual_threshold
        )
        return result

    def jacobian(self):
        """Compute Jacobian at current configuration."""
        return self.sim.robot.jacobian(self.sim.joint_angles)

    def workspace_reachability(self, target_position: list):
        """Check if a position is reachable."""
        return self.sim.robot.check_reachability(target_position)
