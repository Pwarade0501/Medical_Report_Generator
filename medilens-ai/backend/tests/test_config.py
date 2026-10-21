import pytest
from pydantic import ValidationError

from app.core.config import BASE_DIR, Settings


def make(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_defaults():
    s = make()
    assert s.MAX_UPLOAD_SIZE_MB == 10
    assert s.max_upload_size_bytes == 10 * 1024 * 1024
    assert s.report_storage_dir == (BASE_DIR / "storage" / "reports").resolve()


def test_ai_provider_is_disabled_by_default():
    s = make()
    assert s.OPENAI_API_KEY == ""
    assert s.OPENAI_MODEL == "gpt-6-luna"
    assert s.OPENAI_TIMEOUT_SECONDS == 20


@pytest.mark.parametrize("level", ["WARN", "WARNING", "INFO", "ERROR", "CRITICAL"])
def test_debug_accepts_existing_log_level_values(level):
    assert make(DEBUG=level).DEBUG is False


def test_debug_accepts_debug_log_level():
    assert make(DEBUG="DEBUG").DEBUG is True


def test_limit_is_configurable_via_environment(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "3")
    assert make().max_upload_size_bytes == 3 * 1024 * 1024


def test_storage_path_relative_is_resolved_against_backend_dir(monkeypatch):
    monkeypatch.setenv("REPORT_STORAGE_PATH", "somewhere/else")
    assert make().report_storage_dir == (BASE_DIR / "somewhere" / "else").resolve()


def test_storage_path_absolute_is_kept(tmp_path):
    assert make(REPORT_STORAGE_PATH=str(tmp_path)).report_storage_dir == tmp_path.resolve()


@pytest.mark.parametrize("bad", [0, -5])
def test_non_positive_limit_rejected(bad):
    with pytest.raises(ValidationError):
        make(MAX_UPLOAD_SIZE_MB=bad)
