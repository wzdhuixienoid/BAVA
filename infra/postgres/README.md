# PostgreSQL 环境

根 docker-compose.yml 使用 PostgreSQL 17 Alpine，数据保存在 postgres-data 命名卷。应用表由 Alembic 管理，API 容器启动自动 upgrade head；LangGraph checkpointer 管理自己的 checkpoint 表，可配置独立数据库。

不使用手工初始化 SQL 或额外数据库扩展。应用租约、唯一约束和 advisory lock 依赖 PostgreSQL 行为，SQLite 不能替代并发验收。

启动、迁移见 [环境配置](../../docs/development/setup.md)，备份和恢复排查见 [运行维护](../../docs/development/operations.md)，独立测试库要求见 [验证指南](../../docs/development/testing.md)。删除卷会丢失业务数据，不用于正常升级。
