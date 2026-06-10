"""Tests for GET /thumbnails/{relpath} endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from catalog import db
from catalog.api.deps import get_session
from catalog.api.main import create_app

_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


@pytest.fixture
def app_and_thumb_dir(tmp_path):
    """Create a test app with a real engine + thumbnail_root pre-seeded."""
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    app = create_app()
    app.state.engine = engine
    app.state.data_root_resolved = tmp_path  # required by lifespan guard
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()
    app.state.thumbnail_root = thumb_dir

    def override_get_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session
    return app, thumb_dir


@pytest.fixture
def client(app_and_thumb_dir):
    app, thumb_dir = app_and_thumb_dir
    return TestClient(app), thumb_dir


def test_get_thumbnail_existing_file(client):
    test_client, thumb_dir = client
    # Write a real PNG file into the thumb_dir.
    relpath = "sample_a/acq1/t1.png"
    dest = thumb_dir / relpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_FAKE_PNG)

    r = test_client.get(f"/thumbnails/{relpath}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == _FAKE_PNG


def test_get_thumbnail_missing_file(client):
    test_client, thumb_dir = client
    r = test_client.get("/thumbnails/sample_a/acq1/nonexistent.png")
    assert r.status_code == 404


def test_get_thumbnail_traversal_attempt(client):
    test_client, thumb_dir = client
    # Path traversal via encoded ".." segments
    r = test_client.get("/thumbnails/../etc/passwd")
    assert r.status_code == 404


def test_get_thumbnail_not_configured(tmp_path):
    """If thumbnail_root is None, every request returns 404."""
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test2.db'}")
    db.init_schema(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    app = create_app()
    app.state.engine = engine
    app.state.data_root_resolved = tmp_path
    app.state.thumbnail_root = None  # explicitly unconfigured

    def override_get_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session

    test_client = TestClient(app)
    r = test_client.get("/thumbnails/sample_a/acq1/t1.png")
    assert r.status_code == 404


def test_get_thumbnail_non_png_rejected(client):
    test_client, thumb_dir = client
    # Write a .txt file and try to serve it.
    relpath_txt = "sample_a/acq1/notes.txt"
    dest = thumb_dir / relpath_txt
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("hello")

    r = test_client.get(f"/thumbnails/{relpath_txt}")
    assert r.status_code == 404
