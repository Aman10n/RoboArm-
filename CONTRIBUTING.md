# Contributing to RoboArm AI

Thanks for helping improve the project. Keep changes focused, testable, and documented.

## Development workflow

1. Fork the repository and create a branch from `main`.
2. Install the backend and frontend dependencies described in the README.
3. Make the smallest coherent change that solves the problem.
4. Add or update tests when behavior changes.
5. Run the complete local checks before opening a pull request:

```bash
python -m pytest
python -m compileall -q backend run.py setup.py
python -m ruff check backend tests run.py setup.py
cd frontend && npm run check
```

## Pull requests

A good pull request includes:

- A concise explanation of the problem and solution
- Any user-visible or API compatibility impact
- Test evidence
- Screenshots for meaningful interface changes
- A linked issue when one exists

Avoid mixing unrelated refactors with functional changes. Never commit runtime databases, dependency folders, secrets, or generated build output.

## Coding conventions

- Python targets 3.10+ and follows the configuration in `pyproject.toml`.
- React code uses functional components and the existing ESLint configuration.
- Public API inputs must be validated and errors must be actionable.
- Safety-related behavior requires tests and explicit documentation.
