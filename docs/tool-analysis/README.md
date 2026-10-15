# 工具分析第一版接入

状态：第一版已在两仓库实现并通过本地验证，服务器尚未部署。以下命令用于后续服务器接入，不代表已经执行。

## 已实现

AgentOps 增加 `Tool Analysis` 导航、一个工具列表、详情和单次调用展开。详情包括公共指标、状态汇总、动态原始状态、分字段搜索及调用分页；调用常驻展示 Session ID / Turn ID。

cestc-claw 增加定义快照、RuntimeLite 与旧执行入口观测、MCP 结果证据、结果回传长度和本地 Outbox。观测默认关闭；发送失败只重发观测事件，不重做工具动作。两仓库继续使用各自已有的 PostgreSQL，不增加应用或数据库实例。

## 状态口径

| 生命周期（8 类） | 含义 |
|---|---|
| requested 已请求 | 请求已记录 |
| awaiting_approval 待审批 | 等待审批，尚未执行 |
| queued 排队中 | 请求等待进入执行入口 |
| running 执行中 | 已进入可观察执行边界 |
| completed 已结束 | 执行结束，结果另行判断 |
| rejected 已拒绝 | 参数、权限或审批拒绝，未执行 |
| cancelled 已取消 | 来源明确取消 |
| interrupted 已中断 | 来源确认中断或缺少终态证据 |

执行结果另分 `pending / success / failure / rejected / cancelled / unknown` 6 类。工具原始状态是埋点上报的 namespace / schema_version / code，可随工具变化，不在页面写死。

正常路径：`已请求 → 排队中 → 执行中 → 已结束`。无需排队可直接执行。审批是可选分支，通过后排队或执行，拒绝后进入已拒绝；旧入口可能排队后才检查审批。执行器内部发现参数/权限拒绝时，最终修正为未执行，移除执行计量。

取消和中断可结束活跃调用。已结束包含成功和失败，超时属于失败原因。重试按 Attempt 记录；终态不能因较新事件回到活跃状态。审批自动续接同一个调用尚未接通。

生命周期和结果分别按唯一调用的最新快照计数，事件和 Span 不增加调用数。点击任意汇总状态只筛选调用表，上方汇总保持当前工具公共范围。工具原始状态分布只统计 `execution_started=true` 的调用。

## AgentOps 部署与来源绑定

更新代码后，需要重新构建 AgentOps API / initialize 和 Dashboard。项目现有 initialize 会执行新表迁移；也可在 API 容器内单独执行：

```bash
docker compose exec api python -m agentops.tool_analysis.migrate
```

迁移使用事务、advisory lock 和 checksum，只新增工具分析表，不重置现有账户或数据库。不要手工执行文档中的 DDL 绕过迁移账本。

从 AgentOps 当前项目取得项目 ID 和项目 API key。为 cestc-claw 当前部署生成并固定一个 UUID，多副本共用，重启不变；不同环境分开。

```bash
docker compose exec api python -m agentops.tool_analysis.manage_source \
  --project-id '<AgentOps 项目 UUID>' \
  --source-instance-id '<cestc-claw 部署 UUID>' \
  --tenant-id '<cestc-claw 租户 UUID>' \
  --name 'cestc-claw 测试环境'
```

无租户的独立安装将 `--tenant-id ...` 替换为 `--tenant-none`。一个项目只对应同一个租户及环境；来源必须提前注册。未注册来源或 tenant 不匹配返回 403，不允许首次上报自动认领。

上报入口是 `POST /v1/tool-analysis/events`。来源先用项目 API key 从原版 `/v3/auth/token` 换 JWT；浏览器查询继续使用已有 Cookie 登录与项目组织成员权限。

若域名代理只放行列出的路径，需要同时代理 `/v3/auth/token`、`/v1/tool-analysis/events` 和 `/v4/tool-analysis/` 至 AgentOps API；API 根地址不包含这些后缀。

## cestc-claw 配置

在服务器自身 `.env` 中配置，不填写进仓库示例：

```dotenv
AGENTOPS_TOOL_ENABLED=true
AGENTOPS_API_URL=http://agentops.example.internal
AGENTOPS_API_KEY=<AgentOps 当前项目的 API key>
AGENTOPS_SOURCE_INSTANCE_ID=<上面绑定的部署 UUID>
AGENTOPS_TOOL_TENANT_ID=<上面绑定的租户 UUID>
AGENTOPS_TOOL_INCLUDE_TEXT_PREVIEWS=false
```

`AGENTOPS_TOOL_TENANT_ID` 为空时只采集无租户调用，不表示采集所有租户。它必须与来源注册一致。

默认仅上报允许的参数摘要、结构化状态、数值长度与关联 ID，不上报文件正文和代码。开启 `AGENTOPS_TOOL_INCLUDE_TEXT_PREVIEWS` 后才采集脱敏会话标题与本轮输入，页面相应文字搜索才有数据。

更新后重建 cestc-claw 后台，使配置和新增代码生效。新增 Alembic revision 为 `add_tool_telemetry`，父版本为 `add_platform_notifications`；仓库原有其他 head 未合并。已有库应由运维核对当前迁移版本，再对该分支执行 `alembic upgrade add_tool_telemetry`。本版不清库、不删除卷。

不需要重新发布或安装 AgentOps SDK wheel。发送器已在 cestc-claw 内部实现。

## 首版限制

- 耗时记录执行适配器边界，包含内部校验与工具 I/O，排除观测写入及框架结果物化/持久化。参数/权限拒绝最终不算执行。尚未逐工具拆到文件打开或进程启动边界。
- `dispatch_ms`、审批/容量等待、结果处理和持久化分时尚未采集；返回空值。
- 旧文本返回没有可信协议证据时结果为未知。MCP 保留显式 isError；未捕获外部客户端内部每次重试，不提供伪造的完整 attempt 数。
- 仅关联宿主已有真实 OTel 上下文，不主动创建 Trace / Span。没有上下文时显示未采集；本版不完成全链路 SDK 接入。
- 参数指纹和重复候选未实现，`duplicate_candidate_count=null`。
- 审批自动续接、趋势与版本对比、业务结果有效性、精确工具 token 成本尚未实现。
- 详情样本数放在 summary 中，没有独立 coverage 对象。返回列表保留共享项目/时间，不保留名称、Agent、模型等组件内筛选。

AgentOps 接收事实保留 30 天，收到该来源新事件时清理其过期调用。来源 Outbox 确认/隔离记录保留 7 天，状态保留 30 天；发送器定期清理。

## 队列排查

在 cestc-claw PostgreSQL 中查看待发与隔离数量：

```sql
SELECT
  count(*) FILTER (WHERE acked_at IS NULL AND quarantined_at IS NULL) AS pending,
  min(created_at) FILTER (WHERE acked_at IS NULL AND quarantined_at IS NULL) AS oldest_pending,
  count(*) FILTER (WHERE quarantined_at IS NOT NULL) AS quarantined
FROM tool_telemetry_outbox;
```

查看隔离原因，不输出事件正文或凭证：

```sql
SELECT event_id, tool_call_id, revision, delivery_attempts, last_error_code
FROM tool_telemetry_outbox
WHERE quarantined_at IS NOT NULL
ORDER BY quarantined_at DESC
LIMIT 20;
```

`accepted / duplicate / superseded` 均确认收件；`invalid / conflict / expired` 和来源 403 隔离。413 拆批，网络错误/429/5xx 退避，401 刷新 JWT。日志中的 `telemetry_gap` 表示观测缺口，不驱动业务重试。

## 本地验证

2026-10-15 本地结果：AgentOps 接收与查询 16 项、来源观测与 PostgreSQL 22 项、原有 RuntimeLite/推理重试/文件/Office 回归 90 项，共 128 项通过。Dashboard TypeScript 检查、新增 Python 模块 lint 与格式检查通过。数据库验证使用本机临时 PGlite PostgreSQL，未连接服务器数据。

已覆盖来源观测隔离、计时、审批/拒绝、取消、MCP 证据、Outbox ACK 与退避，以及接收去重/乱序/冲突、鉴权、全范围搜索/分页和两端事件契约。原有 RuntimeLite、推理重试、文件与 Office 回归通过。

浏览器用临时 PostgreSQL 与虚构数据验证列表下钻、调用展开、完整 ID 精确匹配、不完整 ID 空结果、字段切换清空、后续页记录搜索、状态交集与分页。它不代表服务器真实数据已经接入。

事件格式与数据库结构见 [上报示例](./contracts/call-observation.example.json) 和 [结构对照](./contracts/storage.sql)。
