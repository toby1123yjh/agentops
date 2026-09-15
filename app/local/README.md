# 本地模式（无 Supabase 服务）

复用原版 Dashboard、项目管理、权限检查、Trace 和 Metrics 查询。使用独立 PostgreSQL、ClickHouse 和原有 OTLP Collector；不使用 Supabase 服务，不绕过登录。

这是面向本机开发的模式，端口只绑定 `127.0.0.1`。不用于公开部署。云模式仍是默认行为；`AGENTOPS_LOCAL_MODE=true` 切换 API，Dashboard 的 `NEXT_PUBLIC_AGENTOPS_LOCAL_MODE=true` 在构建时生效。

## 启动

需要 Docker Engine / Docker Desktop 的 Linux 容器和 Docker Compose v2。Windows 可用 Docker Desktop + WSL2。没有 Docker 时不能仅靠启动 Dashboard 得到完整系统。

在仓库 `app/` 目录，将 `local/env.example` 复制为 `.env.local-mode`，设置本地登录邮箱、至少 12 位的密码，以及独立的数据库密码、Cookie 签名密钥和 SDK JWT 签名密钥。两个签名密钥各自至少 32 个随机字符；不要复用生产凭据，不要提交此文件。可用密码管理器生成。

```sh
docker compose --env-file .env.local-mode -f compose.local.yaml up -d --build
docker compose --env-file .env.local-mode -f compose.local.yaml ps
```

打开 `http://localhost:3000/signin`，使用配置中的本地账号登录。首次初始化自动建立本地工作区和项目。项目 API Key 在原版项目页面查看。

初始化会等待两套数据库健康，完成后才启动 API 和 Dashboard。重复启动不重设密码或 API Key；修改初始化环境变量不会覆盖数据库中的现有账号。PostgreSQL 和 ClickHouse 使用本模式专有数据卷，不连接 cestc-claw 业务库。初始化拒绝未标记的非空数据库。

```sh
# 查看启动错误；不要将含凭据的 docker compose config 输出发给他人。
docker compose --env-file .env.local-mode -f compose.local.yaml logs --tail=100 initialize api dashboard otelcollector
# 停止服务但保留数据卷。
docker compose --env-file .env.local-mode -f compose.local.yaml stop
```

不要使用 `down -v` 作为日常停止方式，它会删除本地数据库卷。此模式固定使用 3000、8000、4318；启动前检查端口占用。

## 修改 Dashboard 时的启动方式

数据库、API 和采集器仍由 Docker 运行，Dashboard 可单独热更新。先从 `app/` 启动后端：

```sh
docker compose --env-file .env.local-mode -f compose.local.yaml up -d --build api otelcollector
```

若此前已启动 Compose 中的 Dashboard，先执行 `docker compose --env-file .env.local-mode -f compose.local.yaml stop dashboard`，释放 3000 端口。

在 `app/dashboard/` 使用 Node.js 20 和 Bun 1.2.15：

```sh
bun install --frozen-lockfile --ignore-scripts
npm run dev:local
```

Windows 若 Bun 安装报文件移动 `EPERM`，可在安装命令末尾加 `--backend=copyfile`。使用仓库的 `bun.lock` 和 API 的 `uv.lock` 固定依赖，不用无锁的 `npm install` 更新间接依赖。`dev:local` 使用 Webpack，使本地字体替换生效；不要改用原 `dev --turbo` 命令。此方式也需要运行中的本地 API，不是模拟数据页面。

## SDK 接入

保留现有 SDK，显式指定自托管端点，不使用默认云端地址：

```text
AGENTOPS_API_KEY=<本地项目页面中的 API Key>
AGENTOPS_API_ENDPOINT=http://localhost:8000
AGENTOPS_EXPORTER_ENDPOINT=http://localhost:4318/v1/traces
AGENTOPS_APP_URL=http://localhost:3000
```

首个验证使用普通 Trace / Span 示例，不发送真实业务内容。文件和日志附件上传尚未提供本地存储适配，SDK 示例需关闭这些可选上传能力。Trace / Span 的结构化记录仍通过 OTLP 写入 ClickHouse。

## 首版范围

- 支持本地初始化账号、密码登录、持久化会话、退出、项目列表 / 创建 / 修改 / API Key 管理及原有 Trace / Metrics 查询。
- 原有项目权限仍由 API 检查。本地模式不是 anonymous / playground 模式。
- 不开放公共注册、找回密码、OAuth、邮件邀请、Stripe、MCP 云服务、云部署、历史 v1/v2 SDK 接口和 Supabase 文件 / 日志附件上传。
- 本地 Dashboard 禁用 PostHog、Sentry 初始化、云端代理和相关云功能入口；字体使用本地资源。构建仍需要下载 npm/Python 依赖和 Docker 镜像，不是离线安装包。
- 账号增加、密码轮换、完整文件存储及生产级多实例限流不在此开发模式首版中。登录限流为单进程每分钟 10 次，本地会话持久化在 PostgreSQL。

## 验证边界

新增测试覆盖本地配置、登录、会话 Cookie、未登录访问、跨站请求、云路由隔离与 Compose 结构。运行测试不应连接真实数据库或发送遥测。

2026-09-15：26 项 Python 模拟测试与 2 项 Node 配置测试通过；覆盖空库初始化保护、保留已有账号、ClickHouse 初始化失败不标记完成及重试。命令在 `app/` 执行，Python 环境需已安装 API 依赖及 `pytest`、`PyYAML`：

```sh
python -m pytest -c local/pytest.ini local/tests --confcutdir=local/tests --tb=short
node --test local/tests/test-dashboard-config.cjs
```

本机使用 Node.js 24.19.0、Bun 锁定依赖及本地模式环境变量完成 Next.js 生产构建、类型检查和 ESLint 检查。仍有上游未使用变量、`any` 类型及 OpenTelemetry 动态依赖警告。容器使用 Node.js 20，尚未执行镜像构建与运行验收；本次未升级上游框架，不能用于公网部署。

完整验收仍需 Docker 环境：首次启动、登录和项目创建、SDK 上报、Trace 查询、重启持久化。本地环境若没有 Docker，不能把静态检查或模拟测试当作这些环节已通过。
