# 服务器部署

AgentOps 使用独立 Compose，统一启动 PostgreSQL、ClickHouse、API、Dashboard 和 OTLP Collector。数据库及数据卷由本项目管理，不需要手动创建数据库或连接外部数据库网络。

## 1. 配置

首次部署在仓库 `app/` 目录执行：

```sh
cp .env.example .env
chmod 600 .env
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

在 `app/` 目录执行。Compose 自动读取默认 `compose.yaml` 和 `.env`：

```sh
docker compose up -d --build
docker compose ps -a
```

初始化等待两套数据库健康后建立表、管理员和项目。`initialize` 以 `Exited (0)` 结束是正常结果，其余五个服务保持运行。重复初始化不会重设已有管理员密码或 API Key。

查看日志：

```sh
docker compose logs --tail=200 initialize api dashboard otelcollector
```

## 4. 更新已有部署

使用旧 `.env.server-mode` 的服务器，将现有配置复制成 `.env`。保留原数据库密码、登录账号和认证密钥；不要用示例覆盖已有配置。在 `app/` 目录执行：

```sh
cp -n .env.server-mode .env
chmod 600 .env
```

`cp -n` 会保留已经存在的 `.env`；已有该文件时，手动补齐所需 AgentOps 变量。切换端口时修改以下三项，并同步 Nginx 的转发目标：

```text
AGENTOPS_DASHBOARD_PORT=38621
AGENTOPS_API_PORT=38622
AGENTOPS_OTLP_PORT=38623
```

拉取代码、修改配置后，重新执行 `docker compose up -d --build`。项目名继续使用 `agentops-server`，沿用原 PostgreSQL 和 ClickHouse 数据卷；无需删除旧容器或数据库卷。

旧的 `compose.server.yaml` 仍可用于原有带参数命令，它引用默认配置，不再维护第二套服务定义。

日常停止并保留数据：

```sh
docker compose stop
```

不要执行 `down -v`，它会删除 PostgreSQL 和 ClickHouse 数据卷。
