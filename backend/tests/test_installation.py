"""Fresh installation, repeat setup and credential preservation."""

from __future__ import annotations

import os
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def run(*args: str, cwd: Path = ROOT, env: dict | None = None):
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def test_config_generation_does_not_overwrite_existing_keys(tmp_path):
    envfile = tmp_path / ".env"
    result = run(str(ROOT / "scripts/init_config.py"), "--mode", "manual", "--output", str(envfile))
    assert result.returncode == 0, result.stderr
    initial = envfile.read_bytes()
    values = dict(line.split("=", 1) for line in initial.decode().splitlines() if "=" in line)
    Fernet(values["DOCSYNC_MASTER_KEY"].encode())
    assert len(values["DOCSYNC_JWT_SECRET"]) >= 32
    assert "sqlite+aiosqlite" in values["DOCSYNC_META_DB_URL"]
    again = run(str(ROOT / "scripts/init_config.py"), "--mode", "docker", "--output", str(envfile))
    assert again.returncode == 1
    assert envfile.read_bytes() == initial


def test_fresh_schema_setup_is_repeatable_without_resetting_accounts(tmp_path):
    database = tmp_path / "fresh.db"
    env = {key: value for key, value in os.environ.items() if not key.startswith("DOCSYNC_")}
    env.update(
        {
            "PYTHONUTF8": "1",
            "DOCSYNC_ENV": "prod",
            "DOCSYNC_MASTER_KEY": Fernet.generate_key().decode(),
            "DOCSYNC_JWT_SECRET": secrets.token_urlsafe(48),
            "DOCSYNC_META_DB_URL": f"sqlite+aiosqlite:///{database.as_posix()}",
            "DOCSYNC_DATA_DIR": str(tmp_path / "data"),
            "DOCSYNC_SCHEDULER_ENABLED": "false",
        }
    )

    def cli(*arguments):
        result = run("-m", "app.cli", *arguments, cwd=ROOT / "backend", env=env)
        assert result.returncode == 0, result.stderr + result.stdout

    cli("setup", "--username", "first_admin", "--password", "SyntheticOnly123!")
    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT id,username,password_hash FROM sys_user").fetchall()
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert len(before) == 1 and revision
    cli("setup", "--username", "different_admin", "--password", "DifferentSynthetic456!")
    cli("check")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT id,username,password_hash FROM sys_user").fetchall() == before


def test_production_requires_explicit_stable_jwt_secret(monkeypatch):
    monkeypatch.delenv("DOCSYNC_JWT_SECRET", raising=False)
    settings = Settings(_env_file=None, env="prod", master_key=Fernet.generate_key().decode())
    with pytest.raises(RuntimeError, match="DOCSYNC_JWT_SECRET"):
        settings.validate_security()
    settings = Settings(
        _env_file=None, env="prod", master_key=Fernet.generate_key().decode(), jwt_secret="short"
    )
    with pytest.raises(RuntimeError, match="DOCSYNC_JWT_SECRET"):
        settings.validate_security()


def test_runtime_paths_follow_data_directory(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    assert settings.profiles_dir == tmp_path / "browser"
    assert settings.downloads_dir == tmp_path / "wps-downloads"
