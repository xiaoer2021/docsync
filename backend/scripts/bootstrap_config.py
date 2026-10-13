"""Persist installation secrets for the self-contained Docker deployment."""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path


def main() -> int:
    directory = Path(os.environ.get("DOCSYNC_DATA_DIR", "./data"))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "runtime.env"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return 0
    master = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    jwt = secrets.token_urlsafe(48)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"DOCSYNC_MASTER_KEY={master}\nDOCSYNC_JWT_SECRET={jwt}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
