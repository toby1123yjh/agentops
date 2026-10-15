"""Versioned ingestion contract and evidence-based execution results."""

import base64
import hashlib
import json
import math
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

BIGINT_MAX = 9223372036854775807
ACTIVE_STATES = {'requested', 'awaiting_approval', 'queued', 'running'}

LIFECYCLES = {
    'requested': '已请求',
    'awaiting_approval': '待审批',
    'queued': '排队中',
    'running': '执行中',
    'completed': '已结束',
    'rejected': '已拒绝',
    'cancelled': '已取消',
    'interrupted': '已中断',
}
OUTCOMES = {
    'pending': '待完成',
    'success': '成功',
    'failure': '失败',
    'rejected': '拒绝',
    'cancelled': '取消',
    'unknown': '未知',
}
TRANSITIONS = {
    'requested': ['awaiting_approval', 'queued', 'running', 'rejected', 'cancelled', 'interrupted'],
    'awaiting_approval': ['queued', 'running', 'rejected', 'cancelled', 'interrupted'],
    'queued': ['awaiting_approval', 'running', 'rejected', 'cancelled', 'interrupted'],
    'running': ['completed', 'rejected', 'cancelled', 'interrupted'],
    'completed': [],
    'rejected': [],
    'cancelled': [],
    'interrupted': [],
}


class ToolStatus(BaseModel):
    namespace: str = Field(min_length=1, max_length=128)
    schema_version: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=200)


class Evidence(BaseModel):
    kind: str = Field(max_length=128)
    adapter_version: str = Field(max_length=128)
    verified: bool = False
    conflict: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class Attempt(BaseModel):
    model_config = ConfigDict(extra='forbid')
    attempt_id: UUID
    attempt_index: int = Field(ge=1, le=100)
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    execution_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    outcome: Literal['pending', 'success', 'failure', 'rejected', 'cancelled', 'unknown']
    evidence: str = Field(max_length=128)
    trace_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    span_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{16}$')


class Call(BaseModel):
    # Extension fields are retained; bounded preview/identity fields are explicit.
    model_config = ConfigDict(extra='allow')
    tool_call_id: UUID
    tool_key: str = Field(min_length=1, max_length=80)
    tool_definition_id: UUID | None = None
    tool_name: str = Field(min_length=1, max_length=200)
    tool_type: str = Field(min_length=1, max_length=32)
    implementation_version: str | None = Field(default=None, max_length=128)
    agent_id: UUID | None = None
    agent_name: str | None = Field(default=None, max_length=256)
    model_id: str | None = Field(default=None, max_length=128)
    session_id: UUID | None = None
    session_title: str | None = Field(default=None, max_length=256)
    turn_id: UUID | None = None
    turn_input_preview: str | None = Field(default=None, max_length=1024)
    provider_round_id: UUID | None = None
    tenant_id: UUID | None = None
    requested_at: AwareDatetime
    updated_at: AwareDatetime
    terminal_at: AwareDatetime | None = None
    lifecycle_status: Literal[
        'requested',
        'awaiting_approval',
        'queued',
        'running',
        'completed',
        'rejected',
        'cancelled',
        'interrupted',
    ]
    execution_outcome: Literal['pending', 'success', 'failure', 'rejected', 'cancelled', 'unknown']
    execution_started: bool | None
    status_evidence: Evidence
    tool_status: ToolStatus | None = None
    error_stage: (
        Literal[
            'validation', 'authorization', 'approval', 'execution', 'result_processing', 'result_persistence'
        ]
        | None
    ) = None
    error_code: str | None = Field(default=None, max_length=128)
    attempts: list[Attempt] = Field(default_factory=list, max_length=100)
    attempts_complete: bool = False
    execution_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    dispatch_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    model_return_chars: int | None = Field(default=None, ge=0, le=BIGINT_MAX)
    model_return_bytes: int | None = Field(default=None, ge=0, le=BIGINT_MAX)
    result_original_bytes: int | None = Field(default=None, ge=0, le=BIGINT_MAX)
    output_truncated: bool | None = None
    result_summary: str | None = Field(default=None, max_length=2048)
    trace_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    span_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{16}$')
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def consistent(self):
        encoded = self.model_dump(mode='json')
        canonical(encoded)  # Reject non-finite numbers, including extension/evidence fields.

        def validate_strings(value):
            if isinstance(value, str) and '\x00' in value:
                raise ValueError('NUL is not supported in PostgreSQL JSON')
            if isinstance(value, dict):
                for key, item in value.items():
                    validate_strings(key)
                    validate_strings(item)
            elif isinstance(value, list):
                for item in value:
                    validate_strings(item)

        validate_strings(encoded)
        if self.tool_definition_id is not None and self.tool_key != f'db:{self.tool_definition_id}':
            raise ValueError('tool_key does not match definition')
        if self.tool_definition_id is None and not (
            self.tool_key == 'unresolved:' + hashlib.sha256(self.tool_name.encode()).hexdigest()
        ):
            raise ValueError('Unresolved tool_key must hash the original name')
        if self.updated_at < self.requested_at or (self.terminal_at and self.terminal_at < self.requested_at):
            raise ValueError('Invalid time ordering')
        if self.lifecycle_status in ACTIVE_STATES:
            if self.execution_outcome != 'pending' or self.terminal_at is not None:
                raise ValueError('Active calls require a pending result and no terminal time')
        elif self.terminal_at is None or self.execution_outcome == 'pending':
            raise ValueError('Terminal calls require a terminal time and non-pending result')
        if self.lifecycle_status == 'rejected' and self.execution_started is not False:
            raise ValueError('A rejected call has not executed')
        if self.lifecycle_status in {'running', 'completed'} and self.execution_started is not True:
            raise ValueError('Running/completed calls require an execution boundary')
        if self.execution_started is not True and (self.attempts or self.execution_ms is not None):
            raise ValueError('Execution measurements require an observed execution')
        if len({a.attempt_id for a in self.attempts}) != len(self.attempts) or len(
            {a.attempt_index for a in self.attempts}
        ) != len(self.attempts):
            raise ValueError('Duplicate attempt identity')
        for attempt in self.attempts:
            if attempt.ended_at and attempt.ended_at < attempt.started_at:
                raise ValueError('Invalid attempt time ordering')
            if attempt.execution_ms is not None and attempt.ended_at is None:
                raise ValueError('Measured attempts require an end time')
            for value in (attempt.trace_id, attempt.span_id):
                if value and int(value, 16) == 0:
                    raise ValueError('Trace/Span IDs cannot be all zero')
        for value in (self.trace_id, self.span_id):
            if value and int(value, 16) == 0:
                raise ValueError('Trace/Span IDs cannot be all zero')
        if self.attempts_complete and (
            not self.attempts or any(a.ended_at is None or a.execution_ms is None for a in self.attempts)
        ):
            raise ValueError('Complete attempts require all measured end times')
        if self.execution_ms is not None and (
            not self.attempts_complete
            or not self.attempts
            or any(a.execution_ms is None for a in self.attempts)
            or not math.isclose(self.execution_ms, sum(a.execution_ms for a in self.attempts), abs_tol=0.01)
        ):
            raise ValueError('Execution duration requires complete measured attempts')
        for key in ('parameters_preview', 'result_preview'):
            value = getattr(self, key, None)
            if value is not None and len(json.dumps(value, ensure_ascii=False)) > 4096:
                raise ValueError('Preview exceeds limit')
        if len(canonical(self.attributes).encode()) > 8192:
            raise ValueError('Attributes exceed limit')
        return self


class Observation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1]
    event_id: UUID
    revision: int = Field(ge=1, le=9223372036854775807)
    event_type: Literal[
        'call.requested',
        'call.updated',
        'attempt.started',
        'attempt.finished',
        'call.result_committed',
        'call.result_replaced',
        'call.interrupted',
    ]
    occurred_at: AwareDatetime
    source_system: Literal['cestc-claw']
    source_instance_id: UUID
    call: Call


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def normalize_call(call: Call) -> dict:
    snapshot = call.model_dump(mode='json')
    evidence = snapshot['status_evidence']
    raw, adapter = evidence['raw'], evidence['adapter_version']
    verified, conflict = False, False
    claimed, outcome = call.execution_outcome, 'unknown'
    if claimed == 'pending' and call.lifecycle_status in ACTIVE_STATES:
        outcome = 'pending'
    elif adapter in {'core-result/1', 'legacy-structured/1', 'mcp-result/1'}:
        error = raw.get('isError') if adapter == 'mcp-result/1' else raw.get('is_error')
        if isinstance(error, bool):
            outcome = 'failure' if error else 'success'
            if (
                error
                and call.execution_started is False
                and call.lifecycle_status == 'rejected'
                and call.error_stage in {'validation', 'authorization', 'approval'}
            ):
                outcome = 'rejected'
            if raw.get('process_status') == 'cancelled' and error:
                outcome = 'cancelled'
            conflict = (
                outcome != claimed
                or (not error and bool(raw.get('error_code')))
                or (not error and raw.get('exit_code') not in (None, 0))
                or (not error and raw.get('process_status') in {'timed_out', 'cancelled', 'not_started'})
            )
            verified = not conflict and (outcome != 'success' or call.execution_started is True)
    elif adapter == 'executor-exception/1' and raw.get('exception_type'):
        outcome = 'cancelled' if raw.get('cancelled') is True else 'failure'
        verified = outcome == claimed and (
            call.execution_started is True
            or (outcome == 'cancelled' and call.lifecycle_status == 'cancelled')
        )
        conflict = outcome != claimed
    if not verified and outcome != 'pending':
        outcome = 'unknown'
    snapshot['execution_outcome'] = outcome
    evidence.update(verified=verified, conflict=conflict)
    status = snapshot.get('tool_status') or {}
    identity = [
        snapshot['tool_key'],
        snapshot.get('implementation_version'),
        status.get('namespace'),
        status.get('schema_version'),
        status.get('code'),
        outcome,
    ]
    snapshot['_status_identity'] = identity
    return snapshot


def status_key(source: str, snapshot: dict) -> str:
    digest = hashlib.sha256(canonical([source, *snapshot['_status_identity']]).encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip('=')
