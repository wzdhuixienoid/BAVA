本次请求的产品输出是月度消费报告数据源。
必须成功获取 spending_summary 和 category_breakdown。
优先同时获取 period_comparison 和 top_transactions。
如果先查询了账户，剩余三个工具名额必须优先汇总、分类，再选一项可选数据。
任何必需查询返回没有账单时立即结束，不补查可选数据或猜测其他期间。
top_transactions 使用 limit=5，以保持报告 Artifact 的有界展示范围。
不得固定 Tool 调用顺序，也不得自行计算数值。
中间自然语言回答不会展示给用户；只需在数据收集完成后简短结束。
