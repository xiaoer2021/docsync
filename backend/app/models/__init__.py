"""全部模型。导入这个模块即可让 Alembic / create_all 看到所有表。"""

from app.models.action import DdAction
from app.models.app import DdApp, DdContact
from app.models.audit import SysAudit
from app.models.base import Base, BaseModel
from app.models.datasource import DdDatasource
from app.models.doc import DdDoc, DdDocSheet
from app.models.docgroup import DdDocGroup, DdDocGroupLink
from app.models.rbac import SysUser
from app.models.run import DdRun, DdRunAction, DdRunIssue, DdRunLog
from app.models.setting import DdSetting
from app.models.task import DdTask
from app.models.template import DdTemplate

__all__ = [
    "Base",
    "BaseModel",
    "DdAction",
    "DdApp",
    "DdContact",
    "DdDatasource",
    "DdDoc",
    "DdDocGroup",
    "DdDocGroupLink",
    "DdDocSheet",
    "DdRun",
    "DdRunAction",
    "DdRunIssue",
    "DdRunLog",
    "DdSetting",
    "DdTask",
    "DdTemplate",
    "SysAudit",
    "SysUser",
]
