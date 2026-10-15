from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.config.demo_time import reference_now
from banking_api.domain.enums import RiskLevel
from banking_api.financial.anomaly_detector import TransactionAnomalyDetector
from banking_api.financial.anomaly_models import (
    TransactionAnomalyInput,
    TransactionAnomalyOutput,
)
from banking_api.tools.models import ToolExecutionContext, ToolSpec


def build_detect_anomalies_tool(
    detector: TransactionAnomalyDetector, *, bank_reader=None
) -> ToolSpec:
    async def handler(
        context: ToolExecutionContext, arguments: TransactionAnomalyInput
    ) -> TransactionAnomalyOutput:
        source = (
            TransactionAnomalyDetector(await bank_reader(context.principal.user_id))
            if bank_reader is not None
            else detector
        )
        now = reference_now()
        start, end = arguments.bounds(now)
        return TransactionAnomalyOutput(
            snapshot=source.detect(
                user_id=context.principal.user_id,
                analysis_started_at=start,
                analysis_ended_at=end,
                generated_at=now,
                account_ids=arguments.account_ids,
            )
        )

    return ToolSpec(
        capability_id="transaction.detect_anomalies",
        name="detect_transaction_anomalies",
        description=(
            "支持一年以内的天数或带时区的起止时间；按当前用户和币种隔离返回异常交易快照；"
            "不会返回完整原始流水，也不会确认欺诈。"
        ),
        input_model=TransactionAnomalyInput,
        output_model=TransactionAnomalyOutput,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({FINANCIAL_ANALYSIS_AGENT_ID}),
        handler=handler,
    )
