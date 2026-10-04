# Changelog

All notable changes to RoboArm AI are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.2.0] - 2026-10-05

### Added

- Enforced keep-in and keep-out workspace zones with live 3D visualization and operator controls.
- Time-aware single- and multi-point trajectory execution with progress, stop, completion, and failure states.
- Persistent, throttled session telemetry with indexed history and summary endpoints.
- API readiness checks, request correlation headers, and WebSocket command validation.
- Live connection-latency, trajectory-status, and safety-boundary feedback in the dashboard.

### Changed

- Centralized environment-backed runtime configuration.
- Hardened SQLite transaction handling and query performance.
- Prevented manual commands from interrupting non-manual control modes.
- Prevented trajectory execution while the emergency stop is engaged.

### Fixed

- Report interrupted trajectory outcomes instead of leaving ambiguous execution state.
- Avoid optimistic frontend success messages when real-time commands cannot be sent.

## [1.1.0] - 2026-10-05

### Added

- Production container deployment, environment configuration, CI checks, and API input validation.
- Responsive React and Three.js dashboard with live telemetry analytics.

## [1.0.0] - 2026-10-04

### Added

- Initial 7-DOF mathematical simulator, kinematics API, trajectory planning, and browser digital twin.

[Unreleased]: https://github.com/Aman10n/RoboArm-/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/Aman10n/RoboArm-/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Aman10n/RoboArm-/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Aman10n/RoboArm-/releases/tag/v1.0.0
