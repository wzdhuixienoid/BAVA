# 理财知识维护

## 当前资源与职责

`content/wealth_education.json` 保存通用教育条目及来源 manifest；`content/wealth_retrieval_gold.json` 保存人工检索评估集。产品资料在数据库中按产品版本保存，模拟设计画像由相邻 wealth/design_profiles.py 提供。KeywordWealthKnowledge 执行关键词、别名及中文片段匹配，不用向量数据库，不在启动或对话时下载网页。

教育资料解释概念，不决定交易参数或适当性。产品条款绑定风险、费用和开放／到账安排；DESIGN 画像说明项目虚构策略，不是银行披露、实际持仓或收益预测。画像按产品版本、画像版本及发布时间生效，不覆盖旧说明书、合成净值或历史订单。

技能目录的 SKILL.md 是可信指令，知识正文是待引用证据；检索内容不能修改权限、工具选择或交易授权。

## 新增、更新与停用

1. 阅读完整官方来源，记录名称、URL、来源类型、核验日、可确认的发布／生效日；不能确认的日期留空。来源访问失败记入 manifest 的 unverified_sources，不以搜索摘要补证。
2. 在教育 JSON 中使用稳定 ID、主题、别名、摘要、正文、作用域、版本和有效期；概括必要内容，不长篇转载。来源日期表示上次核验，不代表当前重新访问或持续有效性承诺。
3. 使用 wealth.catalog.digest(content) 生成 content_hash。更新正文需新版本及核验；重复 ID、hash 不符、过期或 enabled=false 的条目不得成为当前依据。停用不删除已保存分析的历史证据。
4. 新域名同步后端及前端来源白名单，并补允许／拒绝测试。内部产品路径和外部 http／https 来源分别校验。
5. 产品资料修改须新增版本，保持结构化条款与正文 hash 清单一致；历史订单检索使用其原绑定版本，不自动补新画像。
6. 更新 gold，加入真实改写、版本、作用域和无答案用例；不得把 gold 问句硬编码到检索或为提升指标改标注。

## 验证与部署

在仓库根目录执行：

```bash
uv run --project apps/api pytest apps/api/tests/test_wealth_advisory.py apps/api/tests/test_wealth_strategy.py
```

检索测试报告实际 Top-3 命中和失败用例；同时检查 scope、产品、版本、hash、未来资料不可见和无答案行为。有限命中率不代表任意问题都能正确回答，不在维护文档固定记录某次指标。

资料按必要章节／段落切片，引用必须来自实际检索结果；缺少证据明确返回无答案。更新包内教育内容后重启 API，无需联网或重建外部索引。概览见 [系统架构](../../../../../docs/architecture/system.md)，用户入口见 [理财指南](../../../../../docs/guides/wealth.md)。
