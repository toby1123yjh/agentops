# 服务器部署

此模式复用现有 PostgreSQL 实例，但使用独立空数据库和独立非超级用户。Compose 不创建 PostgreSQL 容器，也不管理它的数据卷。ClickHouse 仍由 AgentOps 独立管理。

## 1. 准备 PostgreSQL

由 PostgreSQL 管理员创建专用账号和数据库。不要使用 cestc-claw 的业务账号或业务数据库。

```sql
CREATE ROLE agentops LOGIN PASSWORD '<独立随机密码>';
CREATE DATABASE agentops OWNER agentops;
```

数据库必须为空。AgentOps 初始化程序会拒绝覆盖已有业务表的数据库。

## 2. 准备 Docker 网络

创建只用于 AgentOps 访问数据库的外部网络，并把现有 PostgreSQL 容器接入该网络。将 `<postgres-container>` 替换为真实容器名。

```sh
docker network create agentops-db
docker network connect --alias postgres-agentops agentops-db <postgres-container>
```

重复执行 `docker network connect` 会报已连接；先用 `docker network inspect agentops-db` 核对即可。不要断开 PostgreSQL 原有网络。

## 3. 配置

在 `app/` 目录执行：

```sh
cp server/env.example .env.server-mode
chmod 600 .env.server-mode
```

填写真实域名、独立数据库凭据、登录账号和随机密钥。`AGENTOPS_PUBLIC_URL` 必须是完整的 HTTP 或 HTTPS origin，不能带路径。

HTTP 测试环境示例：

```text
AGENTOPS_PUBLIC_URL=http://agentops-dev.cestc.cn
```

HTTPS 生产环境示例：

```text
AGENTOPS_PUBLIC_URL=https://agentops.cestc.cn
```

Dashboard 在镜像构建时写入公开 URL。修改该变量后必须重新构建 Dashboard，不能只重启容器。

## 4. 启动

```sh
docker compose --env-file .env.server-mode -f compose.server.yaml config --quiet
docker compose --env-file .env.server-mode -f compose.server.yaml up -d --build
docker compose --env-file .env.server-mode -f compose.server.yaml ps
```

初始化会等待外部 PostgreSQL，默认最多等待 60 秒。首次成功后建立 AgentOps 表、管理员和项目；重复启动不会重设密码或 API Key。

查看日志：

```sh
docker compose --env-file .env.server-mode -f compose.server.yaml logs --tail=200 initialize api dashboard otelcollector
```

宿主机默认只在 loopback 发布 `32170`、`32171` 和 `32172`。Nginx 代理 Dashboard 和 API。OTLP 不对公网开放；同机服务使用 `http://127.0.0.1:32172/v1/traces`。

日常停止但保留 ClickHouse 数据：

```sh
docker compose --env-file .env.server-mode -f compose.server.yaml stop
```

不要执行 `down -v`，它会删除 AgentOps ClickHouse 数据卷。
