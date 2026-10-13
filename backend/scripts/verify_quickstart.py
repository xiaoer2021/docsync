"""Check quickstart login from inside the API container without printing credentials."""

from __future__ import annotations

from pathlib import Path

import httpx

from app.core.config import settings


def main() -> int:
    password = (Path(settings.data_dir) / "initial-admin-password").read_text().strip()
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10, trust_env=False) as client:
        health = client.get("/health")
        health.raise_for_status()
        assert health.json()["database"]["ok"]
        assert health.json()["scheduler"]["running"]
        result = client.post("/api/v1/auth/login", json={"username": "admin", "password": password})
        result.raise_for_status()
        token = result.json()["token"]
        assert token
    print("Quickstart health, scheduler and generated administrator login passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
