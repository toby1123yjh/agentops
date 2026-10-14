# AgentOps 自托管部署

默认 Compose 统一启动独立 PostgreSQL、ClickHouse、API、Dashboard 和 OTLP Collector。

在本目录首次部署：

```sh
cp .env.example .env
chmod 600 .env
```

填写 `.env` 中的访问地址、管理员邮箱及密码、两套数据库密码和两项认证密钥。管理员密码至少 12 位，认证密钥各至少 32 位。访问地址使用 Nginx 提供的完整 HTTP 或 HTTPS origin。

启动、查看状态和日志：

```sh
docker compose up -d --build
docker compose ps -a
docker compose logs --tail=200 initialize api dashboard otelcollector
```

默认宿主机端口为 `38621`（页面）、`38622`（API）和 `38623`（采集），只绑定 `127.0.0.1`。数据库不发布宿主机端口。Nginx 转发、已有服务器迁移和更新方法见 [服务器部署说明](server/README.md)。

`initialize` 以 `Exited (0)` 结束是正常结果，其余五个服务保持运行。

本机开发见 [local/README.md](local/README.md)。上游 Supabase 部署保留在 [README.cloud.md](README.cloud.md)，使用 `compose.cloud.yaml` 和 `.env.cloud.example`。
