# OIDC 登录与动态码完整演示环境

该环境在模拟银行旁运行独立 Keycloak 身份服务，使用真实 OIDC Authorization Code + PKCE 登录和认证器 TOTP 动态码验证。主身份登录与银行交易授权分别校验；账户和资金渠道继续使用项目合成数据。适合评审验证红色操作的完整认证链路。

## 准备与启动

需要 Docker Compose、Python 3.9+，以及已按[部署说明](setup.md)填写模型配置的根 `.env`。以下在仓库根目录执行，使用独立项目名保存本环境的数据：

```bash
python3 scripts/prepare_oidc_demo.py
docker compose --env-file .env --env-file .env.oidc.local \
  -f docker-compose.yml -f infra/oidc/compose.yml -p bava-oidc-demo up --build -d
python3 scripts/prepare_oidc_demo.py --provision --project bava-oidc-demo
```

脚本生成私有 `.env.oidc.local` 和 `.local/oidc/bava-realm.json`，权限为0600，并生成每套环境独立的用户密码、管理员密码和银行认证器加密密钥。再次准备会保留原身份和密钥。`--provision` 显式映射合成用户，重复执行不修改既有映射。

默认 Web／API／身份服务／PostgreSQL 端口为3000／8000／8080／5432。已有环境占用端口时，在首次准备时使用 `--web-port`、`--api-port`、`--idp-port` 和 `--database-port` 选择其他端口，地址与前端构建配置会一起生成。启动后通过 `docker compose ... ps` 查看服务，Keycloak 首次导入约需十余秒；先等待身份服务就绪再登录。

## 登录与绑定认证器

1. 打开工作台并点击“登录”。在 Keycloak 登录窗口输入 `.env.oidc.local` 中的 `OIDC_DEMO_USERNAME` 和 `OIDC_DEMO_PASSWORD`，完成密码登录后回到 BAVA。
2. 主身份登录后5分钟内进入“金融总览”，在“免密支付额度”区域点击“绑定认证器”。
3. 在本人认证器中手动添加基于时间的账户，填写页面给出的密钥。
4. 输入认证器当前六位动态码并点击“确认绑定”。成功后显示“认证器已绑定”，密钥和输入码从页面清除。
5. 返回工作台发起红色转账，核对、确认后输入认证器新生成的动态码。绑定或已验证过的时间步不能再次消费；同一动态码不能授权另一笔交易。

本人认证器和加密密钥会随数据库保留。不要删除或更换 `.env.oidc.local` 中的 `MFA_ENCRYPTION_KEY`。演示环境登录需要重新打开页面时再次认证；浏览器 access token 仅保存在内存。

## 评审检查

按[功能验收用例](../competition/acceptance.md)检查账户／消费、订阅、转账与模拟理财。在此环境中，还应核对无凭据及错误 audience 被拒绝、主体映射归属、未绑定／未验证不得提交、错误码拒绝、动态码防重放和独立操作审计。已验证的结果见[提交验证记录](../competition/verification.md)。

使用与启动相同的 Compose 参数执行 `stop`／`start`／`down`。数据库与身份服务命名卷保留数据，私有文件和密钥不纳入源码包。该配置使用仅本机访问的 HTTP 身份服务与 Keycloak 开发启动模式；对外部署时使用组织 HTTPS IdP 及相应生产配置。

身份服务的配置依据为 [Keycloak Docker 指南](https://www.keycloak.org/getting-started/getting-started-docker)及[容器导入说明](https://www.keycloak.org/server/containers)。
