import re
import uuid

import pytest

from tests.conftest import TEST_MAX_BYTES
from tests.helpers import JPEG_BYTES, PDF_BYTES, PNG_BYTES

URL = "/api/v1/reports/upload"


def upload(client, filename, content, content_type):
    return client.post(URL, files={"file": (filename, content, content_type)})


def saved_files(storage_root):
    return [p for p in storage_root.rglob("*") if p.is_file() and p.name != ".report_metadata.sqlite3"] if storage_root.exists() else []


# ---------- 1-3. Valid uploads ----------

@pytest.mark.parametrize(
    "filename,content,content_type",
    [
        ("report.pdf", PDF_BYTES, "application/pdf"),
        ("scan.png", PNG_BYTES, "image/png"),
        ("photo.jpeg", JPEG_BYTES, "image/jpeg"),
        ("photo.jpg", JPEG_BYTES, "image/jpeg"),
        ("UPPER.PDF", PDF_BYTES, "application/pdf"),
    ],
    ids=lambda v: v if isinstance(v, str) else "bytes",
)
def test_valid_upload(client, storage_root, filename, content, content_type):
    response = upload(client, filename, content, content_type)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"report_id", "filename", "file_type", "file_size", "status"}
    assert body["filename"] == filename
    assert body["file_type"] == content_type
    assert body["file_size"] == len(content)
    assert body["status"] == "uploaded"

    # File really exists at <root>/<report_id>/<name> with identical bytes
    files = saved_files(storage_root)
    assert len(files) == 1
    assert files[0].parent.name == body["report_id"]
    assert files[0].read_bytes() == content


def test_valid_upload_at_exact_size_limit(client):
    content = PDF_BYTES + b"\x00" * (TEST_MAX_BYTES - len(PDF_BYTES))
    assert len(content) == TEST_MAX_BYTES
    assert upload(client, "edge.pdf", content, "application/pdf").status_code == 201


# ---------- 4. Unsupported types ----------

@pytest.mark.parametrize(
    "filename,content,content_type",
    [
        ("notes.txt", b"hello", "text/plain"),
        ("run.exe", b"MZ\x90\x00", "application/octet-stream"),
        ("page.html", b"<html></html>", "text/html"),
        ("image.gif", b"GIF89a", "image/gif"),
        ("noextension", PDF_BYTES, "application/pdf"),
        ("report.pdf", PDF_BYTES, "text/plain"),  # bad declared type
        ("report.pdf", b"just some text, not a pdf", "application/pdf"),  # fake PDF
    ],
    ids=lambda v: v if isinstance(v, str) else "bytes",
)
def test_unsupported_type_rejected(client, storage_root, filename, content, content_type):
    response = upload(client, filename, content, content_type)
    assert response.status_code == 415
    assert response.json()["error"]["code"] == 415
    assert saved_files(storage_root) == []


@pytest.mark.parametrize(
    "filename,content,content_type",
    [
        ("report.pdf", PNG_BYTES, "application/pdf"),  # PNG disguised as PDF
        ("image.png", PDF_BYTES, "image/png"),  # PDF disguised as PNG
        ("image.png", JPEG_BYTES, "image/jpeg"),  # extension != declared/real type
        ("image.jpg", PNG_BYTES, "image/png"),
    ],
    ids=lambda v: v if isinstance(v, str) else "bytes",
)
def test_content_mismatch_rejected(client, storage_root, filename, content, content_type):
    response = upload(client, filename, content, content_type)
    assert response.status_code == 400
    assert "does not match" in response.json()["error"]["message"]
    assert saved_files(storage_root) == []


# ---------- 5. Empty file ----------

def test_empty_file_rejected(client, storage_root):
    response = upload(client, "empty.pdf", b"", "application/pdf")
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "The uploaded file is empty."
    assert saved_files(storage_root) == []


# ---------- 6. Too large ----------

def test_file_over_limit_rejected_and_cleaned_up(client, storage_root):
    content = PDF_BYTES + b"\x00" * (TEST_MAX_BYTES + 1 - len(PDF_BYTES))
    assert len(content) == TEST_MAX_BYTES + 1

    response = upload(client, "big.pdf", content, "application/pdf")

    assert response.status_code == 413
    assert "too large" in response.json()["error"]["message"].lower()
    # No partial file or empty directory left behind
    assert not storage_root.exists() or list(storage_root.iterdir()) == []


def test_large_multi_chunk_file_rejected(client, storage_root):
    # Bigger than one read chunk (64 KB) to exercise the streaming path
    content = PDF_BYTES + b"\x00" * (200 * 1024)
    response = upload(client, "huge.pdf", content, "application/pdf")
    assert response.status_code == 413
    assert not storage_root.exists() or list(storage_root.iterdir()) == []


# ---------- 7. Report IDs ----------

def test_report_id_is_unique_uuid4_not_derived_from_filename(client, storage_root):
    ids = []
    for _ in range(3):
        response = upload(client, "same_name.pdf", PDF_BYTES, "application/pdf")
        assert response.status_code == 201
        ids.append(response.json()["report_id"])

    assert len(set(ids)) == 3
    for report_id in ids:
        assert uuid.UUID(report_id).version == 4
        assert "same_name" not in report_id
        assert (storage_root / report_id / "same_name.pdf").is_file()
    # Same filename uploaded 3 times: nothing overwritten
    assert len(saved_files(storage_root)) == 3


# ---------- 8. Path traversal / unsafe filenames ----------

@pytest.mark.parametrize(
    "evil_name",
    [
        "../../../etc/passwd.pdf",
        "..\\..\\windows\\evil.pdf",
        "/etc/cron.d/evil.pdf",
        "C:\\Users\\victim\\evil.pdf",
        "....//....//evil.pdf",
        "a/../../b.pdf",
        "%2e%2e%2fevil.pdf",
        "evil;rm -rf ~.pdf",
        "we<ird>:na|me?*.pdf",
        ".pdf.pdf",
        "नमस्ते रिपोर्ट.pdf",  # non-ASCII name
    ],
)
def test_path_traversal_and_unsafe_names_are_contained(client, tmp_path, storage_root, evil_name):
    response = upload(client, evil_name, PDF_BYTES, "application/pdf")

    assert response.status_code == 201, response.text
    body = response.json()
    # Metadata never contains a path separator
    assert "/" not in body["filename"] and "\\" not in body["filename"]

    files = saved_files(storage_root)
    assert len(files) == 1
    saved = files[0]
    # Stored under <root>/<report_id>/ with a safe name
    assert saved.parent == storage_root.resolve() / body["report_id"]
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.pdf", saved.name), saved.name
    assert ".." not in saved.name
    # Nothing was written anywhere outside the storage root
    for path in tmp_path.rglob("*"):
        assert path == storage_root.resolve() or storage_root.resolve() in path.parents


def test_traversal_name_with_unsupported_extension_rejected(client, tmp_path):
    response = upload(client, "../../evil.sh", b"#!/bin/sh", "text/x-sh")
    assert response.status_code == 415
    assert list(tmp_path.rglob("*")) == []


# ---------- Malformed uploads ----------

def test_missing_file_field_returns_validation_error(client):
    response = client.post(URL, files={"wrong_field": ("a.pdf", PDF_BYTES, "application/pdf")})
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Validation error"


def test_non_multipart_body_rejected(client):
    response = client.post(URL, json={"file": "not a file"})
    assert response.status_code == 422


def test_get_not_allowed_on_upload(client):
    assert client.get(URL).status_code == 405


# ---------- Storage failure & no path leaks ----------

def test_storage_failure_returns_generic_500(client, tmp_path, storage_root):
    # Make the storage root a *file* so creating directories under it fails
    storage_root.write_text("not a directory")

    response = upload(client, "report.pdf", PDF_BYTES, "application/pdf")

    assert response.status_code == 500
    assert response.json()["error"]["message"] == "Failed to store the uploaded file."
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize(
    "filename,content,content_type",
    [
        ("big.pdf", PDF_BYTES + b"\x00" * 2048, "application/pdf"),
        ("empty.pdf", b"", "application/pdf"),
        ("x.txt", b"x", "text/plain"),
        ("x.pdf", PNG_BYTES, "application/pdf"),
    ],
    ids=lambda v: v if isinstance(v, str) else "bytes",
)
def test_error_responses_do_not_leak_paths(client, tmp_path, filename, content, content_type):
    response = upload(client, filename, content, content_type)
    assert response.status_code >= 400
    assert str(tmp_path) not in response.text
    assert "/home" not in response.text and "/mnt" not in response.text
