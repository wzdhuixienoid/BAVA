# AI Banking Agent

面向中文用户的个人银行智能助理。通过对话查询账户和账单、分析消费、管理订阅、办理转账和模拟理财，并展示核对、授权、处理过程及可追溯结果。

**当前版本：v1.0.0 · 数据库迁移：0036**

当前是可运行的模拟银行原型。账户及初始交易为合成数据，转账、订阅扣费、理财执行和强身份验证均使用 Mock；尚未连接真实银行或支付渠道。

## 当前能力

| 场景 | 能力 |
| --- | --- |
| 个人银行 | 账户、余额、收款人、已入账账单；按期间、账户、类别、方向及对手方查询，连续翻页 |
| 转账分析 | 查询已入账转入／转出，计算全期间总额、笔数与对手方分组，并展示最近明细 |
| 消费分析与报告 | 自然月、自然年、最近 N 天及明确区间的汇总、分类、期间比较；生成和保存月报／年报，删除与恢复报告 |
| 异常提醒 | 确定性规则检查金额突增、同账户重复扣款、新商户大额及订阅涨价；后台生成站内提醒并保存证据 |
| 订阅 | 周期扣费识别、涨价分析、页面确认取消、对话取消／恢复；可选模拟自动扣费与续费通知 |
| 转账与收款 | 即时转账、单次预约、有限次按月转账、收款人管理和 AA 收款／付款 |
| 模拟理财 | 八款虚构净值型产品、风险测评、目录、推荐、比较、资料、持仓、申购及赎回；异步成交到账 |
| 受约束计划 | 将已注册查询和工作流组合为持久化 DAG，支持明确数值条件与等待用户操作 |
| 工作台 | 对话命名与删除、处理过程、业务卡片、审计链、消息已读与删除 |

工作台左侧入口依次为金融总览、转账与收款、订阅管理、理财中心、历史消费报告。业务结果在对话中查看；通知从左侧铃铛进入。

## 快速启动

需要 Docker Compose。在仓库根目录执行：

```bash
cp .env.example .env
```

编辑 `.env`，填写可用的 OpenAI-compatible `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`，并设置自己的 `MOCK_REAUTH_CODE`。Base URL 是 API 根路径，适配器追加 `/chat/completions`。

```bash
docker compose up --build -d
```

API 容器启动自动迁移数据库。示例明确启用 development 身份、模拟订阅扣费和模拟理财；预约默认关闭。配置差异、本地开发、OIDC 与升级步骤见 [环境配置](docs/development/setup.md)。

| 页面 | 地址 |
| --- | --- |
| 对话工作台 | [localhost:3000](http://localhost:3000/) |
| 金融总览 | [dashboard](http://localhost:3000/dashboard) |
| 转账与收款 | [transfers](http://localhost:3000/transfers) |
| 订阅管理 | [subscriptions](http://localhost:3000/subscriptions) |
| 理财中心 | [wealth](http://localhost:3000/wealth) |
| 历史消费报告 | [reports](http://localhost:3000/reports) |
| API 文档 | [OpenAPI](http://localhost:8000/docs) |

## 对话示例

```text
我有哪些账户？工资卡余额多少？
我最近有哪些转账？按收款人统计总额。
分析工资卡最近30天的消费。
生成一份2026年8月份消费报告。
最近有没有异常交易？
我有哪些订阅？取消星幕视频。
从工资卡给李小雨转1元，备注餐费。
明天早上9点从工资卡给物业转200元。
每月1号上午9点给物业转100元，共3次。
聚餐100元，和张三、李四AA，我也参与。
查工资卡余额，如果余额不少于3000元，给张三转500元。
有哪些理财产品？比较演示稳健优选和演示进取成长。
```

预约需开启对应开关。收款人、金额、时间或产品有歧义时先补全；不会由模型代替用户确认。具体交互见 [使用指南](docs/README.md)。

## Agent 与执行边界

开发／测试环境登记三个只读 Agent：PersonalBankingAgent、SubscriptionAnalysisAgent、WealthAdvisorAgent。PersonalBankingAgent 按账户、消费或组合请求选择 Skill 和工具配置。生产装配不登记 Mock 理财 Agent 及其工具。

八个标准 Agent Skills 包保存专业指令和按需加载的参考资料；其中三个绑定 Python 业务实现。LangGraph 提供产品工具循环和 checkpoint，Manual 保留为参考运行时。27 个开发／测试工具分为 19 个纯读取、5 个提交和 3 个可推进结算的对账工具。

模型理解请求、选择获准查询并解释事实；后端负责 Decimal 计算、用户归属、风险、授权、幂等及金融状态机。资金写操作由确定性 Workflow 或受控业务 API 执行。

- 查询自动执行；取消订阅需要确认。所有转账、理财申购／赎回和恢复续费授权均须确认与 Mock 强验证。
- Task 完成、预约创建、AA 发布或理财申请受理均不等于资金成功。UNKNOWN 继续核对原 Operation，不另建扣款。
- 页面账单与对话共用已入账投影。提醒、资金占用、待处理和失败记录不作为实际扣款。
- 对话、报告、分析与异常通知保留当时快照；新查询读取当前事实，删除展示记录不撤销金融交易。

六层职责与三个 Agent 的独立说明见 [架构导航](docs/README.md#系统架构与六层职责)。实现与限制见 [系统架构](docs/architecture/system.md)、[安全边界](docs/architecture/security.md) 和 [金融计算与规则](docs/architecture/algorithms.md)。

## 项目与开发入口

```text
apps/api/             FastAPI、Agent、Skill、Workflow、计算、持久化与测试
apps/web/             Next.js 15 / React 19 / TypeScript 工作台
packages/api-client/  OpenAPI 生成的 TypeScript 类型
infra/postgres/       PostgreSQL 环境说明
scripts/              数据、校验、评估与隔离演示工具
docs/guides/          当前使用指南
docs/architecture/    当前架构、技能、工具、算法与安全
docs/development/     环境、测试及运行维护
```

后端使用 Python 3.12+、FastAPI、SQLAlchemy、Alembic 和 PostgreSQL 17。本地开发及检查命令见 [开发配置](docs/development/setup.md) 和 [验证方法](docs/development/testing.md)。完整阅读顺序见 [文档导航](docs/README.md)。

## 当前限制

转账仅支持 CNY 银行卡收款人；预约不冻结余额，周期最多 12 次且跨度最多 366 天。计划最多 8 步、2 个条件和一个写工作流，不支持 ELSE、循环、多笔写业务或动态重规划。模拟理财不支持定投、调仓、条件自动投资、封闭式产品或受理后撤单。

通知仅站内提供，消费异常线索不等于欺诈认定。Worker 由 API 托管，SSE 为进程内广播，尚无跨进程实时代理或事件回放。没有真实银行、真实 MFA、通用代码沙箱或自主多 Agent 委派；有限正文校验也不能证明任意自然语言解释全部正确。
