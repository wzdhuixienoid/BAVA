# Agent

v0.11.0定义账户、消费、订阅和理财四类只读Agent；理财开关关闭时不注册WealthAdvisorAgent。产品runtime使用LangGraph。Agent只读工具白名单由ToolRegistry和PolicyService强制执行，模型不具备申购、赎回、转账或订阅写权限。金额、排名和结构化结果由确定性服务计算。
