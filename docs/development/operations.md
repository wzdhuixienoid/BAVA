# 运行与文档维护

## 启停与健康

启动、配置和迁移见 [环境配置](setup.md)。当前 Worker 随 API 进程启停，单独关闭浏览器不停止授权业务或后台恢复。

```bash
docker compose ps
docker compose logs --tail 100 api
docker compose logs --tail 100 web
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/openapi.json
```

`/health` 只表示 HTTP 进程响应，不校验数据库或模型。OpenAPI 的 info.version 应与根 README、各包及网页版本一致；Web 从 package.json 读取版本。数据库在 API 容器内可用 `uv run alembic current` 核对，当前 head 见 [文档索引](../README.md)。

本地 `/api/v1/demo/readiness` 与 demo_preflight 检查专用演示初始条件；正常使用后的余额、订阅或风险变化不应误判为系统损坏。真实服务可用性还需检查数据库、Worker 日志和具体业务资源，当前没有完整生产监控平台。

## 备份与升级

升级前停止新写入并记录未收敛 Operation、理财订单和预约。备份应用库；如 LangGraph 使用独立库，也独立备份。默认 Compose 参数下的备份示例：

```bash
umask 077
docker compose exec -T postgres pg_dump -U banking -d banking -Fc > /private/tmp/banking-backup.dump
```

自定义数据库名和用户须同步调整。备份包含业务数据，保存在私有位置；恢复验证使用独立库。同步代码后按迁移链升级并重启，复核版本、schema、原订单／Operation 恢复和通知去重。不在原业务库尝试破坏性降级，不用清库或 reset 代替修复。

更新 Agent Skill、知识或 fixture 后重启 API，确保进程快照一致；更新前端公开构建参数后重建 Web，长期打开页面刷新以加载新代码。历史报告、分析及通知证据仍保留原快照。

## 常见状态排查

| 现象 | 核对方法 |
| --- | --- |
| 任务长时间等待 | 区分等待输入／确认／验证、Task lease 和外部处理；查看所属 Task、Workflow 及审计，不把所有等待当模型失败 |
| UNKNOWN 或理财待成交／到账 | 查询原 Operation／订单及 recovery 日志；检查净值、业务时间和下一阶段，不重复提交 |
| 消息提示但账单没有扣款 | 核对提醒类型；未来续费、授权和资金占用不是扣款，只有实际成功现金流水入账 |
| 转账／订阅后余额或账单旧 | 刷新资源；核对用户、账户、方向、期间与 as_of。对话是历史快照，分页会固定原查询截止时间 |
| 异常没有通知 | 检查近 30 天范围、POSTED 支出、消费／订阅分类、足够历史和 Worker 日志；转账／理财移动不走消费异常规则。已读或删除的同笔提醒不重新生成 |
| 理财新业务关闭 | 确认开关及环境；只读查询和已受理恢复仍可用，不通过开关撤单 |
| 前端漏掉实时事件 | SSE 仅进程内广播；重新读取本人业务资源。尚无跨进程 broker 或事件重放保证 |
| 写操作被锁 | 按 Security Guard 的实际解锁时间等待；无管理员手动解锁入口，不改数据库绕过 |
| 模型失败／正文降级 | 检查提供商配置、超时及契约失败日志，保留确定性事实；不为生成文字重跑金融交易 |

日志和审计不得粘贴密钥、JWT、验证码或用户全量账单。向外部模型重现仅使用授权范围内合成数据。更多结果边界见 [安全说明](../architecture/security.md)。

## 文档维护规则

`README.md` 是产品入口，`docs/README.md` 是完整索引；guides 描述用户交互，architecture 按 Agent、Agent Skill、Tool、Workflow、Plan、Domain API 描述实现及限制，三个 Agent 各有同规格详情，development 描述可执行开发和维护方法。源码 README 只解释本目录职责并链接权威说明，避免复制整份工具表或版本历史。

文档用一级标题标明主题、二级标题划分职责，命令写明工作目录、依赖和数据范围。以当前行为直接叙述，不追加“本轮修复”“未来设计”或历次通过数量。删除失效说明、未使用图片、临时评估结果和发布流水；需要调查历史时使用 Git 历史。

参赛复核报告可保留当前版本的验收日期、实测结果和未达标事项，更新时替换旧结论，不累积发布流水。文档检查会拒绝已移除页面的操作指引以及公开身份验证码的旧说明。

应用版本集中在包配置及两个入口文档；升级时同步版本检查。Skill 资源版本、资料发布日期、schema 标识和 Alembic 历史编号独立，不随应用版本统一改写。仍被运行加载的 SKILL.md、references、知识资料和迁移不能因日期旧而删除。

功能变更须同步相应指南、架构、安全和可运行命令；新文档加入索引，旧文档删除时同时移除引用。维护后执行：

```bash
apps/api/.venv/bin/python scripts/check_docs.py
apps/api/.venv/bin/python -m pytest apps/api/tests/test_release_version.py
```

检查覆盖本地链接／锚点、导航、文档结构、当前版本和已删除目录引用；外部服务可用性及任意自然语言语义仍需人工复核。测试方法见 [验证指南](testing.md)。
