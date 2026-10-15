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
  value == null ? '未采集' : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
const percent = (value: number | null | undefined) =>
  value == null ? '无样本' : `${(value * 100).toFixed(1)}%`;
const duration = (value: number | null | undefined) =>
  value == null ? '未采集' : `${(value / 1000).toFixed(3)}s`;
const selectStyle = 'h-9 rounded-md border bg-background px-3 text-sm';
const outcomeNames: Record<string, string> = {
  pending: '待完成',
  success: '成功',
  failure: '失败',
  rejected: '拒绝',
  cancelled: '取消',
  unknown: '未知',
};
const lifecycleNames: Record<string, string> = {
  requested: '已请求',
  awaiting_approval: '待审批',
  queued: '排队中',
  running: '执行中',
  completed: '已结束',
  rejected: '已拒绝',
  cancelled: '已取消',
  interrupted: '已中断',
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
        共 {total} 条 · 第 {Math.floor(offset / 50) + 1} 页
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={!offset}
        onClick={() => setOffset(Math.max(0, offset - 50))}
      >
        上一页
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={offset + 50 >= total}
        onClick={() => setOffset(offset + 50)}
      >
        下一页
      </Button>
    </div>
  );
}

function SummaryLine({ data }: { data: Summary }) {
  return (
    <dl className="grid grid-cols-2 gap-5 border-y py-4 md:grid-cols-4">
      {[
        ['请求次数', number(data.request_count)],
        ['已执行调用', number(data.executed_call_count)],
        ['已知结果成功率', percent(data.known_success_rate)],
        ['执行 P95', duration(data.execution_p95_ms)],
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
      <h2 className="font-medium">状态汇总</h2>
      <p className="text-xs text-muted-foreground">
        按每次调用的最新状态计数。生命周期 8 类，执行结果 6 类；两层分别统计，不能相加。
      </p>
      {group('生命周期', data.lifecycle_summary, lifecycle, setLifecycle)}
      {group('执行结果', data.outcome_summary, outcome, setOutcome)}
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">状态含义与流转</summary>
        <div className="mt-3 space-y-2 text-muted-foreground">
          <p>正常：已请求 → 排队中 → 执行中 → 已结束。无需排队时可直接执行。</p>
          <p>需审批：已请求 → 待审批 → 排队中 / 执行中；审批拒绝进入已拒绝。</p>
          <p>执行前拒绝进入已拒绝。取消进入已取消。进程中断、恢复后无法确认终态时进入已中断。</p>
          <p>兼容入口可在排队后检查审批；执行器内部校验拒绝时，会纠正为未执行的已拒绝。</p>
          <p>
            已结束包含成功和失败。超时是失败的原因。已中断通常结果未知；未上报状态不等于失败。重试作为同一调用的
            Attempt 记录，不把生命周期重置为已请求。
          </p>
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
            {Object.entries(data.transitions).map(([from, tos]) => (
              <Fragment key={from}>
                <dt>{lifecycleNames[from]}</dt>
                <dd>
                  {tos.length
                    ? tos.map((to) => lifecycleNames[to]).join(' / ')
                    : '终态；后续仅补充证据与结果信息'}
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
  if (query.isLoading) return <p role="status">正在读取调用详情…</p>;
  if (query.error) return <p role="alert">调用详情读取失败：{query.error.message}</p>;
  const data = query.data;
  if (!data) return null;
  const pairs = [
    ['Tool Definition ID', data.tool_definition_id],
    ['Tool Call ID', data.tool_call_id],
    ['Session ID', data.session_id],
    ['会话标题', data.session_title],
    ['Turn ID', data.turn_id],
    ['本轮输入', data.turn_input_preview],
    ['生命周期', lifecycleNames[data.lifecycle_status]],
    ['执行结果', outcomeNames[data.execution_outcome]],
    ['Trace ID', data.trace_id],
    ['Span ID', data.span_id],
  ];
  return (
    <div className="min-w-0 space-y-4 bg-muted/30 p-4">
      <h3 className="font-medium">Tool Call / 单次调用</h3>
      <dl className="grid gap-x-5 gap-y-2 text-sm sm:grid-cols-[140px_minmax(0,1fr)]">
        {pairs.map(([label, value]) => (
          <Fragment key={label}>
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="break-all">{value || '未采集'}</dd>
          </Fragment>
        ))}
      </dl>
      {data.trace_id && (
        <Link
          className="text-primary underline"
          href={`/traces?trace_id=${encodeURIComponent(data.trace_id)}`}
        >
          View Trace / 查看 Trace
        </Link>
      )}
      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <section>
          <h4>Parameters / 参数</h4>
          <CodeViewer
            code={
              data.parameters_preview == null
                ? '未采集'
                : JSON.stringify(data.parameters_preview, null, 2)
            }
          />
        </section>
        <section>
          <h4>Result / 结果</h4>
          <CodeViewer
            code={
              data.result_preview == null ? '未采集' : JSON.stringify(data.result_preview, null, 2)
            }
          />
        </section>
      </div>
      {data.error_code && (
        <p>
          Error / 错误：{data.error_stage} · {data.error_code}
        </p>
      )}
      {Boolean(data.revision_gaps?.length) && (
        <p className="text-sm text-muted-foreground">
          事件版本有缺口：{data.revision_gaps?.map((gap) => `${gap.from}–${gap.to}`).join('、')}
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
        <summary className="cursor-pointer">Attempt / 状态证据与原始字段</summary>
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
  if (detail.isLoading) return <p role="status">正在读取工具详情…</p>;
  if (detail.error) return <p role="alert">工具详情读取失败：{detail.error.message}</p>;
  const data = detail.data;
  if (!data) return null;
  const search = callSearchFields.find((field) => field.key === searchField)!;
  const selected = data.status_groups.find((group) => group.status_key === status);
  return (
    <div className="space-y-6">
      <Link className="text-sm text-primary" href="/tool-analysis">
        ← 工具列表
      </Link>
      <header>
        <h1 className="text-2xl font-medium">{data.tool.tool_name || toolKey}</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {data.tool.description || '未采集工具说明'}
        </p>
        <p className="mt-2 break-all font-mono text-xs">
          Tool Definition ID：{data.tool.tool_definition_id || '未解析'} · {data.tool.tool_type} ·{' '}
          {data.tool.versions.length > 1
            ? `多个版本（${data.tool.versions.map((v) => v || '未采集').join('、')}）`
            : data.tool.implementation_version || '实现版本未采集'}
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
        <h2 className="mb-2 font-medium">工具上报状态</h2>
        <p className="mb-2 text-xs text-muted-foreground">
          仅统计已观察到执行的调用。状态名称来自埋点；未执行的拒绝和审批等待见状态汇总。
        </p>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>工具原始状态</TableHead>
              <TableHead>平台结果</TableHead>
              <TableHead>实现版本</TableHead>
              <TableHead>调用数</TableHead>
              <TableHead>占比</TableHead>
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
                    {group.tool_status?.label || group.tool_status?.code || '未上报'}
                  </button>
                  <div className="text-xs text-muted-foreground">
                    {group.tool_status?.namespace} · {group.tool_status?.code || '—'}
                    {group.evidence_summary.conflict_count > 0 ? ' · 存在证据冲突' : ''}
                  </div>
                </TableCell>
                <TableCell>{outcomeNames[group.execution_outcome]}</TableCell>
                <TableCell>{group.implementation_version || '未采集'}</TableCell>
                <TableCell>{group.call_count}</TableCell>
                <TableCell>{percent(group.ratio)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {!data.status_groups.length && (
          <p className="py-4 text-sm text-muted-foreground">当前范围没有已执行调用</p>
        )}
      </section>
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-medium">
            调用记录
            {status
              ? ` · ${selected?.tool_status?.label || selected?.tool_status?.code || '未上报'}`
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
              清除调用状态筛选
            </Button>
          )}
        </div>
        <div className="flex max-w-2xl flex-wrap items-center gap-2">
          <label className="text-sm">
            搜索{' '}
            <select
              className={selectStyle}
              aria-label="搜索字段"
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
            aria-label={`搜索${search.label}`}
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
            当前筛选：{lifecycleNames[lifecycle]} {outcomeNames[outcome]} · 与搜索条件取交集
          </p>
        )}
        {calls.isFetching && (
          <p role="status" className="text-sm text-muted-foreground">
            正在读取调用记录…
          </p>
        )}
        {calls.error && <p role="alert">调用记录读取失败：{calls.error.message}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>调用 / 时间</TableHead>
              <TableHead>Agent</TableHead>
              <TableHead>Session / Turn</TableHead>
              <TableHead>生命周期 / 执行结果</TableHead>
              <TableHead>工具状态</TableHead>
              <TableHead>执行耗时</TableHead>
              <TableHead>结果摘要</TableHead>
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
                  <TableCell>{call.agent_name || call.agent_id || '未采集'}</TableCell>
                  <TableCell className="max-w-56 break-all font-mono text-xs">
                    {call.session_id || 'Session 未采集'}
                    <div className="mt-1 text-muted-foreground">
                      {call.turn_id || 'Turn 未采集'}
                    </div>
                  </TableCell>
                  <TableCell>
                    {lifecycleNames[call.lifecycle_status]}
                    <div>{outcomeNames[call.execution_outcome]}</div>
                  </TableCell>
                  <TableCell>
                    {call.tool_status?.label || call.tool_status?.code || '未上报'}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">{duration(call.execution_ms)}</TableCell>
                  <TableCell>{call.result_summary || '未采集'}</TableCell>
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
          <p className="py-6 text-center text-muted-foreground">没有匹配的调用记录</p>
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
        <summary className="cursor-pointer text-sm">更多指标与统计口径</summary>
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          {[
            ['结果未知', number(data.summary.unknown_count)],
            ['可信终态覆盖率', percent(data.summary.terminal_status_coverage)],
            ['执行耗时样本数', number(data.summary.execution_sample_count)],
            ['平均执行耗时', duration(data.summary.execution_avg_ms)],
            ['显式重试调用', number(data.summary.observed_retry_call_count)],
            [
              '重试测量覆盖',
              `${data.summary.retry_covered_call_count} / ${data.summary.request_count} 次调用`,
            ],
            ['重复候选', number(data.summary.duplicate_candidate_count)],
            ['模型回传中位长度', number(data.summary.model_return_median_chars) + ' 字符'],
            ['结果截断比例', percent(data.summary.truncation_rate)],
          ].map(([label, value]) => (
            <div key={label}>
              {label}：{value}
            </div>
          ))}
        </dl>
        <p className="mt-3 text-xs text-muted-foreground">
          成功率只统计有可信结果的已执行调用。耗时仅使用完整尝试测量；未知与未采集不填
          0。搜索和调用状态筛选不改变上方汇总。
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
            ['模型', model, setModel, choices.data?.models],
            ...(!source ? [['类型', type, setType, choices.data?.types] as const] : []),
          ] as const
        ).map(([label, value, setValue, options]) => (
          <label key={label} className="text-sm">
            {label}{' '}
            <select
              aria-label={`${label}筛选`}
              className={selectStyle}
              value={value}
              onChange={(event) => {
                setValue(event.target.value);
                setOffset(0);
              }}
            >
              <option value="">全部</option>
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
          刷新
        </Button>
      </div>
      {!rangeValid ? (
        <p role="alert">请选择不超过 30 天的时间范围</p>
      ) : !project ? (
        <p>请选择项目</p>
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
          <h1 className="text-2xl font-medium">Tool Analysis / 工具分析</h1>
          <div className="flex flex-wrap gap-3">
            <Input
              className="max-w-sm"
              aria-label="搜索工具"
              placeholder="搜索工具名或定义 ID"
              value={listInput}
              onChange={(event) => setListInput(event.target.value)}
              maxLength={256}
            />
            <select
              aria-label="工具排序"
              className={selectStyle}
              value={sort}
              onChange={(event) => {
                setSort(event.target.value);
                setOffset(0);
              }}
            >
              <option value="request_count">请求次数最多</option>
              <option value="known_success_rate">成功率最低</option>
              <option value="execution_p95_ms">执行 P95 最长</option>
            </select>
          </div>
          {query.isLoading && <p role="status">正在读取工具列表…</p>}
          {query.error && <p role="alert">工具列表读取失败：{query.error.message}</p>}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>工具</TableHead>
                <TableHead>请求 / 已执行</TableHead>
                <TableHead>已知结果成功率</TableHead>
                <TableHead>拒绝 / 失败</TableHead>
                <TableHead>执行耗时</TableHead>
                <TableHead>显式重试</TableHead>
                <TableHead>回传中位长度</TableHead>
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
                    <div className="text-xs text-muted-foreground">
                      使用 Agent {item.agent_count}
                    </div>
                  </TableCell>
                  <TableCell>
                    {percent(item.known_success_rate)}
                    <div className="text-xs text-muted-foreground">
                      未知 {item.unknown_count} · 覆盖 {percent(item.terminal_status_coverage)}
                    </div>
                  </TableCell>
                  <TableCell>
                    参数 {item.validation_rejected_count} · 权限 {item.authorization_rejected_count}
                    <div className="text-xs text-muted-foreground">
                      执行失败 {item.execution_failure_count}
                    </div>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    均值 {duration(item.execution_avg_ms)}
                    <div className="text-xs text-muted-foreground">
                      P95 {duration(item.execution_p95_ms)}
                    </div>
                  </TableCell>
                  <TableCell>
                    已观察 {item.observed_retry_call_count}
                    <div className="text-xs text-muted-foreground">
                      覆盖 {item.retry_covered_call_count} / {item.request_count}
                    </div>
                  </TableCell>
                  <TableCell>
                    {number(item.model_return_median_chars)} 字符
                    <div className="text-xs text-muted-foreground">
                      截断 {percent(item.truncation_rate)}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {query.data?.total === 0 && (
            <p className="py-8 text-center text-muted-foreground">当前范围无数据</p>
          )}
          <Pagination total={query.data?.total || 0} offset={offset} setOffset={setOffset} />
        </>
      )}
    </main>
  );
}
