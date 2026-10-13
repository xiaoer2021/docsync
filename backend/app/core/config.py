"""全局配置。所有可调项都走环境变量，前缀 ``DOCSYNC_``。"""

from __future__ import annotations

import base64
import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILES = (".env", "../.env")
if os.environ.get("DOCSYNC_AUTO_SETUP", "false").lower() == "true":
    _ENV_FILES += (str(Path(os.environ.get("DOCSYNC_DATA_DIR", "./data")) / "runtime.env"),)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_prefix="DOCSYNC_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "文档同步中心"
    env: str = "dev"
    debug: bool = False
    api_prefix: str = "/api/v1"

    meta_db_url: str = "sqlite+aiosqlite:///./data/docsync.db"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    jwt_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 12 * 60

    master_key: str = ""
    password_min_length: int = 8
    cors_origins: list[str] = Field(default_factory=list)
    browser_profiles_dir: Path | None = None
    wps_download_dir: Path | None = None

    data_dir: Path = Path("./data")

    scheduler_enabled: bool = True

    embedded_scheduler: bool = True
    scheduler_tick_seconds: int = 15

    worker_max_concurrency: int = 6

    run_timeout_seconds: int = 30 * 60

    queue_wait_timeout_seconds: int = 5 * 60

    run_log_max_bytes: int = 200 * 1024 * 1024

    run_log_db_max_lines: int = 20000

    run_issue_max_rows: int = 200

    dingtalk_api_base: str = "https://api.dingtalk.com"
    dingtalk_oauth_base: str = "https://oapi.dingtalk.com"
    dingtalk_timeout_seconds: float = 30.0
    dingtalk_max_retries: int = 3

    dingtalk_token_refresh_margin_seconds: int = 300

    feishu_api_base: str = "https://open.feishu.cn/open-apis"
    feishu_timeout_seconds: float = 30.0
    feishu_max_retries: int = 3

    feishu_token_refresh_margin_seconds: int = 300

    feishu_bitable_page_size: int = 500

    feishu_sheet_max_cells: int = 20000

    default_batch_size: int = 2000

    sheet_empty_batch_stop: int = 2

    aitable_page_size: int = 100

    preview_rows: int = 20

    load_batch_size: int = 1000

    target_login_timeout: int = 30
    target_query_timeout: int = 120

    @field_validator("data_dir", mode="before")
    @classmethod
    def _expand(cls, v: object) -> object:
        if isinstance(v, str):
            return Path(os.path.expanduser(v))
        return v

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def profiles_dir(self) -> Path:
        return self.browser_profiles_dir or self.data_dir / "browser"

    @property
    def downloads_dir(self) -> Path:
        return self.wps_download_dir or self.data_dir / "wps-downloads"

    def validate_security(self) -> None:
        self.resolve_master_key()
        if self.env != "dev" and ("jwt_secret" not in self.model_fields_set or len(self.jwt_secret) < 32):
            raise RuntimeError("生产环境必须显式设置至少 32 字符的 DOCSYNC_JWT_SECRET。")

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def is_sqlite(self) -> bool:
        return self.meta_db_url.startswith("sqlite")

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.logs_dir, self.tmp_dir):
            p.mkdir(parents=True, exist_ok=True)

        if self.is_sqlite:
            _, _, tail = self.meta_db_url.partition("///")
            db_file = Path(tail.split("?")[0])
            if db_file.name and db_file.parent != Path("."):
                db_file.parent.mkdir(parents=True, exist_ok=True)

    def resolve_master_key(self) -> bytes:
        "取 Fernet 主密钥。"
        if self.master_key:
            key = self.master_key.encode()
            try:
                if len(base64.urlsafe_b64decode(key)) != 32:
                    raise ValueError
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    "DOCSYNC_MASTER_KEY 不是合法的 Fernet 密钥。"
                    '用 `python -c "from cryptography.fernet import Fernet;'
                    ' print(Fernet.generate_key().decode())"` 生成。'
                ) from exc
            return key

        if self.env != "dev":
            raise RuntimeError("生产环境必须设置 DOCSYNC_MASTER_KEY，否则已加密的凭证在重启后将无法解密。")

        fallback = self.data_dir / "dev_master.key"
        if fallback.exists():
            return fallback.read_bytes().strip()
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_bytes(key)
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
