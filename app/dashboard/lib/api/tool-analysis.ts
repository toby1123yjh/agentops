import { fetchAuthenticatedApi } from '@/lib/api-client';

export const callSearchFields = [
  {
    key: 'tool_call_id',
    label: 'Tool Call ID',
    placeholder: 'Enter a full Tool Call ID (exact match)',
  },
  { key: 'session_id', label: 'Session ID', placeholder: 'Enter a full Session ID (exact match)' },
  { key: 'turn_id', label: 'Turn ID', placeholder: 'Enter a full Turn ID (exact match)' },
  { key: 'session_title', label: 'Session Title', placeholder: 'Search session titles' },
  { key: 'turn_input_preview', label: 'Turn Input', placeholder: 'Search turn inputs' },
  { key: 'agent_name', label: 'Agent Name', placeholder: 'Search agent names' },
  { key: 'result_summary', label: 'Result Summary', placeholder: 'Search result summaries' },
] as const;

export interface Summary {
  request_count: number;
  executed_call_count: number;
  agent_count: number;
  known_success_rate: number | null;
  terminal_status_coverage: number | null;
  unknown_count: number;
  validation_rejected_count: number;
  authorization_rejected_count: number;
  execution_failure_count: number;
  execution_avg_ms: number | null;
  execution_p95_ms: number | null;
  execution_sample_count: number;
  observed_retry_call_count: number;
  retry_covered_call_count: number;
  duplicate_candidate_count: number | null;
  model_return_median_chars: number | null;
  truncation_rate: number | null;
}
export interface Tool extends Summary {
  source_instance_id: string;
  tool_key: string;
  tool_definition_id: string | null;
  tool_name: string | null;
  tool_type: string | null;
}
export interface StateCount {
  code: string;
  label: string;
  count: number;
}
export interface ToolStatus {
  namespace: string;
  schema_version: string;
  code: string;
  label?: string;
}
export interface ToolDetail {
  tool: Pick<
    Tool,
    'source_instance_id' | 'tool_key' | 'tool_definition_id' | 'tool_name' | 'tool_type'
  > & {
    description?: string;
    implementation_version?: string;
    executor_name?: string;
    tool_schema_hash?: string;
    versions: (string | null)[];
  };
  summary: Summary;
  lifecycle_summary: StateCount[];
  outcome_summary: StateCount[];
  transitions: Record<string, string[]>;
  status_groups: {
    status_key: string;
    tool_status: ToolStatus | null;
    execution_outcome: string;
    implementation_version: string | null;
    call_count: number;
    ratio: number | null;
    evidence_summary: { verified_count: number; unverified_count: number; conflict_count: number };
  }[];
}
export interface ToolCall {
  tool_call_id: string;
  tool_definition_id: string | null;
  tool_name: string;
  agent_id?: string;
  agent_name?: string;
  session_id: string | null;
  session_title?: string;
  turn_id: string | null;
  turn_number?: number;
  turn_input_preview?: string;
  requested_at: string;
  lifecycle_status: string;
  execution_outcome: string;
  tool_status: ToolStatus | null;
  execution_ms: number | null;
  parameters_preview?: unknown;
  result_preview?: unknown;
  error_code?: string;
  error_stage?: string;
  result_summary?: string;
  trace_id?: string;
  span_id?: string;
  status_evidence: { verified: boolean; conflict: boolean; kind: string; adapter_version: string };
  attempts: unknown[];
  events?: {
    event_id: string;
    revision: number;
    event_type: string;
    occurred_at: string;
    received_at: string;
  }[];
  revision_gaps?: { from: number; to: number }[];
}
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  as_of?: string;
}

export function toolAnalysisPath(project: string, source?: string, tool?: string) {
  const base = `/v4/tool-analysis/projects/${encodeURIComponent(project)}`;
  return source && tool
    ? `${base}/tools/${encodeURIComponent(source)}/${encodeURIComponent(tool)}`
    : `${base}/tools`;
}
export function getToolAnalysis<T>(
  path: string,
  params: Record<string, string | number | undefined>,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== '') query.set(key, String(value));
  return fetchAuthenticatedApi<T>(`${path}?${query}`, { signal });
}
