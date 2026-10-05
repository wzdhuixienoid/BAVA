import hashlib
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.config.settings import get_settings
from banking_api.persistence.models import SecurityGuardStateModel
from banking_api.runtime.event_publisher import EventPublisher


class SecurityGuardStatus(StrEnum):
    NORMAL = "NORMAL"
    WRITE_LOCKED = "WRITE_LOCKED"


class SecurityLockReason(StrEnum):
    REAUTH_FAILURES = "REAUTH_FAILURES"
    CONTROL_BYPASS = "CONTROL_BYPASS"


class SecuritySignalType(StrEnum):
    REAUTH_FAILED = "REAUTH_FAILED"
    SECURITY_CONTROL_BYPASS_ATTEMPT = "SECURITY_CONTROL_BYPASS_ATTEMPT"


class SecurityStatus(BaseModel):
    status: SecurityGuardStatus
    locked_until: datetime | None = None
    reason_code: SecurityLockReason | None = None


class SecurityWriteLockedError(Exception):
    def __init__(self, status: SecurityStatus) -> None:
        super().__init__("SECURITY_WRITE_LOCKED")
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def security_guard_lock_key(user_id: str) -> int:
    digest = hashlib.sha256(f"security-guard:user:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


async def acquire_security_user_lock(session: AsyncSession, user_id: str) -> None:
    """Serialize security state changes and new Operations for one Principal."""

    if session.get_bind().dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": security_guard_lock_key(user_id)},
        )


class SecurityGuardService:
    """Persistent fail-closed gate for new business side effects."""

    def __init__(self, session: AsyncSession, *, clock=_now) -> None:  # type: ignore[no-untyped-def]
        self.session = session
        self.clock = clock
        self.publisher = EventPublisher(session)
        settings = get_settings()
        self.reauth_limit = settings.security_reauth_failure_limit
        self.reauth_window = timedelta(seconds=settings.security_reauth_failure_window_seconds)
        self.bypass_limit = settings.security_bypass_limit
        self.bypass_window = timedelta(seconds=settings.security_bypass_window_seconds)
        self.lock_duration = timedelta(seconds=settings.security_write_lock_seconds)

    async def get_status(self, user_id: str) -> SecurityStatus:
        await self._serialize(user_id)
        state = await self._load(user_id, for_update=True)
        if state is None:
            return SecurityStatus(status=SecurityGuardStatus.NORMAL)
        changed = self._clear_expired(state, _as_utc(self.clock()))
        if changed:
            await self.session.flush()
        return self._status(state)

    async def require_write_allowed(
        self,
        user_id: str,
        *,
        workflow_id: UUID | None = None,
        conversation_id: UUID | None = None,
        task_id: UUID | None = None,
    ) -> None:
        await self._serialize(user_id)
        state = await self._load(user_id, for_update=True)
        if state is not None:
            self._clear_expired(state, _as_utc(self.clock()))
        status = self._status(state) if state else SecurityStatus(status=SecurityGuardStatus.NORMAL)
        if conversation_id is not None and workflow_id is not None:
            await self.publisher.persist(
                event_type="security.write_check",
                conversation_id=conversation_id,
                task_id=task_id,
                data={
                    "workflow_id": str(workflow_id),
                    "status": status.status.value,
                    "reason_code": status.reason_code.value if status.reason_code else None,
                    "locked_until": status.locked_until.isoformat()
                    if status.locked_until
                    else None,
                    "attempt_count": (
                        state.bypass_attempt_count
                        if state and status.reason_code is SecurityLockReason.CONTROL_BYPASS
                        else state.reauth_failure_count
                        if state
                        else 0
                    ),
                    "window_seconds": int(
                        (
                            self.bypass_window
                            if status.reason_code is SecurityLockReason.CONTROL_BYPASS
                            else self.reauth_window
                        ).total_seconds()
                    ),
                },
            )
        if status.status is SecurityGuardStatus.WRITE_LOCKED:
            if conversation_id is not None:
                await self.session.commit()  # Persist the denial, never a business Operation.
            raise SecurityWriteLockedError(status)

    async def record_reauthentication_result(
        self,
        *,
        user_id: str,
        workflow_id: UUID,
        conversation_id: UUID,
        task_id: UUID | None,
        succeeded: bool,
    ) -> SecurityStatus:
        now = _as_utc(self.clock())
        state = await self._state_for_update(user_id)
        if self._is_locked(state, now):
            return self._status(state)
        self._clear_expired(state, now)
        if succeeded:
            state.reauth_failure_count = 0
            state.reauth_window_started_at = None
            state.version += 1
            state.updated_at = now
            await self.session.flush()
            return self._status(state)
        if (
            state.reauth_window_started_at is None
            or now - _as_utc(state.reauth_window_started_at) > self.reauth_window
        ):
            state.reauth_failure_count = 1
            state.reauth_window_started_at = now
        else:
            state.reauth_failure_count += 1
        activated = state.reauth_failure_count >= self.reauth_limit
        if activated:
            self._activate(state, SecurityLockReason.REAUTH_FAILURES, now)
        else:
            state.version += 1
            state.updated_at = now
        await self._persist_signal(
            event_type="security.reauth_failed",
            state=state,
            signal_type=SecuritySignalType.REAUTH_FAILED,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            task_id=task_id,
            attempt_count=state.reauth_failure_count,
            window=self.reauth_window,
        )
        if activated:
            await self._persist_lock_activated(
                state=state,
                workflow_id=workflow_id,
                conversation_id=conversation_id,
                task_id=task_id,
                signal_type=SecuritySignalType.REAUTH_FAILED,
                attempt_count=state.reauth_failure_count,
                window=self.reauth_window,
            )
        await self.session.flush()
        return self._status(state)

    async def record_control_bypass_attempt(
        self,
        *,
        user_id: str,
        workflow_id: UUID,
        conversation_id: UUID,
        task_id: UUID | None,
    ) -> SecurityStatus:
        now = _as_utc(self.clock())
        state = await self._state_for_update(user_id)
        if self._is_locked(state, now):
            return self._status(state)
        self._clear_expired(state, now)
        if (
            state.bypass_window_started_at is None
            or now - _as_utc(state.bypass_window_started_at) > self.bypass_window
        ):
            state.bypass_attempt_count = 1
            state.bypass_window_started_at = now
        else:
            state.bypass_attempt_count += 1
        activated = state.bypass_attempt_count >= self.bypass_limit
        if activated:
            self._activate(state, SecurityLockReason.CONTROL_BYPASS, now)
        else:
            state.version += 1
            state.updated_at = now
        await self._persist_signal(
            event_type="security.control_bypass_attempt",
            state=state,
            signal_type=SecuritySignalType.SECURITY_CONTROL_BYPASS_ATTEMPT,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            task_id=task_id,
            attempt_count=state.bypass_attempt_count,
            window=self.bypass_window,
        )
        if activated:
            await self._persist_lock_activated(
                state=state,
                workflow_id=workflow_id,
                conversation_id=conversation_id,
                task_id=task_id,
                signal_type=SecuritySignalType.SECURITY_CONTROL_BYPASS_ATTEMPT,
                attempt_count=state.bypass_attempt_count,
                window=self.bypass_window,
            )
        await self.session.flush()
        return self._status(state)

    async def _state_for_update(self, user_id: str) -> SecurityGuardStateModel:
        await self._serialize(user_id)
        state = await self._load(user_id, for_update=True)
        if state is not None:
            return state
        state = SecurityGuardStateModel(user_id=user_id)
        self.session.add(state)
        await self.session.flush()
        return state

    async def _serialize(self, user_id: str) -> None:
        await acquire_security_user_lock(self.session, user_id)

    async def _load(self, user_id: str, *, for_update: bool) -> SecurityGuardStateModel | None:
        statement = select(SecurityGuardStateModel).where(
            SecurityGuardStateModel.user_id == user_id
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    def _clear_expired(self, state: SecurityGuardStateModel, now: datetime) -> bool:
        if state.locked_until is None or _as_utc(state.locked_until) > now:
            return False
        state.locked_until = None
        state.lock_reason = None
        state.reauth_failure_count = 0
        state.reauth_window_started_at = None
        state.bypass_attempt_count = 0
        state.bypass_window_started_at = None
        state.version += 1
        state.updated_at = now
        return True

    @staticmethod
    def _is_locked(state: SecurityGuardStateModel, now: datetime) -> bool:
        return state.locked_until is not None and _as_utc(state.locked_until) > now

    def _activate(
        self, state: SecurityGuardStateModel, reason: SecurityLockReason, now: datetime
    ) -> None:
        state.locked_until = now + self.lock_duration
        state.lock_reason = reason.value
        state.version += 1
        state.updated_at = now

    def _status(self, state: SecurityGuardStateModel) -> SecurityStatus:
        now = _as_utc(self.clock())
        if self._is_locked(state, now):
            return SecurityStatus(
                status=SecurityGuardStatus.WRITE_LOCKED,
                locked_until=_as_utc(state.locked_until),  # type: ignore[arg-type]
                reason_code=SecurityLockReason(state.lock_reason),
            )
        return SecurityStatus(status=SecurityGuardStatus.NORMAL)

    async def _persist_signal(
        self,
        *,
        event_type: str,
        state: SecurityGuardStateModel,
        signal_type: SecuritySignalType,
        workflow_id: UUID,
        conversation_id: UUID,
        task_id: UUID | None,
        attempt_count: int,
        window: timedelta,
    ) -> None:
        await self.publisher.persist(
            event_type=event_type,
            conversation_id=conversation_id,
            task_id=task_id,
            data=self._event_data(
                state,
                signal_type=signal_type,
                workflow_id=workflow_id,
                attempt_count=attempt_count,
                window=window,
            ),
        )

    async def _persist_lock_activated(
        self,
        *,
        state: SecurityGuardStateModel,
        workflow_id: UUID,
        conversation_id: UUID,
        task_id: UUID | None,
        signal_type: SecuritySignalType,
        attempt_count: int,
        window: timedelta,
    ) -> None:
        await self.publisher.persist(
            event_type="security.write_lock_activated",
            conversation_id=conversation_id,
            task_id=task_id,
            data=self._event_data(
                state,
                signal_type=signal_type,
                workflow_id=workflow_id,
                attempt_count=attempt_count,
                window=window,
            ),
        )

    @staticmethod
    def _event_data(
        state: SecurityGuardStateModel,
        *,
        signal_type: SecuritySignalType,
        workflow_id: UUID,
        attempt_count: int,
        window: timedelta,
    ) -> dict[str, Any]:
        return {
            "user_id": state.user_id,
            "workflow_id": str(workflow_id),
            "signal_type": signal_type.value,
            "attempt_count": attempt_count,
            "window_seconds": int(window.total_seconds()),
            "locked_until": (
                _as_utc(state.locked_until).isoformat() if state.locked_until else None
            ),
            "reason_code": state.lock_reason,
            "status": "WRITE_LOCKED" if state.locked_until else "NORMAL",
            "locked_at": state.updated_at.isoformat() if state.locked_until else None,
        }
