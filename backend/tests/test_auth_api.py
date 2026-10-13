"""登录、鉴权、账号管理。"""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth_header


class TestLogin:
    async def test_login_ok(self, client: AsyncClient, admin_token: str):
        assert admin_token

    async def test_wrong_password(self, client: AsyncClient, admin_token: str):
        res = await client.post("/api/v1/auth/login", json={"username": "admin_t", "password": "nope-nope"})
        assert res.status_code == 401

    async def test_unknown_user_same_message(self, client: AsyncClient):
        """账号不存在与口令错误必须返回同一句话，不给「用户名存在」的旁证。"""
        res = await client.post("/api/v1/auth/login", json={"username": "ghost", "password": "whatever123"})
        assert res.status_code == 401
        assert res.json()["detail"] == "用户名或口令不正确"

    async def test_password_not_echoed(self, client: AsyncClient, admin_token: str):
        res = await client.get("/api/v1/auth/me", headers=auth_header(admin_token))
        body = res.text
        assert "Admin@12345" not in body
        assert "password" not in body


class TestAuthGuard:
    async def test_me_requires_token(self, client: AsyncClient):
        assert (await client.get("/api/v1/auth/me")).status_code == 401

    async def test_me_rejects_bad_token(self, client: AsyncClient):
        res = await client.get("/api/v1/auth/me", headers=auth_header("garbage"))
        assert res.status_code == 401

    async def test_viewer_cannot_create_user(self, client: AsyncClient, viewer_token: str):
        res = await client.post(
            "/api/v1/users",
            headers=auth_header(viewer_token),
            json={"username": "nope", "password": "Whatever@123", "role": "viewer"},
        )
        assert res.status_code == 403

    async def test_viewer_can_list_users(self, client: AsyncClient, viewer_token: str):
        """只读账号要看得到「这条是谁改的」，所以清单是放开的。"""
        res = await client.get("/api/v1/users", headers=auth_header(viewer_token))
        assert res.status_code == 200


class TestUserAdmin:
    async def test_create_and_login_new_user(self, client: AsyncClient, admin_token: str):
        res = await client.post(
            "/api/v1/users",
            headers=auth_header(admin_token),
            json={
                "username": "ops_a",
                "password": "Ops@123456",
                "display_name": "运营甲",
                "role": "viewer",
            },
        )
        assert res.status_code == 201, res.text
        assert res.json()["role"] == "viewer"

        login = await client.post("/api/v1/auth/login", json={"username": "ops_a", "password": "Ops@123456"})
        assert login.status_code == 200

    async def test_duplicate_username(self, client: AsyncClient, admin_token: str):
        payload = {"username": "dup_u", "password": "Dup@123456", "role": "viewer"}
        first = await client.post("/api/v1/users", headers=auth_header(admin_token), json=payload)
        assert first.status_code == 201
        second = await client.post("/api/v1/users", headers=auth_header(admin_token), json=payload)
        assert second.status_code == 409

    async def test_bad_role_rejected(self, client: AsyncClient, admin_token: str):
        res = await client.post(
            "/api/v1/users",
            headers=auth_header(admin_token),
            json={"username": "badrole", "password": "Bad@123456", "role": "superuser"},
        )
        assert res.status_code == 400

    async def test_cannot_delete_self(self, client: AsyncClient, admin_token: str):
        me = await client.get("/api/v1/auth/me", headers=auth_header(admin_token))
        my_id = me.json()["id"]
        res = await client.delete(f"/api/v1/users/{my_id}", headers=auth_header(admin_token))
        assert res.status_code == 400

    async def test_last_admin_cannot_be_demoted(self, client: AsyncClient, admin_token: str):
        """把唯一的管理员降级会把平台锁死，必须挡住。"""
        me = await client.get("/api/v1/auth/me", headers=auth_header(admin_token))
        my_id = me.json()["id"]
        res = await client.patch(
            f"/api/v1/users/{my_id}",
            headers=auth_header(admin_token),
            json={"role": "viewer"},
        )
        assert res.status_code == 400
        assert "管理员" in res.json()["detail"]

    async def test_change_password(self, client: AsyncClient, admin_token: str):
        res = await client.post(
            "/api/v1/auth/password",
            headers=auth_header(admin_token),
            json={"old_password": "Admin@12345", "new_password": "Admin@54321"},
        )
        assert res.status_code == 200

        login = await client.post(
            "/api/v1/auth/login", json={"username": "admin_t", "password": "Admin@54321"}
        )
        assert login.status_code == 200

        await client.post(
            "/api/v1/auth/password",
            headers=auth_header(admin_token),
            json={"old_password": "Admin@54321", "new_password": "Admin@12345"},
        )

    async def test_wrong_old_password(self, client: AsyncClient, admin_token: str):
        res = await client.post(
            "/api/v1/auth/password",
            headers=auth_header(admin_token),
            json={"old_password": "not-it", "new_password": "Whatever@123"},
        )
        assert res.status_code == 400
