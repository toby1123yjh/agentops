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
