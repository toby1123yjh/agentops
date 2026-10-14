# 服务器部署

AgentOps 使用独立 Compose，统一启动 PostgreSQL、ClickHouse、API、Dashboard 和 OTLP Collector。数据库及数据卷由本项目管理，不需要手动创建数据库或连接外部数据库网络。

## 1. 配置

首次部署在仓库 `app/` 目录执行：

```sh
cp server/env.example .env.server-mode
chmod 600 .env.server-mode
```

填写访问地址、管理员账号、数据库密码和认证密钥。管理员密码至少 12 位；`AUTH_COOKIE_SECRET` 和 `JWT_SECRET_KEY` 分别使用至少 32 位的随机字符串。

`AGENTOPS_PUBLIC_URL` 使用 Nginx 对外提供的完整 HTTP 或 HTTPS origin，不能带路径。测试环境使用 HTTP，生产环境使用已有 Nginx 的 HTTPS 和证书。例如：

```text
AGENTOPS_PUBLIC_URL=http://agentops.example.internal
```

Dashboard 在镜像构建时写入公开 URL。修改该变量后必须重新构建 Dashboard，不能只重启容器。

宿主机默认端口：

| 服务 | 地址 | 用途 |
| --- | --- | --- |
| Dashboard | `127.0.0.1:38621` | 页面及 Dashboard 内置 API 转发 |
| API | `127.0.0.1:38622` | API、SDK 鉴权及健康检查 |
| OTLP Collector | `127.0.0.1:38623` | Trace / Span 数据采集 |

PostgreSQL 和 ClickHouse 不发布宿主机端口。`POSTGRES_PORT=5432` 是容器内部端口。

## 2. Nginx 转发

同机宿主机 Nginx 将页面请求转到 `http://127.0.0.1:38621`，将 `/auth/`、`/opsboard/`、`/v3/` 和 `/v4/` 请求转到 `http://127.0.0.1:38622`，保留原始路径。转发时设置 `Host`、`X-Forwarded-For` 和 `X-Forwarded-Proto`，公开地址与 `AGENTOPS_PUBLIC_URL` 保持一致。

Dashboard 的 `/api-v4/` 和 `/api-metrics/` 路径已有内部 API 转发，交给 Dashboard 处理。

端口只绑定宿主机 loopback。若 Nginx 在另一台服务器或容器内，需要另行配置可达的网络地址，不能用该环境自己的 `127.0.0.1`。

OTLP 不通过此页面代理公开。宿主机进程使用 `http://127.0.0.1:38623/v1/traces`；cestc-claw 等容器里的 SDK 需要可达的容器网络地址，并同时配置 API 端点及项目 API Key。

## 3. 启动

在 `app/` 目录执行，明确指定服务器模式的 Compose 文件：

```sh
docker compose --env-file .env.server-mode -f compose.server.yaml config --quiet
docker compose --env-file .env.server-mode -f compose.server.yaml up -d --build
docker compose --env-file .env.server-mode -f compose.server.yaml ps -a
```

初始化等待两套数据库健康后建立表、管理员和项目。`initialize` 以 `Exited (0)` 结束是正常结果，其余五个服务保持运行。重复初始化不会重设已有管理员密码或 API Key。

查看日志：

```sh
docker compose --env-file .env.server-mode -f compose.server.yaml logs --tail=200 initialize api dashboard otelcollector
```

## 4. 更新已有部署

保留服务器现有 `.env.server-mode`，不要用示例覆盖它。切换本次端口时修改以下三项，并同步 Nginx 的转发目标：

```text
AGENTOPS_DASHBOARD_PORT=38621
AGENTOPS_API_PORT=38622
AGENTOPS_OTLP_PORT=38623
```

拉取代码、修改配置后，重新执行上述 `up -d --build` 命令。无需删除旧容器或数据库卷，Compose 会重建有变化的服务。

日常停止并保留数据：

```sh
docker compose --env-file .env.server-mode -f compose.server.yaml stop
```

不要执行 `down -v`，它会删除 PostgreSQL 和 ClickHouse 数据卷。
