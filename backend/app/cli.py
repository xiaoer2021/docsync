"命令行工具：建库、建管理员、改口令、自检。"

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))

    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic").replace("%", "%%"))
    return cfg


def cmd_initdb(_: argparse.Namespace) -> int:
    """把元数据库升到最新结构。可重复执行。"""
    from alembic import command

    from app.core.config import settings

    settings.ensure_dirs()
    settings.validate_security()
    command.upgrade(_alembic_config(), "head")
    print(f"元数据库已就绪：{'SQLite' if settings.is_sqlite else 'MySQL'}")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    """生成一个新的迁移脚本（开发用）。"""
    from alembic import command

    command.revision(_alembic_config(), message=args.message, autogenerate=True)
    return 0


async def _create_admin(username: str, password: str, display_name: str | None) -> int:
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.models.rbac import ROLE_ADMIN, SysUser

    async with SessionLocal() as session:
        existing = await session.scalar(select(SysUser).where(SysUser.username == username))
        if existing is not None:
            print(f"账号 {username} 已存在，未做改动。要改口令用 reset-password。", file=sys.stderr)
            return 1
        session.add(
            SysUser(
                username=username,
                password_hash=hash_password(password),
                display_name=display_name or username,
                role=ROLE_ADMIN,
            )
        )
        await session.commit()
    print(f"管理员 {username} 已创建。")
    return 0


def cmd_create_admin(args: argparse.Namespace) -> int:
    try:
        return asyncio.run(_create_admin(args.username, _password(args), args.display_name))
    except ValueError as exc:
        print(f"口令不合格：{exc}", file=sys.stderr)
        return 1


async def _reset_password(username: str, password: str) -> int:
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.models.rbac import SysUser

    async with SessionLocal() as session:
        user = await session.scalar(select(SysUser).where(SysUser.username == username))
        if user is None:
            print(f"账号 {username} 不存在。", file=sys.stderr)
            return 1
        user.password_hash = hash_password(password)
        await session.commit()
    print(f"{username} 的口令已重置。")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    try:
        return asyncio.run(_reset_password(args.username, _password(args)))
    except ValueError as exc:
        print(f"口令不合格：{exc}", file=sys.stderr)
        return 1


async def _check() -> int:
    from sqlalchemy import func, select, text

    from app.core.config import settings
    from app.core.db import SessionLocal, engine
    from app.models.rbac import ROLE_ADMIN, SysUser

    ok = True

    try:
        settings.validate_security()
        print("[ok] 安全配置可用")
    except Exception as exc:  # noqa: BLE001
        print(f"[!!] 主密钥不可用：{exc}")
        ok = False

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        print(f"[ok] 元数据库连通（{'sqlite' if settings.is_sqlite else 'mysql'}）")
    except Exception as exc:  # noqa: BLE001
        print(f"[!!] 元数据库连不上：{exc}")
        return 1

    try:
        async with SessionLocal() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(SysUser)
                .where(SysUser.role == ROLE_ADMIN, SysUser.status == "enabled")
            )
        if count:
            print(f"[ok] 已有 {count} 个可用管理员")
        else:
            print("[!!] 没有可用管理员，用 setup 创建")
            ok = False
    except Exception as exc:  # noqa: BLE001
        print(f"[!!] 表结构不完整，先跑 initdb：{exc}")
        ok = False

    return 0 if ok else 1


def cmd_check(_: argparse.Namespace) -> int:
    return asyncio.run(_check())


def _password(args: argparse.Namespace) -> str:
    if args.password is not None:
        return args.password
    password = getpass.getpass("管理员口令：")
    if password != getpass.getpass("再次输入口令："):
        raise ValueError("两次口令不一致")
    return password


async def _has_admin() -> bool:
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.models.rbac import ROLE_ADMIN, SysUser

    async with SessionLocal() as session:
        return (
            await session.scalar(
                select(SysUser.id).where(SysUser.role == ROLE_ADMIN, SysUser.status == "enabled").limit(1)
            )
            is not None
        )


def cmd_setup(args: argparse.Namespace) -> int:
    """Upgrade the schema and create the first administrator without resetting data."""
    cmd_initdb(args)
    if asyncio.run(_has_admin()):
        print("已有可用管理员，保留现有账号及数据。")
        return 0
    return cmd_create_admin(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docsync", description="文档同步中心 命令行工具")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("initdb", help="建表/升级元数据库").set_defaults(func=cmd_initdb)

    p = sub.add_parser("create-admin", help="创建管理员账号")
    p.add_argument("--username", required=True)
    p.add_argument("--password", help="Omit to enter the password interactively")
    p.add_argument("--display-name", default=None)
    p.set_defaults(func=cmd_create_admin)

    p = sub.add_parser("reset-password", help="重置某个账号的口令")
    p.add_argument("--username", required=True)
    p.add_argument("--password", help="Omit to enter the password interactively")
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("setup", help="初始化表结构和首个管理员；保留已有数据")
    p.add_argument("--username", default="admin")
    p.add_argument("--password", help="Omit to enter the password interactively")
    p.add_argument("--display-name", default=None)
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("migrate", help="生成新的迁移脚本（开发用）")
    p.add_argument("-m", "--message", required=True)
    p.set_defaults(func=cmd_migrate)

    sub.add_parser("check", help="自检：主密钥 / 元数据库 / 账号").set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
