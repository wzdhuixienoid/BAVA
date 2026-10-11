# 理财知识维护（v0.11.2）

当前知识库为 24 条已核验的通用教育知识，另检索数据库中八款模拟产品的版本化资料。不使用向量数据库，也不在对话时下载网页。通用知识解释概念，不证明模拟产品的资产配置、费率或银行背书；产品事实只能使用绑定版本的模拟条款。

## 来源与范围

来源核验于 2026-10-10。监管原文采用政府网站完整转载核对；法规、政府投教、银行投教与管理人投教保留各自类型。旧银行资料只采用概念，不采用旧保本产品分类。发布时间不能确认的记为空。

- [中国银行·2019理财知识宣传](https://www.boc.cn/custserv/cs7/cs72/201904/t20190417_17045395.html)（BANK_EDUCATION）
- [中国银行·理财产品代销业务](https://www.boc.cn/pbservice/pb3/202409/t20240912_25152706.html)（BANK_EDUCATION）
- [中银基金·帮助中心](https://www.bocim.com/Channel/16819)（MANAGER_EDUCATION）
- [湖南省委金融办·金融小知识：最大回撤](https://dfjrjgj.hunan.gov.cn/dfjrjgj/jrbk/jrzs/202607/t20260709_34023141.html)（GOVERNMENT_EDUCATION）
- [金融监管总局·产品适当性办法（湖南省政府转载）](https://www.hunan.gov.cn/zqt/zcsd/202507/t20250714_33738350.html)（REGULATION）
- [金融监管总局·资管产品信息披露办法（湖南省政府转载）](https://www.hunan.gov.cn/zqt/zcsd/202512/t20251229_33881962.html)（REGULATION）

原始 NFRA 动态页、银行业协会业绩比较基准两页及工商银行指定投教页曾出现访问失败/超时；manifest 的 unverified_sources 保留未核验记录，未收录为可检索证据。不能以搜索摘要补证。

## 新增、更新、停用

1. 阅读完整官方原文，记录名称、URL、来源类型、核验日及可确认的发布日期/生效日。概括必要段落，避免长篇转载。
2. 在 content/wealth_education.json 新增稳定 ID、主题、别名、摘要、正文、作用域、版本及有效期。新来源域名需同时更新后端及前端安全白名单并补测试。
3. 用 wealth.catalog.digest(content) 生成 content_hash；正文更新须提升版本并重新核验。重复 ID、hash 不符、过期或 enabled=false 的材料不得成为当前依据。停用设置 enabled=false，不删除历史快照。
4. 更新人工标注 content/wealth_retrieval_gold.json，增加真实改写问法、错误作用域和无答案用例；不要把 gold 问句硬编码进检索。
5. 执行 pytest apps/api/tests/test_wealth_advisory.py -q。缓存按进程加载，更新内容后重启 API；无需联网或重建外部索引。

产品资料按产品、版本、有效时间、hash 和结构化条款校验；按章节/完整必要段落切片，不固定截文档开头。历史订单保留订单绑定版本，不覆盖 v1 或旧订单的证据。

## 检索评估

人工 gold 共 46 条，其中 44 条可回答。Top-3 命中 43/44（97.73%）；产品版本、作用域、无答案关键用例均正确。真实失败问法：『最大回撤能预测风险吗』命中最大回撤和历史表现，但 Top-3 未命中预期的回撤局限片段。该失败保留，未修改 gold 来提高指标。
