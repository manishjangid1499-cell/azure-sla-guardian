import pytest
import os
from guardian.config import settings

# Point to clean isolated test database during test runs
TEST_DB_PATH = "test_guardian.db"
settings.DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
settings.SCHEDULER_ENABLED = False


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    # Remove any stray ransomware flags before test run
    if os.path.exists(".simulator_ransomware.flag"):
        try:
            os.remove(".simulator_ransomware.flag")
        except Exception:
            pass
    yield
    # Cleanup test db after test suite finishes
    for f in [TEST_DB_PATH, ".simulator_ransomware.flag"]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass
