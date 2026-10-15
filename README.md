# TikTok 跨境电商运营系统

面向 TikTok Shop 的运营后台，以妙手 ERP 为商品、店铺和订单数据入口，提供选品、货源采集、AI 商品编辑、上架任务、订单履约查询、财务汇总和系统设置。

当前为持续开发中的 MVP。真实业务能力依赖账号授权、服务端配置、数据库迁移和 Worker。自动采购、付款、物流发货及全链路无人值守仍需独立实施与验收。本文按 2026-10-15 的代码整理；历史报告只代表对应轮次的范围。

## 当前功能

| 页面 / 模块 | 当前能力与边界 |
|---|---|
| 仪表盘 | 妙手数据统计、近期订单、销售趋势和同步状态；空数据展示空态 |
| 商品管理 | 同步妙手 TikTok 采集箱；区分成本、店铺 SKU 售价、站点币种和库存 |
| 选品中心 | FastMoss 新品榜、市场证据导入、候选库、自动发现、百炼视觉与 DeepSeek 评估、人工审核 |
| 1688 货源中心 | 独立 1688 CLI 登录态查询；支持本机调用或宿主机 Adapter |
| 采集上架 | 我的采集箱、商品工作台、OCR / 文案 / 图片处理、类目与 SKU、草稿检查、妙手同步及发布任务 |
| 订单管理 | 读取妙手包裹 / 订单、手动同步；订单 Worker 约每 10 分钟检查同步需求 |
| 履约管理 | 采购单、待出库和运单查询；不代表自动采购、付款和真实发货已完成 |
| 客服管理 | 会话和回复处理；基础本地配置使用规则及模拟回复 |
| 财务管理 | 流水与汇总、人民币汇率维护、缺失汇率提示；不等同于支付结算或完整会计系统 |
| 系统设置 | 修改密码、角色及用户角色管理、按场景选择百炼模型、模型用量查询 |
| 登录与外观 | 记住我、退出返回登录页；管理员右侧“太阳图标 + 主题”，支持蓝白、绿白、紫白、黄白、护眼深色，本机保存选择 |

选品审核、保存草稿、同步采集箱和正式发布是不同操作。发布前检查店铺模式资料；写请求结果不确定时查询、核对，不自动重复提交。

## 技术与目录

| 层级 | 当前技术 |
|---|---|
| 前端 | Vue 3、TypeScript、Vite 5、Element Plus、Pinia、ECharts |
| API | Python 3.11+、FastAPI、SQLAlchemy 2、Alembic |
| 业务任务与存储 | PostgreSQL 15、持久化任务、租约及 advisory lock |
| AI | 百炼 / DashScope、DeepSeek；按场景设置和服务端配置选择模型 |
| 外部数据 | 妙手 OpenAPI、1688 CLI、FastMoss 浏览器适配 |

以下组件属于历史代码或预留配置，未接入当前管理后台主流程，不作为当前必需技术栈：

| 组件 | 仓库现状 | 当前主流程 |
|---|---|---|
| LangGraph / LangChain | `agent/` 有独立 API、图编排、模型服务和工具 | 前端与业务后端未调用该服务；AI 任务由后端 Worker 直接调用模型 |
| Scrapy | `scraper/` 有爬虫、解析器和数据库管道 | 现有货源入口为妙手、1688 CLI 和 FastMoss，未接入此 Scrapy 服务 |
| Redis | 有配置、依赖和懒初始化客户端；后端退出时保留关闭钩子 | 未发现业务调用 `get_redis()`；不依赖 Redis 服务 |
| MinIO | 有 Compose 服务、配置字段和完整依赖列表中的包 | 未发现上传 / 下载接入；工作台使用本地资产副本及妙手图片空间 |
| RabbitMQ / Celery | 有基础设施配置和旧物流任务，部分任务为 TODO | 当前任务使用 PostgreSQL 与 asyncio Worker；未发现完整 Celery 应用与调度入口 |

```text
backend/       FastAPI、模型、迁移、业务 Worker、测试及管理脚本
frontend/      Vue 管理后台
agent/         历史独立 LangGraph 服务，未接入当前后台主流程
scraper/       历史 Scrapy 实现，未接入当前货源流程
instructions/  当前需求、验收、风险、协同约定与历史规划
docs/          分模块使用与实施说明
scripts/       Windows 启动、迁移检查及验证脚本
infra/         基础设施配置
.runtime/      本机数据库、日志、工具与工作台图片副本（运行时生成）
```

## Windows 本地启动

建议使用 Python 3.11 / 3.12、Node.js 20、PowerShell。从零准备 `.venv`、项目专用 PostgreSQL 和前端依赖，按 [本地准备说明](docs/LOCAL_STARTUP.md) 执行。

依赖已就绪时，在项目根目录运行：

```powershell
./scripts/start-local.ps1
```

| 服务 | 默认地址 / 位置 |
|---|---|
| 管理后台 | [http://127.0.0.1:3000](http://127.0.0.1:3000) |
| 健康检查 | [http://127.0.0.1:8000/v1/health](http://127.0.0.1:8000/v1/health) |
| 业务 API | `http://127.0.0.1:8000/api/v1/…`，前端通过 `/api` 代理 |
| 本机 PostgreSQL | `127.0.0.1:5433`，业务库 `tiktok_ops_local` |
| 日志与进程记录 | `.runtime/logs/` |

本地初始化演示账号：`admin@tiktok-ops.com` / `admin123`，仅用于开发环境。已有数据库会保留，不要对已有数据目录重复执行 `initdb`。

脚本使用固定端口 `3000 --strictPort`，端口占用时不会替换现有进程。单独运行 Vite 时可能递增到 3001 等端口，以终端输出为准。

基础脚本保留旧业务模拟配置，不启动独立 Agent、FastMoss Worker 或业务任务 Worker。它设置 `DEBUG=false`，默认不开放 `/docs`、`/redoc`；调试文档需自行配置并重启后端。

## 真实选品、工作台和同步

1. 根据 [选品配置示例](backend/.env.sourcing.example) 和 [工作台配置示例](backend/.env.workbench.example)，将所需配置写入 `backend/.env`，保留已有配置，填写服务端妙手及模型凭证。
2. 备份业务数据，在独立测试库验证迁移后，再在 `backend` 目录、正确的 `DATABASE_URL` 下执行 `alembic upgrade head`。旧 ORM 初始化库需先核对迁移历史，不能直接 `stamp head`。
3. 在项目根目录启动或重启后端与组合 Worker：

   ```powershell
   ./scripts/start-sourcing-local.ps1
   ```

该脚本检查选品 schema，不自动执行迁移。组合入口 `python -m app.services.sourcing_worker` 同时运行选品、妙手采集、自动发现、工作台、发布及订单同步。启动后可能消费已有任务、产生模型调用和外部写入。

FastMoss 另需本机工具、浏览器扩展和登录态，按 [FastMoss 说明](docs/FASTMOSS_INTEGRATION.md) 准备，再运行 `./scripts/start-fastmoss-local.ps1`。1688 CLI 见 [1688 集成说明](docs/ALIBABA1688_CLI_INTEGRATION.md)。这些任务不要求启动独立 `agent/` 服务。

百炼模型选择和用量在系统设置中管理；DeepSeek 等场景仍按服务端配置。模型默认值见示例文件，用量和参考价格不等同于供应商实际账单。工作台图片副本默认保存在 `.runtime/workbench-assets`，应作为持久化资产备份。

## 开发与验证

前端：

```powershell
cd frontend
npm ci
npm run dev
npm run build
```

`build` 包含 Vue / TypeScript 类型检查。`npm run lint` 默认带 `--fix`，`npm run format` 会修改文件。

后端按用途选择 `backend/requirements-local.txt`、`backend/requirements-test.txt` 或完整的 `backend/requirements.txt`。从 `backend` 运行单元测试：

```powershell
../.venv/Scripts/python.exe -m pytest unit_tests -q
```

集成测试要求显式 `TEST_DATABASE_URL`，库名以 `_test` 结尾且与 `DATABASE_URL` 不同。测试会清空测试库模型表；先准备独立测试库、执行迁移，再运行 `pytest tests -q`，见 [验收与测试基线](instructions/附录A-验收标准与测试方案.md)。

`docker-compose.yml` 定义 PostgreSQL、Redis、MinIO、RabbitMQ；其中后三项是当前主流程未使用的历史基础设施配置。`docker-compose.dev.yml` 保留独立 Agent 和旧爬虫 Worker：爬虫命令引用的 `scraper.tasks` 模块不存在，不能将这套配置视为已可用的完整开发启动方案。当前 Windows 启动以本文脚本为准。

Compose 与 Windows 本机方案的数据库端口不同。Makefile 和 CI 仍有历史配置，旧命令及容错通过不能当作当前验收完成。历史文件与未使用依赖仍保留，后续清理需同时检查启动、导入、测试和配置引用。

## 文档

- [instructions 总索引与当前边界](instructions/README.md)
- [当前详细需求](instructions/TikTok跨境电商全自动运营系统-详细需求说明书V1.0.md)、[MVP 范围](instructions/需求MVP简化版.MD)
- [实施计划](instructions/MVP详细开发计划-6周分阶段执行方案.md)、[验收与测试](instructions/附录A-验收标准与测试方案.md)
- [风险与恢复](instructions/附录B-风险评估与应急预案.md)、[开发协同](instructions/开发团队多Agent协同配置完整文档.md)
- [妙手 API 参考](<instructions/妙手开放平台-API接口文档 (1).md>)、[首轮集成记录](docs/MIAOSHOU_INTEGRATION_REPORT.md)
- [AI 选品实施](docs/AI_SOURCING_PHASE1_IMPLEMENTATION.md)、[自动发现来源审计](docs/PRODUCT_DISCOVERY_SOURCE_AUDIT.md)
- [商品工作台](docs/PRODUCT_WORKBENCH.md)、[工作台实施](docs/PRODUCT_WORKBENCH_IMPLEMENTATION.md)
- [1688 CLI](docs/ALIBABA1688_CLI_INTEGRATION.md)、[FastMoss](docs/FASTMOSS_INTEGRATION.md)、[本地环境准备](docs/LOCAL_STARTUP.md)
