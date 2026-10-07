from banking_api.application.workflow_service import WorkflowService
from banking_api.config.settings import get_settings
from banking_api.domain.enums import WorkflowStatus


async def authenticate_workflow(app, engine, workflow, *, subscription_engine=None, clock=None):
    kwargs = {"subscription_engine": subscription_engine}
    if clock is not None:
        kwargs["clock"] = clock
    if workflow.status is not WorkflowStatus.REAUTH_REQUIRED:
        return workflow
    async with app.state.test_session_factory() as session:
        challenged = await WorkflowService(
            session, app.state.event_bus, engine, **kwargs
        ).start_reauthentication(
            workflow.workflow_id, user_id=workflow.user_id, expected_version=workflow.version
        )
    async with app.state.test_session_factory() as session:
        return await WorkflowService(
            session, app.state.event_bus, engine, **kwargs
        ).verify_reauthentication(
            workflow.workflow_id,
            user_id=workflow.user_id,
            expected_version=challenged.version,
            reauth_id=challenged.reauth_summary.reauth_id,
            verification_code=get_settings().mock_reauth_code,
        )


async def legacy_yellow_authorization(app, engine, workflow):
    """Represent a persisted pre-upgrade authorization without strong verification."""
    from banking_api.persistence.models import WorkflowModel

    async with app.state.test_session_factory() as session:
        row = await session.get(WorkflowModel, workflow.workflow_id)
        state = dict(row.state_json)
        risk = dict(state["risk_decision"])
        risk.update(
            level="YELLOW",
            required_reauthentication=False,
            reason_codes=["DAILY_TRANSFER_WITHIN_LIMIT"],
        )
        state["risk_decision"] = risk
        row.state_json = state
        row.status = WorkflowStatus.READY_FOR_COMMIT
        await session.commit()
        return await WorkflowService(session, app.state.event_bus, engine).get(
            row.workflow_id, user_id=row.user_id
        )
