# 受控业务 Tools

本目录实现银行与订阅能力，理财工具在相邻 wealth 模块；统一通过 ToolRegistry 登记、ToolExecutor 校验和 PolicyService 授权。

R1 为纯读取，R4 为提交，R3 对账可推进结算。Agent 仅允许其白名单内 R1；提交和对账只允许对应 Workflow，并重新核验持久 Operation 授权。不能因函数名含 status 就标为只读。

完整清单、模型协议、环境差异及验证见 [Tools](../../../../../docs/architecture/tools.md)，不在本页重复维护数量和应用版本。
