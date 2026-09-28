"""Run the ServiceRequest location and technician acceptance tests locally."""

import os
import subprocess
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = [
    "tests/test_inventory_postgres.py",
    "tests/test_request_workflow_postgres.py",
    "tests/test_inventory_browser.py",
    "tests/test_request_workflow_browser.py",
    "tests/test_technician_client_access.py",
    "tests/test_saas_foundation.py",
    "tests/test_service_request_media.py",
]


def main() -> int:
    env = os.environ.copy()
    # Match the isolated PostgreSQL values used by GitHub Actions. Never inherit
    # a developer or production DATABASE_URL for this test command.
    test_db = "postgresql+asyncpg://pilot:pilot-ci-only@127.0.0.1:5432/fixit_test"
    env.update(
        DATABASE_URL=test_db,
        FIXIT_TEST_DATABASE_URL=test_db,
        FIXIT_RUN_BROWSER="1",
        PYTHONPATH=ROOT,
        SECRET_KEY="isolated-release-ci-secret",
        PUBLIC_APP_URL="http://127.0.0.1:8765",
        ALLOWED_HOSTS="testserver,localhost,127.0.0.1",
        ALLOWED_ORIGINS="http://127.0.0.1:8765",
    )
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS], cwd=ROOT, env=env
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
