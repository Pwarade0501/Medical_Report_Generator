import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.storage import ReportStorage, get_report_storage

TEST_MAX_BYTES = 1024  # small limit so "too large" tests stay fast


@pytest.fixture
def storage_root(tmp_path):
    return tmp_path / "reports"


@pytest.fixture
def client(storage_root):
    """TestClient whose storage points at a temp dir (never the real storage/)."""
    storage = ReportStorage(root=storage_root, max_upload_bytes=TEST_MAX_BYTES)
    app.dependency_overrides[get_report_storage] = lambda: storage
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
