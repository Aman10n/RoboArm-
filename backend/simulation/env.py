"""Pure-Python simulation engine for the RoboArm AI digital twin."""

import math
import threading
import time
from collections.abc import Callable

import numpy as np


def rotation_x(theta):
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[1, 0, 0, 0],
                     [0, c, -s, 0],
                     [0, s, c, 0],
                     [0, 0, 0, 1]])


def rotation_z(theta):
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s, 0, 0],
                     [s, c, 0, 0],
                     [0, 0, 1, 0],
                     [0, 0, 0, 1]])


def translation(x, y, z):
    return np.array([[1, 0, 0, x],
                     [0, 1, 0, y],
                     [0, 0, 1, z],
                     [0, 0, 0, 1]])


def dh_matrix(theta, d, a, alpha):
    """Compute Denavit-Hartenberg transformation matrix."""
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha), math.sin(alpha)
    return np.array([
        [ct, -st * ca, st * sa, a * ct],
        [st, ct * ca, -ct * sa, a * st],
        [0, sa, ca, d],
        [0, 0, 0, 1]
    ])


def matrix_to_quaternion(m):
    """Convert a 3x3 rotation matrix to quaternion [x, y, z, w]."""
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = 0.5 / math.sqrt(tr + 1.0)
        w = 0.25 / s
        x = (m[2, 1] - m[1, 2]) * s
        y = (m[0, 2] - m[2, 0]) * s
        z = (m[1, 0] - m[0, 1]) * s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = 2.0 * math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = 2.0 * math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    return [float(x), float(y), float(z), float(w)]


class KukaIIWA:
    """KUKA LBR iiwa-inspired 7-DOF mathematical model."""

    # DH Parameters: (a, alpha, d) for each joint
    # theta is the joint variable
    DH_PARAMS = [
        (0, -math.pi / 2, 0.1575),   # J1
        (0, math.pi / 2, 0.2025),     # J2
        (0, math.pi / 2, 0.2045),     # J3
        (0, -math.pi / 2, 0.2155),    # J4
        (0, -math.pi / 2, 0.1845),    # J5
        (0, math.pi / 2, 0.2155),     # J6
        (0, 0, 0.081),                # J7
    ]

    JOINT_LIMITS = [
        {'lower': -2.96706, 'upper': 2.96706, 'max_force': 176.0, 'max_velocity': 1.4835},
        {'lower': -2.09440, 'upper': 2.09440, 'max_force': 176.0, 'max_velocity': 1.4835},
        {'lower': -2.96706, 'upper': 2.96706, 'max_force': 100.0, 'max_velocity': 1.7453},
        {'lower': -2.09440, 'upper': 2.09440, 'max_force': 100.0, 'max_velocity': 1.3090},
        {'lower': -2.96706, 'upper': 2.96706, 'max_force': 100.0, 'max_velocity': 2.2689},
        {'lower': -2.09440, 'upper': 2.09440, 'max_force': 38.0, 'max_velocity': 2.3562},
        {'lower': -3.05433, 'upper': 3.05433, 'max_force': 38.0, 'max_velocity': 2.3562},
    ]

    JOINT_NAMES = [
        'lbr_iiwa_joint_1', 'lbr_iiwa_joint_2', 'lbr_iiwa_joint_3',
        'lbr_iiwa_joint_4', 'lbr_iiwa_joint_5', 'lbr_iiwa_joint_6',
        'lbr_iiwa_joint_7'
    ]

    # Visual link dimensions for rendering (height, radius per segment)
    LINK_VISUALS = [
        {'height': 0.1575, 'radius': 0.075},
        {'height': 0.2025, 'radius': 0.065},
        {'height': 0.2045, 'radius': 0.060},
        {'height': 0.2155, 'radius': 0.055},
        {'height': 0.1845, 'radius': 0.050},
        {'height': 0.2155, 'radius': 0.045},
        {'height': 0.081, 'radius': 0.040},
    ]

    def __init__(self):
        self.num_joints = 7

    def forward_kinematics(self, joint_angles: list[float]):
        """
        Compute all link transforms using DH parameters.
        Returns list of {position, orientation} for each link + end effector.
        """
        transforms = []
        T = np.eye(4)

        # Base transform (sitting on ground)
        T_base = translation(0, 0, 0.0)
        T = T_base.copy()

        transforms.append({
            'index': -1,
            'position': [0.0, 0.0, 0.0],
            'orientation': [0.0, 0.0, 0.0, 1.0],
            'local_position': [0.0, 0.0, 0.0],
            'local_orientation': [0.0, 0.0, 0.0, 1.0],
        })

        for i in range(self.num_joints):
            a, alpha, d = self.DH_PARAMS[i]
            theta = joint_angles[i]

            T_joint = dh_matrix(theta, d, a, alpha)
            T = T @ T_joint

            pos = T[:3, 3].tolist()
            quat = matrix_to_quaternion(T[:3, :3])

            transforms.append({
                'index': i,
                'position': [float(pos[0]), float(pos[1]), float(pos[2])],
                'orientation': quat,
                'local_position': [float(a), 0.0, float(d)],
                'local_orientation': [0.0, 0.0, 0.0, 1.0],
            })

        return transforms

    def get_end_effector(self, joint_angles: list[float]):
        """Get end-effector position and orientation."""
        T = np.eye(4)
        for i in range(self.num_joints):
            a, alpha, d = self.DH_PARAMS[i]
            T = T @ dh_matrix(joint_angles[i], d, a, alpha)

        pos = T[:3, 3].tolist()
        quat = matrix_to_quaternion(T[:3, :3])
        euler = self._quat_to_euler(quat)

        return {
            'position': [float(x) for x in pos],
            'orientation': [float(x) for x in quat],
            'euler': [float(x) for x in euler],
        }

    def inverse_kinematics(self, target_position: list[float],
                           target_orientation: list[float] = None,
                           initial_angles: list[float] = None,
                           max_iterations: int = 200,
                           tolerance: float = 1e-3):
        """
        Iterative Jacobian-based IK solver.
        Uses damped least squares (Levenberg-Marquardt).
        """
        if initial_angles is None:
            initial_angles = [0.0] * self.num_joints

        angles = np.array(initial_angles, dtype=float)
        target = np.array(target_position, dtype=float)
        damping = 0.1

        for iteration in range(max_iterations):
            # Current end-effector position
            ee = self.get_end_effector(angles.tolist())
            current = np.array(ee['position'])
            error = target - current
            residual = np.linalg.norm(error)

            if residual < tolerance:
                return {
                    'joint_angles': [float(a) for a in angles],
                    'achieved_position': current.tolist(),
                    'achieved_orientation': ee['orientation'],
                    'residual': float(residual),
                    'success': True,
                    'iterations': iteration
                }

            # Compute Jacobian (numerically)
            J = self._numerical_jacobian(angles)

            # Damped least squares: dq = J^T (J J^T + λI)^-1 * e
            JJT = J @ J.T
            JJT += damping**2 * np.eye(3)
            dq = J.T @ np.linalg.solve(JJT, error)

            # Update angles with step size
            step_size = min(1.0, 0.5 / (np.linalg.norm(dq) + 1e-10))
            angles += step_size * dq

            # Clamp to joint limits
            for i in range(self.num_joints):
                lower = self.JOINT_LIMITS[i]['lower']
                upper = self.JOINT_LIMITS[i]['upper']
                angles[i] = max(lower, min(upper, angles[i]))

        ee = self.get_end_effector(angles.tolist())
        residual = np.linalg.norm(target - np.array(ee['position']))

        return {
            'joint_angles': [float(a) for a in angles],
            'achieved_position': ee['position'],
            'achieved_orientation': ee['orientation'],
            'residual': float(residual),
            'success': residual < 0.01,
            'iterations': max_iterations
        }

    def _numerical_jacobian(self, angles, delta=1e-5):
        """Compute Jacobian numerically via finite differences."""
        J = np.zeros((3, self.num_joints))
        ee_base = np.array(self.get_end_effector(angles.tolist())['position'])

        for i in range(self.num_joints):
            angles_perturbed = angles.copy()
            angles_perturbed[i] += delta
            ee_perturbed = np.array(
                self.get_end_effector(angles_perturbed.tolist())['position']
            )
            J[:, i] = (ee_perturbed - ee_base) / delta

        return J

    def jacobian(self, joint_angles: list[float]):
        """Compute Jacobian at given configuration."""
        angles = np.array(joint_angles, dtype=float)
        J = self._numerical_jacobian(angles)
        return {
            'linear': J.tolist(),
            'angular': np.zeros((3, self.num_joints)).tolist()
        }

    def check_reachability(self, target_position: list[float]):
        """Check if a position is within workspace."""
        dist = np.linalg.norm(target_position)
        max_reach = sum(p[2] for p in self.DH_PARAMS)  # sum of d parameters

        if dist > max_reach:
            return {
                'reachable': False,
                'reason': 'Beyond maximum reach',
                'distance': float(dist),
                'max_reach': float(max_reach)
            }
        if dist < 0.1:
            return {
                'reachable': False,
                'reason': 'Too close to base',
                'distance': float(dist)
            }

        result = self.inverse_kinematics(target_position)
        return {
            'reachable': result['success'],
            'residual': result['residual'],
            'distance': float(dist)
        }

    @staticmethod
    def _quat_to_euler(q):
        """Quaternion [x,y,z,w] to Euler [roll, pitch, yaw]."""
        x, y, z, w = q
        sinr_cosp = 2 * (w * x + y * z)
        cosr_cosp = 1 - 2 * (x * x + y * y)
        roll = math.atan2(sinr_cosp, cosr_cosp)

        sinp = 2 * (w * y - z * x)
        if abs(sinp) >= 1:
            pitch = math.copysign(math.pi / 2, sinp)
        else:
            pitch = math.asin(sinp)

        siny_cosp = 2 * (w * z + x * y)
        cosy_cosp = 1 - 2 * (y * y + z * z)
        yaw = math.atan2(siny_cosp, cosy_cosp)

        return [roll, pitch, yaw]


class RoboArmSimulation:
    """
    Pure-Python simulation environment.
    Manages the robot model, physics stepping, and state broadcasting.
    """

    def __init__(self, time_step=1.0 / 240.0):
        self.time_step = time_step
        self.robot = KukaIIWA()
        self.num_joints = self.robot.num_joints

        # Joint state
        self.joint_angles = [0.0] * self.num_joints
        self.joint_velocities = [0.0] * self.num_joints
        self.joint_torques = [0.0] * self.num_joints
        self.target_angles = [0.0] * self.num_joints

        # Joint info
        self.joint_indices = list(range(self.num_joints))
        self.joint_limits = self.robot.JOINT_LIMITS
        self.joint_names = self.robot.JOINT_NAMES
        self.end_effector_index = self.num_joints - 1

        # Simulation state
        self.running = False
        self.emergency_stopped = False
        self.sim_time = 0.0
        self.step_count = 0
        self.lock = threading.Lock()
        self.sim_thread = None

        # Workspace objects
        self.workspace_objects = {}
        self._object_counter = 0

        # Callbacks
        self.telemetry_callbacks: list[Callable] = []
        self.collision_callbacks: list[Callable] = []
        self.step_callbacks: list[Callable[[float], None]] = []

        # PD control gains
        self.kp = 15.0   # Proportional gain
        self.kd = 2.0    # Derivative gain

    def initialize(self):
        """Initialize the simulation."""
        self.joint_angles = [0.0] * self.num_joints
        self.joint_velocities = [0.0] * self.num_joints
        self.joint_torques = [0.0] * self.num_joints
        self.target_angles = [0.0] * self.num_joints
        self.sim_time = 0.0
        self.step_count = 0
        self.emergency_stopped = False
        self.workspace_objects.clear()
        self._object_counter = 0
        return self.get_robot_info()

    def get_robot_info(self):
        """Return robot configuration."""
        return {
            'num_joints': self.num_joints,
            'joint_names': self.joint_names,
            'joint_limits': self.joint_limits,
            'end_effector_index': self.end_effector_index,
            'robot_name': 'Kuka IIWA 7-DOF (Mathematical Model)'
        }

    def get_joint_states(self):
        """Get current joint states."""
        with self.lock:
            ee = self.robot.get_end_effector(self.joint_angles)
            return {
                'joint_angles': list(self.joint_angles),
                'joint_velocities': list(self.joint_velocities),
                'joint_torques': list(self.joint_torques),
                'end_effector_pos': ee['position'],
                'end_effector_orn': ee['orientation'],
                'sim_time': self.sim_time,
                'step_count': self.step_count,
                'emergency_stopped': self.emergency_stopped,
            }

    def get_link_states(self):
        """Get all link positions for 3D rendering."""
        with self.lock:
            return self.robot.forward_kinematics(self.joint_angles)

    def set_joint_angles(self, angles: list, force: float = None):
        """Set target joint angles."""
        if self.emergency_stopped:
            raise ValueError(
                "Emergency stop is engaged; reset the robot before commanding motion"
            )
        if len(angles) != self.num_joints:
            raise ValueError(f"Expected {self.num_joints} angles, got {len(angles)}")

        clamped = []
        for i, angle in enumerate(angles):
            lower = self.joint_limits[i]['lower']
            upper = self.joint_limits[i]['upper']
            clamped.append(max(lower, min(upper, float(angle))))

        with self.lock:
            self.target_angles = clamped

    def set_single_joint(self, joint_index: int, angle: float, force: float = None):
        """Set a single joint's target angle."""
        if self.emergency_stopped:
            raise ValueError(
                "Emergency stop is engaged; reset the robot before commanding motion"
            )
        if not 0 <= joint_index < self.num_joints:
            raise ValueError(f"Joint index must be between 0 and {self.num_joints - 1}")
        lower = self.joint_limits[joint_index]['lower']
        upper = self.joint_limits[joint_index]['upper']
        angle = max(lower, min(upper, float(angle)))
        with self.lock:
            self.target_angles[joint_index] = angle

    def step(self):
        """Advance simulation by one timestep using PD control."""
        with self.lock:
            for i in range(self.num_joints):
                # PD control
                error = self.target_angles[i] - self.joint_angles[i]
                torque = self.kp * error - self.kd * self.joint_velocities[i]

                # Clamp torque
                max_f = self.joint_limits[i]['max_force']
                torque = max(-max_f, min(max_f, torque))
                self.joint_torques[i] = torque

                # Simple dynamics: acceleration = torque / inertia (approx)
                inertia = 1.0 + 0.5 * (self.num_joints - i)  # heavier at base
                acceleration = torque / inertia

                # Integrate velocity
                self.joint_velocities[i] += acceleration * self.time_step
                # Damping
                self.joint_velocities[i] *= 0.98

                # Clamp velocity
                max_v = self.joint_limits[i]['max_velocity']
                self.joint_velocities[i] = max(-max_v, min(max_v, self.joint_velocities[i]))

                # Integrate position
                self.joint_angles[i] += self.joint_velocities[i] * self.time_step

                # Clamp to limits
                lower = self.joint_limits[i]['lower']
                upper = self.joint_limits[i]['upper']
                if self.joint_angles[i] < lower:
                    self.joint_angles[i] = lower
                    self.joint_velocities[i] = 0
                elif self.joint_angles[i] > upper:
                    self.joint_angles[i] = upper
                    self.joint_velocities[i] = 0

            self.sim_time += self.time_step
            self.step_count += 1

    def add_workspace_object(self, name, shape="box", position=None,
                             size=None, color=None, mass=0.1):
        """Add an object to the workspace."""
        self._object_counter += 1
        position = position or [0.5, 0, 0.05]
        size = size or [0.05, 0.05, 0.05]
        color = color or [1, 0, 0, 1]

        self.workspace_objects[name] = {
            'id': self._object_counter,
            'shape': shape,
            'position': [float(x) for x in position],
            'size': [float(x) for x in size],
            'color': [float(x) for x in color],
            'mass': float(mass),
            'orientation': [0, 0, 0, 1]
        }
        return self._object_counter

    def remove_workspace_object(self, name):
        """Remove a workspace object."""
        if name in self.workspace_objects:
            del self.workspace_objects[name]
            return True
        return False

    def get_workspace_objects(self):
        """Get all workspace objects."""
        return dict(self.workspace_objects)

    def reset(self):
        """Reset to home position."""
        with self.lock:
            self.joint_angles = [0.0] * self.num_joints
            self.joint_velocities = [0.0] * self.num_joints
            self.joint_torques = [0.0] * self.num_joints
            self.target_angles = [0.0] * self.num_joints
            self.sim_time = 0.0
            self.step_count = 0
            self.emergency_stopped = False

    def emergency_stop(self):
        """Latch motion in place until an explicit reset is performed."""
        with self.lock:
            self.target_angles = list(self.joint_angles)
            self.joint_velocities = [0.0] * self.num_joints
            self.joint_torques = [0.0] * self.num_joints
            self.emergency_stopped = True

    def add_telemetry_callback(self, callback):
        self.telemetry_callbacks.append(callback)

    def add_collision_callback(self, callback):
        self.collision_callbacks.append(callback)

    def add_step_callback(self, callback):
        self.step_callbacks.append(callback)

    def clear_callbacks(self):
        """Remove callbacks left by a previous application lifecycle."""
        self.telemetry_callbacks.clear()
        self.collision_callbacks.clear()
        self.step_callbacks.clear()

    def start_loop(self, real_time=True):
        """Start simulation loop in background thread."""
        if self.running:
            return
        self.running = True
        self.sim_thread = threading.Thread(
            target=self._sim_loop, args=(real_time,), daemon=True
        )
        self.sim_thread.start()

    def stop_loop(self):
        """Stop simulation loop."""
        self.running = False
        if self.sim_thread:
            self.sim_thread.join(timeout=2.0)

    def _sim_loop(self, real_time=True):
        """Main simulation loop."""
        while self.running:
            start = time.time()
            self.step()

            for callback in tuple(self.step_callbacks):
                try:
                    callback(self.time_step)
                except Exception:
                    continue

            # Broadcast telemetry at ~30Hz
            if self.step_count % 8 == 0:
                state = self.get_joint_states()
                links = self.get_link_states()
                telemetry = {
                    **state,
                    'links': links,
                    'objects': self.get_workspace_objects()
                }
                for cb in self.telemetry_callbacks:
                    try:
                        cb(telemetry)
                    except Exception:
                        pass

            if real_time:
                elapsed = time.time() - start
                sleep_time = self.time_step - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

    def cleanup(self):
        """Stop simulation."""
        self.stop_loop()


# Global instance
_sim_instance = None


def get_simulation() -> RoboArmSimulation:
    global _sim_instance
    if _sim_instance is None:
        _sim_instance = RoboArmSimulation()
    return _sim_instance
