from banking_api.agents.financial_analysis_agent import FINANCIAL_ANALYSIS_AGENT_ID
from banking_api.domain.enums import RiskLevel
from banking_api.financial.anomaly_detector import TransactionAnomalyDetector
from banking_api.financial.anomaly_models import (
    TransactionAnomalyInput,
    TransactionAnomalyOutput,
)
from banking_api.tools.models import ToolExecutionContext, ToolSpec


def build_detect_anomalies_tool(detector: TransactionAnomalyDetector) -> ToolSpec:
    def handler(
        context: ToolExecutionContext, arguments: TransactionAnomalyInput
    ) -> TransactionAnomalyOutput:
        return TransactionAnomalyOutput(
            snapshot=detector.detect(
                user_id=context.principal.user_id,
                analysis_days=arguments.analysis_days,
            )
        )

    return ToolSpec(
        capability_id="transaction.detect_anomalies",
        name="detect_transaction_anomalies",
        description=(
            "按当前 Principal 和币种隔离，用确定性规则返回有界异常交易快照；"
            "不会返回完整原始流水，也不会确认欺诈。"
        ),
        input_model=TransactionAnomalyInput,
        output_model=TransactionAnomalyOutput,
        risk_level=RiskLevel.R1_PRIVATE_READ,
        side_effect=False,
        allowed_callers=frozenset({FINANCIAL_ANALYSIS_AGENT_ID}),
        handler=handler,
    )
