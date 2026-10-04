"""Initialize local folders and the RoboArm AI SQLite database."""

from pathlib import Path

from backend.db import init_db

ROOT = Path(__file__).resolve().parent


def main() -> None:
    directories = (
        ROOT / "data",
    )
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    init_db()
    print("RoboArm AI setup complete.")
    print("Next: install the frontend dependencies, then run `python run.py`.")


if __name__ == "__main__":
    main()
