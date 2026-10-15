-- 工具分析第一版数据库结构，核对日期 2026-10-15。
-- 本文件只作跨仓库结构对照，不直接执行，以下两段属于不同的现有数据库。
-- AgentOps 权威迁移：../../../app/api/agentops/tool_analysis/{migrate.py,001.sql}
-- cestc-claw 权威定义：cestc-claw 仓库 backend/app/models/tool_telemetry.py
-- cestc-claw Alembic：add_tool_telemetry（父版本 add_platform_notifications）
-- 统计 SQL 以 AgentOps tool_analysis/repository.py:SUMMARY 和 views.py 为准。
-- 尚未采集的耗时、指纹与重复候选不在本契约中虚构专列。

-- A. AgentOps PostgreSQL，由 initialize 调用 migrate()。
-- 此版本表由 migrate.py 在事务与 advisory lock 内创建；checksum 不匹配即拒绝。
CREATE TABLE IF NOT EXISTS public.tool_analysis_schema_versions (
 version integer PRIMARY KEY,
 checksum char(64) NOT NULL,
 applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.tool_analysis_sources (
 project_id uuid NOT NULL REFERENCES public.projects(id), source_instance_id uuid NOT NULL,
 source_system text NOT NULL CHECK (source_system='cestc-claw'), tenant_id uuid,
 name text NOT NULL, enabled boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(project_id,source_instance_id)
);
CREATE TABLE public.tool_analysis_calls (
 project_id uuid NOT NULL, source_instance_id uuid NOT NULL, tool_call_id uuid NOT NULL,
 revision bigint NOT NULL CHECK(revision>0), requested_at timestamptz NOT NULL,
 source_updated_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
 tool_key varchar(80) NOT NULL, tool_definition_id uuid, tool_name varchar(200) NOT NULL,
 tool_type varchar(32) NOT NULL, implementation_version varchar(128),
 agent_id uuid, model_id varchar(128), session_id uuid, turn_id uuid, provider_round_id uuid,
 lifecycle_status varchar(32) NOT NULL CHECK(lifecycle_status IN ('requested','awaiting_approval','queued','running','completed','rejected','cancelled','interrupted')),
 execution_outcome varchar(16) NOT NULL CHECK(execution_outcome IN ('pending','success','failure','rejected','cancelled','unknown')),
 execution_started boolean, status_verified boolean NOT NULL, status_conflict boolean NOT NULL,
 status_key varchar(43) NOT NULL, execution_ms double precision, dispatch_ms double precision,
 attempts_complete boolean NOT NULL, model_return_chars bigint, output_truncated boolean,
 snapshot jsonb NOT NULL CHECK(jsonb_typeof(snapshot)='object'),
 CHECK(execution_ms IS NULL OR (execution_ms >= 0 AND execution_ms < 'Infinity'::double precision)),
 CHECK(dispatch_ms IS NULL OR (dispatch_ms >= 0 AND dispatch_ms < 'Infinity'::double precision)),
 CHECK(model_return_chars IS NULL OR model_return_chars >= 0),
 PRIMARY KEY(project_id,source_instance_id,tool_call_id),
 FOREIGN KEY(project_id,source_instance_id) REFERENCES public.tool_analysis_sources(project_id,source_instance_id)
);
CREATE INDEX tool_analysis_tools_idx ON public.tool_analysis_calls
 (project_id,source_instance_id,tool_key,requested_at DESC,tool_call_id DESC);
CREATE INDEX tool_analysis_time_idx ON public.tool_analysis_calls(project_id,requested_at DESC);
CREATE INDEX tool_analysis_session_idx ON public.tool_analysis_calls(project_id,source_instance_id,session_id,turn_id);
CREATE TABLE public.tool_analysis_events (
 project_id uuid NOT NULL, source_instance_id uuid NOT NULL, event_id uuid NOT NULL,
 tool_call_id uuid NOT NULL, revision bigint NOT NULL CHECK(revision>0), event_type varchar(48) NOT NULL,
 occurred_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
 payload_sha256 char(64) NOT NULL, envelope jsonb NOT NULL,
 PRIMARY KEY(project_id,source_instance_id,event_id), UNIQUE(project_id,source_instance_id,tool_call_id,revision),
 FOREIGN KEY(project_id,source_instance_id,tool_call_id)
 REFERENCES public.tool_analysis_calls(project_id,source_instance_id,tool_call_id) ON DELETE CASCADE
);
CREATE INDEX tool_analysis_events_call_idx ON public.tool_analysis_events(project_id,source_instance_id,tool_call_id,revision);

-- B. cestc-claw PostgreSQL，由独立 Alembic revision 创建。
-- 下列 DDL 从 SQLAlchemy 模型编译；delivery_attempts=0 是应用端默认值。
CREATE TABLE tool_telemetry_state (
	source_instance_id UUID NOT NULL,
	tool_call_id UUID NOT NULL,
	revision BIGINT NOT NULL,
	snapshot JSONB NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (source_instance_id, tool_call_id)
);

CREATE TABLE tool_telemetry_outbox (
	event_id UUID NOT NULL,
	source_instance_id UUID NOT NULL,
	tool_call_id UUID NOT NULL,
	revision BIGINT NOT NULL,
	envelope JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	next_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	delivery_attempts INTEGER NOT NULL,
	lease_token UUID,
	lease_until TIMESTAMP WITH TIME ZONE,
	acked_at TIMESTAMP WITH TIME ZONE,
	quarantined_at TIMESTAMP WITH TIME ZONE,
	last_error_code VARCHAR(128),
	PRIMARY KEY (event_id),
	UNIQUE (source_instance_id, tool_call_id, revision)
);
CREATE INDEX ix_tool_telemetry_outbox_next_attempt_at ON tool_telemetry_outbox (next_attempt_at);
CREATE INDEX ix_tool_telemetry_outbox_source_instance_id ON tool_telemetry_outbox (source_instance_id);
