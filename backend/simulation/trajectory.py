"""Joint-space trajectory planning and time-aware execution."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable
from threading import RLock

import numpy as np


class TrajectoryPlanner:
    """Generate linear, cubic, and quintic trajectories between configurations."""

    def __init__(self, simulation):
        self.sim = simulation

    def _validate(
        self,
        start_angles: list[float],
        end_angles: list[float],
        duration: float,
        num_points: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if len(start_angles) != self.sim.num_joints or len(end_angles) != self.sim.num_joints:
            raise ValueError(f"Trajectories require {self.sim.num_joints} joint angles")
        if not np.isfinite(duration) or duration <= 0:
            raise ValueError("Trajectory duration must be positive")
        if num_points < 2:
            raise ValueError("A trajectory requires at least two points")

        start = np.asarray(start_angles, dtype=float)
        end = np.asarray(end_angles, dtype=float)
        if not np.all(np.isfinite(start)) or not np.all(np.isfinite(end)):
            raise ValueError("Trajectory angles must be finite numbers")
        for index, (start_angle, end_angle, limit) in enumerate(
            zip(start, end, self.sim.joint_limits, strict=True)
        ):
            if not limit["lower"] <= start_angle <= limit["upper"]:
                raise ValueError(f"Start angle for joint {index + 1} exceeds its limits")
            if not limit["lower"] <= end_angle <= limit["upper"]:
                raise ValueError(f"Target angle for joint {index + 1} exceeds its limits")
        timestamps = np.linspace(0.0, duration, num_points)
        normalized_time = timestamps / duration
        return start, end, timestamps, normalized_time

    def _validate_peak_velocity(
        self, start: np.ndarray, end: np.ndarray, duration: float, blend_peak: float
    ) -> None:
        peak_velocities = np.abs(end - start) * blend_peak / duration
        for index, (velocity, limit) in enumerate(
            zip(peak_velocities, self.sim.joint_limits, strict=True)
        ):
            if velocity > limit["max_velocity"]:
                minimum_duration = (
                    abs(end[index] - start[index]) * blend_peak / limit["max_velocity"]
                )
                raise ValueError(
                    f"Duration is too short for joint {index + 1}; "
                    f"use at least {minimum_duration:.2f} seconds"
                )

    def cubic_spline(
        self,
        start_angles: list[float],
        end_angles: list[float],
        duration: float = 2.0,
        num_points: int = 100,
    ) -> dict:
        """Generate a rest-to-rest cubic Hermite trajectory."""
        start, end, timestamps, s = self._validate(
            start_angles, end_angles, duration, num_points
        )
        self._validate_peak_velocity(start, end, duration, 1.5)
        delta = end - start
        blend = 3 * s**2 - 2 * s**3
        velocity_blend = (6 * s - 6 * s**2) / duration
        acceleration_blend = (6 - 12 * s) / duration**2

        return {
            "method": "cubic",
            "waypoints": (start + np.outer(blend, delta)).tolist(),
            "velocities": np.outer(velocity_blend, delta).tolist(),
            "accelerations": np.outer(acceleration_blend, delta).tolist(),
            "timestamps": timestamps.tolist(),
            "duration": duration,
            "num_points": num_points,
        }

    def quintic_polynomial(
        self,
        start_angles: list[float],
        end_angles: list[float],
        duration: float = 2.0,
        num_points: int = 100,
    ) -> dict:
        """Generate a zero-velocity, zero-acceleration endpoint trajectory."""
        start, end, timestamps, s = self._validate(
            start_angles, end_angles, duration, num_points
        )
        self._validate_peak_velocity(start, end, duration, 1.875)
        delta = end - start
        blend = 10 * s**3 - 15 * s**4 + 6 * s**5
        velocity_blend = (30 * s**2 - 60 * s**3 + 30 * s**4) / duration
        acceleration_blend = (60 * s - 180 * s**2 + 120 * s**3) / duration**2
        jerk_blend = (60 - 360 * s + 360 * s**2) / duration**3
        jerks = np.outer(jerk_blend, delta)

        return {
            "method": "quintic",
            "waypoints": (start + np.outer(blend, delta)).tolist(),
            "velocities": np.outer(velocity_blend, delta).tolist(),
            "accelerations": np.outer(acceleration_blend, delta).tolist(),
            "jerks": jerks.tolist(),
            "timestamps": timestamps.tolist(),
            "duration": duration,
            "num_points": num_points,
            "max_jerk": float(np.max(np.abs(jerks))),
        }

    def multi_point_trajectory(
        self,
        via_points: list[list[float]],
        segment_duration: float = 1.5,
        num_points_per_segment: int = 50,
    ) -> dict:
        """Generate a continuous timestamped path through two or more points."""
        if len(via_points) < 2:
            raise ValueError("At least two via points are required")

        waypoints: list[list[float]] = []
        velocities: list[list[float]] = []
        timestamps: list[float] = []
        time_offset = 0.0

        for index in range(len(via_points) - 1):
            segment = self.quintic_polynomial(
                via_points[index],
                via_points[index + 1],
                segment_duration,
                num_points_per_segment,
            )
            segment_times = [time + time_offset for time in segment["timestamps"]]
            start_index = 1 if index else 0
            waypoints.extend(segment["waypoints"][start_index:])
            velocities.extend(segment["velocities"][start_index:])
            timestamps.extend(segment_times[start_index:])
            time_offset += segment_duration

        return {
            "method": "multi-point-quintic",
            "waypoints": waypoints,
            "velocities": velocities,
            "timestamps": timestamps,
            "duration": time_offset,
            "num_segments": len(via_points) - 1,
            "num_points": len(waypoints),
        }

    def linear_interpolation(
        self,
        start_angles: list[float],
        end_angles: list[float],
        duration: float = 2.0,
        num_points: int = 100,
    ) -> dict:
        """Generate constant-speed linear interpolation in joint space."""
        start, end, timestamps, s = self._validate(
            start_angles, end_angles, duration, num_points
        )
        self._validate_peak_velocity(start, end, duration, 1.0)
        delta = end - start
        velocities = np.repeat((delta / duration)[None, :], num_points, axis=0)
        return {
            "method": "linear",
            "waypoints": (start + np.outer(s, delta)).tolist(),
            "velocities": velocities.tolist(),
            "timestamps": timestamps.tolist(),
            "duration": duration,
            "num_points": num_points,
        }


class TrajectoryExecutor:
    """Advance a planned trajectory according to simulation time."""

    def __init__(self, simulation):
        self.sim = simulation
        self.current_trajectory: dict | None = None
        self.current_index = 0
        self.elapsed = 0.0
        self.is_executing = False
        self.completed = False
        self.stopped = False
        self.failure_reason: str | None = None
        self.on_complete: Callable[[], None] | None = None
        self._lock = RLock()

    def load_trajectory(self, trajectory: dict, on_complete=None) -> None:
        """Load a trajectory and reset execution progress."""
        if not trajectory.get("waypoints") or not trajectory.get("timestamps"):
            raise ValueError("Trajectory must contain waypoints and timestamps")
        if len(trajectory["waypoints"]) != len(trajectory["timestamps"]):
            raise ValueError("Every trajectory waypoint requires a timestamp")
        with self._lock:
            self.current_trajectory = trajectory
            self.current_index = 0
            self.elapsed = 0.0
            self.is_executing = False
            self.completed = False
            self.stopped = False
            self.failure_reason = None
            self.on_complete = on_complete

    def start(self) -> None:
        """Start the loaded trajectory from its first waypoint."""
        with self._lock:
            if self.current_trajectory is None:
                raise ValueError("No trajectory has been loaded")
            self.current_index = 0
            self.elapsed = 0.0
            self.completed = False
            self.stopped = False
            self.failure_reason = None
            self.is_executing = True

    def stop(self) -> None:
        """Stop execution while retaining progress for inspection."""
        with self._lock:
            if self.is_executing:
                self.stopped = True
            self.is_executing = False

    def update(self, dt: float):
        """Advance to the waypoint corresponding to the accumulated time."""
        callback = None
        with self._lock:
            if not self.is_executing or self.current_trajectory is None:
                return None

            self.elapsed += max(0.0, float(dt))
            timestamps = self.current_trajectory["timestamps"]
            waypoints = self.current_trajectory["waypoints"]
            waypoint_index = min(
                max(0, bisect_right(timestamps, self.elapsed) - 1),
                len(waypoints) - 1,
            )
            self.current_index = waypoint_index + 1
            target = waypoints[waypoint_index]
            try:
                self.sim.set_joint_angles(target)
            except ValueError as exc:
                self.is_executing = False
                self.failure_reason = str(exc)
                callback = self.on_complete
                result = {
                    "waypoint": target,
                    "index": self.current_index,
                    "total": len(waypoints),
                    "progress": self.current_index / len(waypoints),
                    "error": self.failure_reason,
                }
                if callback:
                    callback()
                return result

            if self.elapsed >= timestamps[-1]:
                self.sim.set_joint_angles(waypoints[-1])
                self.current_index = len(waypoints)
                self.is_executing = False
                self.completed = True
                callback = self.on_complete

            result = {
                "waypoint": target,
                "index": self.current_index,
                "total": len(waypoints),
                "progress": self.current_index / len(waypoints),
            }

        if callback:
            callback()
        return result

    def get_status(self) -> dict:
        """Return a serializable execution snapshot."""
        with self._lock:
            if self.current_trajectory is None:
                return {"state": "idle", "progress": 0.0}

            total = len(self.current_trajectory["waypoints"])
            if self.is_executing:
                state = "executing"
            elif self.failure_reason:
                state = "failed"
            elif self.completed:
                state = "completed"
            elif self.stopped:
                state = "stopped"
            else:
                state = "ready"
            return {
                "state": state,
                "current_index": self.current_index,
                "total_waypoints": total,
                "progress": self.current_index / total if total else 0.0,
                "elapsed": self.elapsed,
                "duration": self.current_trajectory.get("duration", 0.0),
                "failure_reason": self.failure_reason,
            }
