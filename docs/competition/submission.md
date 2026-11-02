# 作品简介与提交材料

## 作品名称与简介

作品名称：BAVA（Banking AI for Verified Actions）。

设计理念：**Ask. Plan. Verify. Act.**

项目简介：BAVA（Banking AI for Verified Actions）以“Ask. Plan. Verify. Act.”为设计理念，构建自然语言驱动的可信银行业务智能体，实现从意图理解到受控执行的业务闭环。系统融合大语言模型、LangGraph工具编排、Skill按需加载及受约束DAG任务规划，支持账户分析、订阅管理、智能转账与模拟理财。通过只读Agent与确定性Workflow分权协同，结合结构化金融事实、分级授权、强验证、幂等控制及异步状态恢复，实现银行业务操作的可核验、可追溯执行。

## 提交文件对应

| 资料 | 本地入口 |
| --- | --- |
| 架构与架构图 | [system.md](../architecture/system.md)，包含可渲染 Mermaid 图 |
| 核心算法 | [algorithms.md](../architecture/algorithms.md) |
| 安全设计 | [security.md](../architecture/security.md)、[沙箱](../architecture/sandbox.md) |
| 权限及已知风险自评 | [安全自评](security-assessment.md) |
| 源码与说明 | [根 README](../../README.md)、apps/api、apps/web、packages/api-client |
| 部署与数据库升级 | [setup.md](../development/setup.md)，当前版本与迁移以文档导航为准 |
| 测试用例与验证 | [自动测试](../development/testing.md)、[功能验收用例](acceptance.md)、[提交验证记录](verification.md) |
| 第三方组件 | [依赖与来源说明](third-party.md) |

## 源码压缩包

在仓库根目录执行，只需 Python 3.9+，无需启动银行服务：

```bash
python3 scripts/check_docs.py
python3 scripts/package_source.py
```

输出为 `dist/BAVA-v1.0.2-source.zip` 和同名 `.zip.sha256`。压缩包顶层为 `BAVA-v1.0.2-source/`，包含 README、环境模板、Docker Compose、前后端源码、数据库迁移、锁文件、测试用例、使用指南、架构和部署说明。解压后按[部署说明](../development/setup.md)配置并启动。

打包采用明确的源码目录清单，排除 `.git`、私有环境文件、数据库／备份、依赖目录、缓存、构建结果和视频制作素材；依赖须按锁文件安装。脚本在无 Git 的解压目录也可运行。`dist/` 已忽略，不需要把生成压缩包提交回源码仓库。

仓库地址：[wzdhuixienoid/banking-agent](https://github.com/wzdhuixienoid/banking-agent)。目录已按 BAVA 名称整理；仓库路径仍使用 `banking-agent`，便于继续使用既有链接。提交时由作者更新 GitHub，并提供评审可访问的仓库地址或上传源码压缩包。

## 交付边界

作品以合成账户和模拟银行演示业务，覆盖转账、账单分析、模拟理财与订阅管理。完整认证环境提供独立 Keycloak OIDC 登录、页面绑定认证器和 TOTP 交易验证，见[完整演示部署](../development/oidc-demo.md)。真实银行、短信、人脸和 U盾属于渠道扩展；卡片管理、手机号转账与生日订花蛋糕不属于本次四场景交付范围。

视频制作脚本、录屏、音频、逐帧图片和临时质检材料不随源码交付。业务测试使用的演示数据、只读预检、重置工具、历史迁移及仍被加载的 Skill／知识资源继续保留。

权限矩阵、强验证机制及部署边界见[安全自评](security-assessment.md)。
