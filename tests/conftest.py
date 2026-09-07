"""Shared fixtures. Every test runs against a throwaway SQLite file, never data/journal.db."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db  # noqa: E402


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Point the whole app at a throwaway DB and build the schema.

    get_conn() reads the module-level DB_PATH at call time, so patching the
    attribute redirects database.py, app_logic.py and server.py at once.
    """
    path = tmp_path / "data" / "journal.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    return str(path)


@pytest.fixture
def client(tmp_db):
    """Flask test client bound to the same throwaway DB."""
    import server

    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


@pytest.fixture
def day_id(tmp_db):
    """A trading day to hang journal trades off. upsert_day returns an int id."""
    return db.upsert_day("2026-09-01", None)
