'use client';

import { Fragment, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { useProject } from '@/app/providers/project-provider';
import ProjectSelector from '@/components/ui/project-selector';
import { DateRangePicker } from '@/components/ui/date-range-picker';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { CodeViewer } from '../traces/_components/event-visualizers/tool-span';
import {
  callSearchFields,
  getToolAnalysis,
  Page,
  StateCount,
  Summary,
  Tool,
  ToolCall,
  ToolDetail,
  toolAnalysisPath,
} from '@/lib/api/tool-analysis';

const number = (value: number | null | undefined) =>
  value == null ? 'Not collected' : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
const percent = (value: number | null | undefined) =>
  value == null ? 'No samples' : `${(value * 100).toFixed(1)}%`;
const duration = (value: number | null | undefined) =>
  value == null ? 'Not collected' : `${(value / 1000).toFixed(3)}s`;
const selectStyle = 'h-9 rounded-md border bg-background px-3 text-sm';
const outcomeNames: Record<string, string> = {
  pending: 'Pending',
  success: 'Success',
  failure: 'Failure',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
  unknown: 'Unknown',
};
const lifecycleNames: Record<string, string> = {
  requested: 'Requested',
  awaiting_approval: 'Awaiting Approval',
  queued: 'Queued',
  running: 'Running',
  completed: 'Completed',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
  interrupted: 'Interrupted',
};

function Pagination({
  total,
  offset,
  setOffset,
}: {
  total: number;
  offset: number;
  setOffset: (n: number) => void;
}) {
  return (
    <div className="flex items-center justify-end gap-3 py-4 text-sm">
      <span>
        {total} records · Page {Math.floor(offset / 50) + 1}
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={!offset}
        onClick={() => setOffset(Math.max(0, offset - 50))}
      >
        Previous
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={offset + 50 >= total}
        onClick={() => setOffset(offset + 50)}
      >
        Next
      </Button>
    </div>
  );
}

function SummaryLine({ data }: { data: Summary }) {
  return (
    <dl className="grid grid-cols-2 gap-5 border-y py-4 md:grid-cols-4">
      {[
        ['Requests', number(data.request_count)],
        ['Executed Calls', number(data.executed_call_count)],
        ['Success Rate (Known Outcomes)', percent(data.known_success_rate)],
        ['P95 Execution Time', duration(data.execution_p95_ms)],
      ].map(([label, value]) => (
        <div key={label}>
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="mt-1 text-2xl font-medium tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function StateSummary({
  data,
  lifecycle,
  outcome,
  setLifecycle,
  setOutcome,
}: {
  data: ToolDetail;
  lifecycle: string;
  outcome: string;
  setLifecycle: (v: string) => void;
  setOutcome: (v: string) => void;
}) {
  const group = (
    title: string,
    states: StateCount[],
    selected: string,
    change: (v: string) => void,
  ) => (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-20 text-sm text-muted-foreground">{title}</span>
      {states.map((item) => (
        <Button
          key={item.code}
          size="sm"
          variant={selected === item.code ? 'secondary' : 'ghost'}
          aria-pressed={selected === item.code}
          onClick={() => change(selected === item.code ? '' : item.code)}
        >
          {item.label} <span className="ml-2 tabular-nums">{item.count}</span>
        </Button>
      ))}
    </div>
  );
  return (
    <section className="space-y-3">
      <h2 className="font-medium">Status Summary</h2>
      <p className="text-xs text-muted-foreground">
        Counts use the latest state of each call. The 8 lifecycle states and 6 execution outcomes
        are counted separately; do not add them together.
      </p>
      {group('Lifecycle', data.lifecycle_summary, lifecycle, setLifecycle)}
      {group('Outcome', data.outcome_summary, outcome, setOutcome)}
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">
          State Definitions and Transitions
        </summary>
        <div className="mt-3 space-y-2 text-muted-foreground">
          <p>Normal flow: Requested → Queued → Running → Completed. Calls can skip the queue.</p>
          <p>
            Approval required: Requested → Awaiting Approval → Queued / Running. Denied approval
            moves the call to Rejected.
          </p>
          <p>
            Calls rejected before execution are marked Rejected. Cancelled calls are marked
            Cancelled. Calls interrupted by a process exit or with no confirmed terminal state after
            recovery are marked Interrupted.
          </p>
          <p>
            Legacy entry points may check approval after queuing. Validation failures inside the
            executor are recorded as Rejected without execution.
          </p>
          <p>
            Completed includes successful and failed calls. A timeout is a failure reason.
            Interrupted calls usually have an unknown outcome; a missing status does not indicate
            failure. Retries are recorded as attempts within the same call and do not reset its
            lifecycle to Requested.
          </p>
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
            {Object.entries(data.transitions).map(([from, tos]) => (
              <Fragment key={from}>
                <dt>{lifecycleNames[from]}</dt>
                <dd>
                  {tos.length
                    ? tos.map((to) => lifecycleNames[to]).join(' / ')
                    : 'Terminal state; only evidence and result details can be updated'}
                </dd>
              </Fragment>
            ))}
          </dl>
        </div>
      </details>
    </section>
  );
}

function CallEvidence({
  project,
  source,
  call,
}: {
  project: string;
  source: string;
  call: ToolCall;
}) {
  const query = useQuery({
    queryKey: ['tool-call', project, source, call.tool_call_id],
    queryFn: ({ signal }) =>
      getToolAnalysis<ToolCall>(
        `/v4/tool-analysis/projects/${encodeURIComponent(project)}/calls/${encodeURIComponent(source)}/${encodeURIComponent(call.tool_call_id)}`,
        {},
        signal,
      ),
  });
  if (query.isLoading) return <p role="status">Loading call details…</p>;
  if (query.error) return <p role="alert">Failed to load call details: {query.error.message}</p>;
  const data = query.data;
  if (!data) return null;
  const pairs = [
    ['Tool Definition ID', data.tool_definition_id],
    ['Tool Call ID', data.tool_call_id],
    ['Session ID', data.session_id],
    ['Session Title', data.session_title],
    ['Turn ID', data.turn_id],
    ['Turn Input', data.turn_input_preview],
    ['Lifecycle', lifecycleNames[data.lifecycle_status]],
    ['Execution Outcome', outcomeNames[data.execution_outcome]],
    ['Trace ID', data.trace_id],
    ['Span ID', data.span_id],
  ];
  return (
    <div className="min-w-0 space-y-4 bg-muted/30 p-4">
      <h3 className="font-medium">Tool Call</h3>
      <dl className="grid gap-x-5 gap-y-2 text-sm sm:grid-cols-[140px_minmax(0,1fr)]">
        {pairs.map(([label, value]) => (
          <Fragment key={label}>
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="break-all">{value || 'Not collected'}</dd>
          </Fragment>
        ))}
      </dl>
      {data.trace_id && (
        <Link
          className="text-primary underline"
          href={`/traces?trace_id=${encodeURIComponent(data.trace_id)}`}
        >
          View Trace
        </Link>
      )}
      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <section>
          <h4>Parameters</h4>
          <CodeViewer
            code={
              data.parameters_preview == null
                ? 'Not collected'
                : JSON.stringify(data.parameters_preview, null, 2)
            }
          />
        </section>
        <section>
          <h4>Result</h4>
          <CodeViewer
            code={
              data.result_preview == null
                ? 'Not collected'
                : JSON.stringify(data.result_preview, null, 2)
            }
          />
        </section>
      </div>
      {data.error_code && (
        <p>
          Error: {data.error_stage} · {data.error_code}
        </p>
      )}
      {Boolean(data.revision_gaps?.length) && (
        <p className="text-sm text-muted-foreground">
          Missing event revisions:{' '}
          {data.revision_gaps?.map((gap) => `${gap.from}–${gap.to}`).join(', ')}
        </p>
      )}
      <ol className="space-y-1 text-sm">
        {data.events?.map((event) => (
          <li key={event.event_id}>
            v{event.revision} · {new Date(event.occurred_at).toLocaleString()} · {event.event_type}
          </li>
        ))}
      </ol>
      <details>
        <summary className="cursor-pointer">Attempts, Evidence, and Raw Data</summary>
        <CodeViewer code={JSON.stringify(data, null, 2)} />
      </details>
    </div>
  );
}

function ToolDetailPage({
  project,
  source,
  toolKey,
  filters,
}: {
  project: string;
  source: string;
  toolKey: string;
  filters: Record<string, string | undefined>;
}) {
  const [searchField, setSearchField] = useState<string>('tool_call_id');
  const [input, setInput] = useState('');
  const [query, setQuery] = useState('');
  const [composing, setComposing] = useState(false);
  const [status, setStatus] = useState('');
  const [lifecycle, setLifecycleState] = useState('');
  const [outcome, setOutcomeState] = useState('');
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const asOf = useRef<string | undefined>();
  const path = toolAnalysisPath(project, source, toolKey);
  const reset = () => {
    setOffset(0);
    asOf.current = undefined;
    setExpanded(null);
  };
  useEffect(() => {
    if (composing) return;
    const timer = setTimeout(() => {
      setQuery(input.trim());
      setOffset(0);
      asOf.current = undefined;
      setExpanded(null);
    }, 300);
    return () => clearTimeout(timer);
  }, [input, composing]);
  const detail = useQuery({
    queryKey: ['tool-detail', project, source, toolKey, filters],
    queryFn: ({ signal }) => getToolAnalysis<ToolDetail>(path, filters, signal),
  });
  const calls = useQuery({
    queryKey: [
      'tool-calls',
      project,
      source,
      toolKey,
      filters,
      searchField,
      query,
      status,
      lifecycle,
      outcome,
      offset,
    ],
    queryFn: ({ signal }) =>
      getToolAnalysis<Page<ToolCall>>(
        path + '/calls',
        {
          ...filters,
          search_field: searchField,
          search_value: query,
          status_key: status,
          lifecycle_status: lifecycle,
          outcome,
          offset,
          as_of: asOf.current,
        },
        signal,
      ),
  });
  useEffect(() => {
    if (calls.data?.as_of) asOf.current = calls.data.as_of;
  }, [calls.data]);
  if (detail.isLoading) return <p role="status">Loading tool details…</p>;
  if (detail.error) return <p role="alert">Failed to load tool details: {detail.error.message}</p>;
  const data = detail.data;
  if (!data) return null;
  const search = callSearchFields.find((field) => field.key === searchField)!;
  const selected = data.status_groups.find((group) => group.status_key === status);
  return (
    <div className="space-y-6">
      <Link className="text-sm text-primary" href="/tool-analysis">
        ← Tool List
      </Link>
      <header>
        <h1 className="text-2xl font-medium">{data.tool.tool_name || toolKey}</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {data.tool.description || 'Tool description not collected'}
        </p>
        <p className="mt-2 break-all font-mono text-xs">
          Tool Definition ID: {data.tool.tool_definition_id || 'Unresolved'} · {data.tool.tool_type}{' '}
          ·{' '}
          {data.tool.versions.length > 1
            ? `Multiple versions (${data.tool.versions.map((v) => v || 'Not collected').join(', ')})`
            : data.tool.implementation_version || 'Implementation version not collected'}
        </p>
      </header>
      <SummaryLine data={data.summary} />
      <StateSummary
        data={data}
        lifecycle={lifecycle}
        outcome={outcome}
        setLifecycle={(v) => {
          setLifecycleState(v);
          reset();
        }}
        setOutcome={(v) => {
          setOutcomeState(v);
          reset();
        }}
      />
      <section>
        <h2 className="mb-2 font-medium">Reported Tool Statuses</h2>
        <p className="mb-2 text-xs text-muted-foreground">
          Only calls observed to execute are counted. Status labels come from instrumentation. Calls
          rejected before execution or awaiting approval are included in the status summary.
        </p>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Raw Tool Status</TableHead>
              <TableHead>Execution Outcome</TableHead>
              <TableHead>Implementation Version</TableHead>
              <TableHead>Calls</TableHead>
              <TableHead>Share</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.status_groups.map((group) => (
              <TableRow
                key={group.status_key}
                data-state={status === group.status_key ? 'selected' : undefined}
              >
                <TableCell>
                  <button
                    className="text-left text-primary underline-offset-4 hover:underline"
                    onClick={() => {
                      setStatus(status === group.status_key ? '' : group.status_key);
                      reset();
                    }}
                  >
                    {group.tool_status?.label || group.tool_status?.code || 'Not reported'}
                  </button>
                  <div className="text-xs text-muted-foreground">
                    {group.tool_status?.namespace} · {group.tool_status?.code || '—'}
                    {group.evidence_summary.conflict_count > 0 ? ' · Conflicting evidence' : ''}
                  </div>
                </TableCell>
                <TableCell>{outcomeNames[group.execution_outcome]}</TableCell>
                <TableCell>{group.implementation_version || 'Not collected'}</TableCell>
                <TableCell>{group.call_count}</TableCell>
                <TableCell>{percent(group.ratio)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {!data.status_groups.length && (
          <p className="py-4 text-sm text-muted-foreground">No executed calls in this scope</p>
        )}
      </section>
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-medium">
            Call History
            {status
              ? ` · ${selected?.tool_status?.label || selected?.tool_status?.code || 'Not reported'}`
              : ''}
          </h2>
          {(status || lifecycle || outcome) && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setStatus('');
                setLifecycleState('');
                setOutcomeState('');
                reset();
              }}
            >
              Clear Call Filters
            </Button>
          )}
        </div>
        <div className="flex max-w-2xl flex-wrap items-center gap-2">
          <label className="text-sm">
            Search{' '}
            <select
              className={selectStyle}
              aria-label="Search field"
              value={searchField}
              onChange={(e) => {
                setSearchField(e.target.value);
                setInput('');
                setQuery('');
                reset();
              }}
            >
              {callSearchFields.map((field) => (
                <option key={field.key} value={field.key}>
                  {field.label}
                </option>
              ))}
            </select>
          </label>
          <Input
            className="min-w-0 flex-[1_1_260px]"
            type="search"
            maxLength={256}
            value={input}
            placeholder={search.placeholder}
            aria-label={`Search ${search.label}`}
            onCompositionStart={() => setComposing(true)}
            onCompositionEnd={(e) => {
              setComposing(false);
              setInput(e.currentTarget.value);
            }}
            onChange={(e) => setInput(e.target.value)}
          />
        </div>
        {(lifecycle || outcome) && (
          <p className="text-xs text-muted-foreground">
            Active filters: {lifecycleNames[lifecycle]} {outcomeNames[outcome]} · Combined with the
            search criteria
          </p>
        )}
        {calls.isFetching && (
          <p role="status" className="text-sm text-muted-foreground">
            Loading call history…
          </p>
        )}
        {calls.error && <p role="alert">Failed to load call history: {calls.error.message}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Call / Time</TableHead>
              <TableHead>Agent</TableHead>
              <TableHead>Session / Turn</TableHead>
              <TableHead>Lifecycle / Outcome</TableHead>
              <TableHead>Tool Status</TableHead>
              <TableHead>Execution Time</TableHead>
              <TableHead>Result Summary</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {calls.data?.items.map((call) => (
              <Fragment key={call.tool_call_id}>
                <TableRow>
                  <TableCell>
                    <button
                      className="max-w-48 break-all text-left font-mono text-xs text-primary"
                      onClick={() =>
                        setExpanded(expanded === call.tool_call_id ? null : call.tool_call_id)
                      }
                    >
                      {call.tool_call_id}
                    </button>
                    <div className="whitespace-nowrap text-xs text-muted-foreground">
                      {new Date(call.requested_at).toLocaleString()}
                    </div>
                  </TableCell>
                  <TableCell>{call.agent_name || call.agent_id || 'Not collected'}</TableCell>
                  <TableCell className="max-w-56 break-all font-mono text-xs">
                    {call.session_id || 'Session not collected'}
                    <div className="mt-1 text-muted-foreground">
                      {call.turn_id || 'Turn not collected'}
                    </div>
                  </TableCell>
                  <TableCell>
                    {lifecycleNames[call.lifecycle_status]}
                    <div>{outcomeNames[call.execution_outcome]}</div>
                  </TableCell>
                  <TableCell>
                    {call.tool_status?.label || call.tool_status?.code || 'Not reported'}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">{duration(call.execution_ms)}</TableCell>
                  <TableCell>{call.result_summary || 'Not collected'}</TableCell>
                </TableRow>
                {expanded === call.tool_call_id && (
                  <TableRow>
                    <TableCell colSpan={7}>
                      <CallEvidence project={project} source={source} call={call} />
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            ))}
          </TableBody>
        </Table>
        {calls.data?.total === 0 && (
          <p className="py-6 text-center text-muted-foreground">No matching calls</p>
        )}
        <Pagination
          total={calls.data?.total || 0}
          offset={offset}
          setOffset={(value) => {
            setExpanded(null);
            setOffset(value);
          }}
        />
      </section>
      <details>
        <summary className="cursor-pointer text-sm">More Metrics and Definitions</summary>
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          {[
            ['Unknown Outcomes', number(data.summary.unknown_count)],
            ['Terminal Status Coverage', percent(data.summary.terminal_status_coverage)],
            ['Execution Time Samples', number(data.summary.execution_sample_count)],
            ['Average Execution Time', duration(data.summary.execution_avg_ms)],
            ['Calls with Observed Retries', number(data.summary.observed_retry_call_count)],
            [
              'Retry Measurement Coverage',
              `${data.summary.retry_covered_call_count} / ${data.summary.request_count} calls`,
            ],
            ['Duplicate Candidates', number(data.summary.duplicate_candidate_count)],
            [
              'Median Model Return Length',
              number(data.summary.model_return_median_chars) + ' chars',
            ],
            ['Result Truncation Rate', percent(data.summary.truncation_rate)],
          ].map(([label, value]) => (
            <div key={label}>
              {label}: {value}
            </div>
          ))}
        </dl>
        <p className="mt-3 text-xs text-muted-foreground">
          Success rate includes only executed calls with known outcomes. Execution time uses
          complete attempt measurements; unknown and missing values are not treated as zero. Search
          and call status filters do not change the summaries above.
        </p>
      </details>
    </div>
  );
}

export function ToolAnalysis({ source, toolKey }: { source?: string; toolKey?: string }) {
  const router = useRouter();
  const { selectedProject, setSelectedProject, sharedDateRange, setSharedDateRange } = useProject();
  const [type, setType] = useState('');
  const [agent, setAgent] = useState('');
  const [model, setModel] = useState('');
  const [listInput, setListInput] = useState('');
  const [listQuery, setListQuery] = useState('');
  const [sort, setSort] = useState('request_count');
  const [refresh, setRefresh] = useState(0);
  const [offset, setOffset] = useState(0);
  const dateInitialized = useRef(false);
  const rangeValid =
    !!sharedDateRange.from &&
    !!sharedDateRange.to &&
    sharedDateRange.to.getTime() > sharedDateRange.from.getTime() &&
    sharedDateRange.to.getTime() - sharedDateRange.from.getTime() <= 30 * 86400000;
  useEffect(() => {
    if (dateInitialized.current) return;
    dateInitialized.current = true;
    if (!rangeValid) {
      const to = new Date();
      setSharedDateRange({ from: new Date(to.getTime() - 86400000), to });
    }
  }, [rangeValid, setSharedDateRange]);
  const filters: Record<string, string | undefined> = {
    start_time: sharedDateRange.from?.toISOString(),
    end_time: sharedDateRange.to?.toISOString(),
    tool_type: type,
    agent_id: agent,
    model_id: model,
  };
  const project = selectedProject?.id;
  const previousProject = useRef(project);
  useEffect(() => {
    if (previousProject.current !== project) {
      if (previousProject.current && source) router.replace('/tool-analysis');
      setAgent('');
      setModel('');
      setType('');
      setListInput('');
      setListQuery('');
    }
    previousProject.current = project;
    setOffset(0);
  }, [project, source, router]);
  useEffect(() => {
    const timer = setTimeout(() => {
      setListQuery(listInput.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [listInput]);
  const choices = useQuery({
    queryKey: [
      'tool-filter-options',
      project,
      source,
      toolKey,
      filters.start_time,
      filters.end_time,
      refresh,
    ],
    enabled: !!project && rangeValid,
    queryFn: ({ signal }) =>
      getToolAnalysis<
        Record<'agents' | 'models' | 'types', { value: string; label: string | null }[]>
      >(
        `/v4/tool-analysis/projects/${encodeURIComponent(project!)}/filters`,
        {
          start_time: filters.start_time,
          end_time: filters.end_time,
          source_instance_id: source,
          tool_key: toolKey,
        },
        signal,
      ),
  });
  const query = useQuery({
    queryKey: ['tool-analysis', project, filters, offset, listQuery, sort, refresh],
    enabled: !!project && !source && rangeValid,
    queryFn: ({ signal }) =>
      getToolAnalysis<Page<Tool>>(
        toolAnalysisPath(project!),
        { ...filters, offset, q: listQuery, sort_by: sort },
        signal,
      ),
  });
  return (
    <main className="min-w-0 space-y-6 p-4 md:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <ProjectSelector
          selectedProject={selectedProject}
          setSelectedProject={setSelectedProject}
        />
        <DateRangePicker
          isRanged
          defaultRange={sharedDateRange}
          onApply={(value) => {
            setSharedDateRange(value);
            setOffset(0);
          }}
        />
        {(
          [
            ['Agent', agent, setAgent, choices.data?.agents],
            ['Model', model, setModel, choices.data?.models],
            ...(!source ? [['Type', type, setType, choices.data?.types] as const] : []),
          ] as const
        ).map(([label, value, setValue, options]) => (
          <label key={label} className="text-sm">
            {label}{' '}
            <select
              aria-label={`Filter by ${label}`}
              className={selectStyle}
              value={value}
              onChange={(event) => {
                setValue(event.target.value);
                setOffset(0);
              }}
            >
              <option value="">All</option>
              {options?.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label || option.value}
                </option>
              ))}
            </select>
          </label>
        ))}
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setRefresh((v) => v + 1);
            setOffset(0);
          }}
        >
          Refresh
        </Button>
      </div>
      {!rangeValid ? (
        <p role="alert">Select a time range of up to 30 days</p>
      ) : !project ? (
        <p>Select a project</p>
      ) : source && toolKey ? (
        <ToolDetailPage
          key={JSON.stringify([project, source, toolKey, filters, refresh])}
          project={project}
          source={source}
          toolKey={toolKey}
          filters={filters}
        />
      ) : (
        <>
          <h1 className="text-2xl font-medium">Tool Analysis</h1>
          <div className="flex flex-wrap gap-3">
            <Input
              className="max-w-sm"
              aria-label="Search tools"
              placeholder="Search by tool name or definition ID"
              value={listInput}
              onChange={(event) => setListInput(event.target.value)}
              maxLength={256}
            />
            <select
              aria-label="Sort tools"
              className={selectStyle}
              value={sort}
              onChange={(event) => {
                setSort(event.target.value);
                setOffset(0);
              }}
            >
              <option value="request_count">Most requests</option>
              <option value="known_success_rate">Lowest success rate</option>
              <option value="execution_p95_ms">Longest P95 execution time</option>
            </select>
          </div>
          {query.isLoading && <p role="status">Loading tools…</p>}
          {query.error && <p role="alert">Failed to load tools: {query.error.message}</p>}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tool</TableHead>
                <TableHead>Requests / Executed</TableHead>
                <TableHead>Success Rate (Known Outcomes)</TableHead>
                <TableHead>Rejected / Failed</TableHead>
                <TableHead>Execution Time</TableHead>
                <TableHead>Observed Retries</TableHead>
                <TableHead>Median Return Length</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data?.items.map((item) => (
                <TableRow key={item.source_instance_id + item.tool_key}>
                  <TableCell>
                    <Link
                      className="text-primary"
                      href={`/tool-analysis/${encodeURIComponent(item.source_instance_id)}/${encodeURIComponent(item.tool_key)}`}
                    >
                      {item.tool_name}
                    </Link>
                    <div className="text-xs text-muted-foreground">
                      {item.tool_type} · {item.source_instance_id.slice(0, 8)}
                    </div>
                  </TableCell>
                  <TableCell>
                    {item.request_count} / {item.executed_call_count}
                    <div className="text-xs text-muted-foreground">Agents: {item.agent_count}</div>
                  </TableCell>
                  <TableCell>
                    {percent(item.known_success_rate)}
                    <div className="text-xs text-muted-foreground">
                      Unknown: {item.unknown_count} · Coverage:{' '}
                      {percent(item.terminal_status_coverage)}
                    </div>
                  </TableCell>
                  <TableCell>
                    Validation: {item.validation_rejected_count} · Authorization:{' '}
                    {item.authorization_rejected_count}
                    <div className="text-xs text-muted-foreground">
                      Failed: {item.execution_failure_count}
                    </div>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    Average: {duration(item.execution_avg_ms)}
                    <div className="text-xs text-muted-foreground">
                      P95 {duration(item.execution_p95_ms)}
                    </div>
                  </TableCell>
                  <TableCell>
                    Observed: {item.observed_retry_call_count}
                    <div className="text-xs text-muted-foreground">
                      Coverage: {item.retry_covered_call_count} / {item.request_count}
                    </div>
                  </TableCell>
                  <TableCell>
                    {number(item.model_return_median_chars)} chars
                    <div className="text-xs text-muted-foreground">
                      Truncated: {percent(item.truncation_rate)}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {query.data?.total === 0 && (
            <p className="py-8 text-center text-muted-foreground">No data in this scope</p>
          )}
          <Pagination total={query.data?.total || 0} offset={offset} setOffset={setOffset} />
        </>
      )}
    </main>
  );
}
