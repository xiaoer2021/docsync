"测试夹具。"

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="docsync-tests-"))
os.environ["DOCSYNC_ENV"] = "dev"
os.environ["DOCSYNC_META_DB_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["DOCSYNC_DATA_DIR"] = str(_TMP)
os.environ["DOCSYNC_SCHEDULER_ENABLED"] = "false"

os.environ["DOCSYNC_MASTER_KEY"] = "S0kZ3nJmYk1vQ2hSNGtQdFZ4YndGcUx6TnhCYzJkRWY="

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.rbac import ROLE_ADMIN, ROLE_VIEWER, SysUser  # noqa: E402


@pytest.fixture(autouse=True)
async def _prepare_schema():
    """每个用例前确保表结构存在。create_all 是幂等的，SQLite 上开销可以忽略。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture(autouse=True)
def _clear_dingtalk_token_cache():
    """token 缓存是进程级的，不清会让用例之间互相串。"""
    from app.services.dingtalk.client import _TOKEN_CACHE

    _TOKEN_CACHE.clear()
    yield
    _TOKEN_CACHE.clear()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def admin_token(client: AsyncClient) -> str:
    await _ensure_user("admin_t", "Admin@12345", ROLE_ADMIN)
    res = await client.post("/api/v1/auth/login", json={"username": "admin_t", "password": "Admin@12345"})
    assert res.status_code == 200, res.text
    return res.json()["token"]


@pytest.fixture
async def viewer_token(client: AsyncClient) -> str:
    await _ensure_user("viewer_t", "Viewer@12345", ROLE_VIEWER)
    res = await client.post("/api/v1/auth/login", json={"username": "viewer_t", "password": "Viewer@12345"})
    assert res.status_code == 200, res.text
    return res.json()["token"]


async def _ensure_user(username: str, password: str, role: str) -> None:
    from sqlalchemy import select

    async with SessionLocal() as session:
        existing = await session.scalar(select(SysUser).where(SysUser.username == username))
        if existing is None:
            session.add(
                SysUser(
                    username=username,
                    password_hash=hash_password(password),
                    display_name=username,
                    role=role,
                )
            )
            await session.commit()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
