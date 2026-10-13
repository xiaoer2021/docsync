# 参与开发

先按 README 完成独立安装。调试使用自造的示例数据，提交内容不得包含 `.env`、数据库快照、浏览器登录档案、导出业务数据或真实凭证。

Python 3.11、Node.js 22 为推荐开发环境。变更后执行：

```bash
cd backend
python -m ruff check app tests scripts ../scripts
python -m pytest -q
cd ../frontend
npm ci
npm run build
```

新增平台必须同时更新连接器、平台就绪状态、链接解析、验证、登记、预览、字段变化检查及前端入口。只声明了平台名称不等于实现了连接器。

修改写入策略需覆盖空数据、源读取不完整、主键重复、关键值异常、事务失败及删除对账。修改数据库模型必须增加 Alembic 迁移；保留现有 ID 和密文绑定，不通过删除数据库解决迁移问题。

提交问题请提供平台、脱敏配置、可复现的假数据、预期及实际行为。报告数据写入结果时区分试跑与正式执行。GitHub Actions 执行后端检查、前端构建和 Docker 空库启动检查。
