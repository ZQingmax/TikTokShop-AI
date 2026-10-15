# Windows 本地启动（AI 关闭）

本文保留基础启动的首轮说明。后续已增加真实 AI 选品和妙手货源服务，使用独立配置及 Worker；最新验收见 [妙手集成报告](MIAOSHOU_INTEGRATION_REPORT.md)。

当前本地服务：

| 服务 | 地址 |
|---|---|
| Vue 管理后台 | http://127.0.0.1:3000 |
| 后端健康检查 | http://127.0.0.1:8000/v1/health |
| 项目专用 PostgreSQL 15 | 127.0.0.1:5433 |

演示管理员：`admin@tiktok-ops.com` / `admin123`。

## 再次启动

在项目根目录运行：

```powershell
./scripts/start-local.ps1
```

脚本使用项目内 `.venv` 和 `.runtime`，后台进程不弹出终端窗口。
日志位于 `.runtime/logs/`。端口已被占用时不会启动重复进程。

数据库为独立的 `tiktok_ops_local`，仅首次新建时注入演示数据。
已有数据库会直接保留，不会重复清空或重建。
历史本地初始化使用 ORM 建表。后续选品实施已修复 Alembic 多 head，并在独立测试库验证后将本机库迁移至 `554b31562dd4`；其他数据库须单独审计和验证，不能直接 stamp。

## AI 和外部服务

基础启动脚本不启动 Agent，旧客服/履约保持模拟模式。真实选品服务使用独立的模型配置；启动 `./scripts/start-sourcing-local.ps1` 后，由 PostgreSQL Worker 调用已配置的百炼和 DeepSeek。凭证配置、数据库验证及真实验收见 [选品实施记录](AI_SOURCING_PHASE1_IMPLEMENTATION.md) 和 [妙手集成报告](MIAOSHOU_INTEGRATION_REPORT.md)。
后端客服使用本地规则和模拟回复；TikTok、1688 保持模拟模式。
OpenAI SDK 是现有后端导入所需的软件依赖，模拟模式不创建 API 客户端。
本地浏览后台不需要 MinIO、RabbitMQ 或爬虫 worker；这些服务未启动。
已有 Redis 不做修改。

## 从零准备依赖

需要 Node.js、uv 和一个可用的 Python 3.11/3.12 解释器：

```powershell
uv venv --python <Python解释器路径> .venv
uv pip install --python .venv/Scripts/python.exe -r backend/requirements-local.txt
npm.cmd --prefix frontend ci
npm.cmd install --prefix .runtime/postgres @embedded-postgres/windows-x64@15.18.0-beta.17 --ignore-scripts --no-audit --no-fund
```

首次运行前，在项目根目录初始化全新的 PostgreSQL 数据目录：

```powershell
New-Item -ItemType Directory -Force .runtime | Out-Null
Set-Content -LiteralPath .runtime/postgres-password.txt -Value 'tiktok_ops_dev' -Encoding ascii
& './.runtime/postgres/node_modules/@embedded-postgres/windows-x64/native/bin/initdb.exe' -D '.runtime/pgdata' -U tiktok_ops --pwfile='.runtime/postgres-password.txt' --auth-host=scram-sha-256 --auth-local=trust --encoding=UTF8 --locale=C
Remove-Item -LiteralPath .runtime/postgres-password.txt
./scripts/start-local.ps1
```

已初始化的目录无需再次执行 `initdb`。

## 本次验证

- 前端 `npm run build` 通过。
- 前后端 HTTP 服务可访问。
- 通过前端 `/api` 代理登录，验证当前用户及商品、订单、采购单、运单、客服会话、财务流水、财务汇总和仪表盘查询。
- 基础启动首轮未启动 Agent、未做外部平台和 AI 联调；后续真实选品/妙手联调已完成，见最新集成报告。
