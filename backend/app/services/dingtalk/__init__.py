"""钉钉开放平台接入层。"""

from app.services.dingtalk.client import DingTalkClient, client_for
from app.services.dingtalk.errors import DingTalkError

__all__ = ["DingTalkClient", "DingTalkError", "client_for"]
