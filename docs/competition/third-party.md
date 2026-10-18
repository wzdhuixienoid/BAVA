# 第三方组件与资料来源

## 组件使用范围

作品业务代码和团队创作信息由作者提交。以下为主要依赖及用途，版本以根package配置、pnpm锁文件、API项目配置和uv锁文件为准；不声称团队拥有第三方组件的著作权。

| 组件 | 用途 | 来源 |
| --- | --- | --- |
| FastAPI、Pydantic、SQLAlchemy、Alembic | API、类型校验、数据库和迁移 | Python包依赖及其上游发行元数据 |
| LangGraph与PostgreSQL checkpointer | 工具循环与运行进度 | API锁文件 |
| Cryptography、PyJWT | TOTP／Fernet、JWT验证 | API锁文件；TOTP算法见RFC6238 |
| Next.js、React、TypeScript、Tailwind CSS | Web工作台与类型检查 | Web项目配置及pnpm锁文件 |
| oidc-client-ts | OIDC Authorization Code + PKCE | Web项目配置 |
| PostgreSQL、Python容器 | 业务持久化、隔离分析 | Docker Compose与沙箱Dockerfile |
| OpenAI-compatible接口 | 可替换的大模型提供商协议适配 | 提供商及模型由部署者配置，不将协议兼容视作模型许可 |

## 数据与知识

账户、收款人、交易、订阅和理财产品是项目合成数据／虚构演示产品。知识及产品资料保留自身来源、版本和hash，不能将模拟画像当作银行披露或收益保证。需要联网模型时仅使用经授权的合成或适当脱敏输入。

技术依据包括 [RFC 6238](https://www.rfc-editor.org/rfc/rfc6238) 和 [Fernet说明](https://cryptography.io/en/latest/fernet/)。这里没有复制上游参考实现；算法由已声明的Cryptography库提供。

## 正式提交前的作者核对

核对实际随作品分发的第三方组件许可证和NOTICE，补充团队成员贡献、模型使用条款和任何新增资料的授权。不能仅凭此依赖清单认定全部法律和知识产权事项已经完成，也不在缺少作者信息时代签独立创作声明。
