# AI 智能选品第一阶段实施与验收

实施日期：2026-10-13，Asia/Shanghai。主项目：`tiktok-ecommerce-automation-system`。

后续同日已完成妙手四接口客户端、真实链接采集及公共箱同步集成，当前数据库 head 为 `554b31562dd4`。最新接口、原始字段映射和真实验收见 [妙手集成报告](MIAOSHOU_INTEGRATION_REPORT.md)；本文保留首轮阶段记录。

## 1. 交付状态与边界

已完成候选池、妙手授权货源查询与导入、真实百炼视觉分析、真实 DeepSeek 文本分析、PostgreSQL 持久化批量任务、独立 Worker、人工审核及前端页面。真实浏览器闭环已执行，结果和审核记录刷新后仍存在。

妙手为优先数据源；手动链接、CSV/JSON 通过同一 SourceAdapter 边界作为备用入口。没有运行自建 1688 爬虫，没有读取或复制 `tk-autopilot` 源码。

审核通过只保存选品决策。本阶段没有创建 Product、ListingDraft 或虚构 TikTok 商品 ID，没有接入发布、认领、平台 SKU 映射、改价、采购、履约或订单同步。已有业务模块的本地模拟开关保持原状，新选品模块独立使用真实 provider。

首轮验收时 `fetch_item` 仅预留。收到完整 OpenAPI 文档后，后续集成已按真实字段启用最多 50 条链接采集，并完成用户指定单条商品的真实调用；详见妙手集成报告。

## 2. 代码与页面

| 部分 | 文件 | 行为 |
|---|---|---|
| 候选及评估模型 | `backend/app/models/sourcing.py` | 四张独立表，不覆盖旧 Product.score |
| 输入与输出校验 | `backend/app/schemas/sourcing.py` | 来源、链接、采购价、SKU 校验；模型严格 JSON/schema 校验 |
| 来源适配器 | `backend/app/services/sourcing_sources.py` | Miaoshou、Manual、FileImport、不可用的 Alibaba 直连边界 |
| 模型适配器 | `backend/app/services/sourcing_providers.py` | ModelProvider、百炼视觉、DeepSeek 文本；没有模拟或规则降级 |
| 事务服务 | `backend/app/services/sourcing_service.py` | 去重、资料版本、任务复用、追加审核历史 |
| 独立 Worker | `backend/app/services/sourcing_worker.py` | PostgreSQL 队列、并发槽、租约、重试、阶段结果持久化 |
| 路由 | `backend/app/api/v1/sourcing.py` | 真实 JWT 鉴权；候选、任务、结果和历史按操作用户隔离 |
| 选品页面 | `frontend/src/views/SourcingView.vue` | 市场/品类/价格筛选、授权查询、备用导入、卡片/表格、批量分析、进度与错误 |
| 审核页面 | `frontend/src/views/SourcingReviewView.vue` | 待审核、已通过、已拒绝、已收藏、审核历史 |
| 结果展示 | `frontend/src/components/SourcingEvaluation.vue` | 视觉分、资料完整度规则分、市场数据缺失、理由、风险及调用证据分别显示 |

页面地址：`http://127.0.0.1:3000/sourcing` 和 `http://127.0.0.1:3000/sourcing/review`。

候选池关键词搜索查询本地 PostgreSQL。妙手按钮单独查询授权账户已有公共采集箱，不表示 1688 全站实时搜索。价格筛选、价格升序必须按所选币种执行，不混排不同币种价格。

## 3. 数据库基础修复与迁移证明

1. `app.core.database.Base` 现在引用 `app.models.base.Base`，不再维护第二套空 metadata。
2. 原始 `f950df57a1e2` 初始化迁移保持不变。孤立的重复迁移 `002` 改为以它为前驱的结构验证标记，五张重复表不再重建；该标记降级不删除表。
3. 首轮新增 `f0cc7d685e7c`（四张选品表）和 `0b8f25ba38cb`（妙手溯源字段），当时仅一个 head：`0b8f25ba38cb`。后续追加妙手集成迁移 `554b31562dd4`，仍保持单 head。
4. 测试使用显式 `TEST_DATABASE_URL`。拒绝非 PostgreSQL、非 `*_test` 名称、与业务 URL 相同的配置。测试仅清空独立测试库的测试数据，不删除 schema，也不以 ORM create_all 掩盖迁移问题。

独立验证先于业务库变更：

| 数据库 | 验证 | 结果 |
|---|---|---|
| `tiktok_sourcing_test` | 空库 `alembic upgrade head`、集成测试、`alembic check` | 成功；无 metadata 差异 |
| `tiktok_sourcing_baseline_test` | 创建旧 23 表 ORM 基线；写入哨兵用户；完整结构核对；接管 002；升级 head | 成功；哨兵数据保留；完整 metadata 一致 |
| `tiktok_ops_local` | 只读核对旧 23 表、列类型/可空性、索引、唯一约束、外键及主键；确认零差异后再次核验并接管升级 | 成功；旧用户 3、商品 29、订单 50，迁移前后保持一致 |

首轮将本机业务库迁移至 `0b8f25ba38cb`，后续已验证并追加到 `554b31562dd4`。没有删除业务数据。首轮结构核对报告留在 `.runtime/sourcing-baseline-audit.json`；迁移前数量留在 `.runtime/sourcing-business-counts-before.json`。

其他部署库必须单独验证，不能因为本机通过就直接 stamp：

- 空库：在隔离测试环境验证后使用 `alembic upgrade head`。
- 旧 ORM 建表且无版本的库：先运行 `python -m scripts.adopt_sourcing_baseline`，默认只读。只有报告 matches=true 且独立副本验证完成，才使用 `--adopt` 接管到 002，再 upgrade head。
- 已记录其他版本、只有旧 002、缺表、类型或约束不同的库：脚本拒绝接管；需要针对该部署的审计，不自动修补或删除数据。

`scripts/check_sourcing_schema.py` 和本地启动脚本只检查版本，不自动迁移或 stamp。

## 4. 新表及关键约束

| 表 | 主要内容 | 约束 |
|---|---|---|
| `sourcing_candidates` | owner、平台/商品 ID、名称/描述、原链接、主图/其他图片、采购价/币种、SKU、品类、供应商、站点、来源说明、可信状态、资料完整性、输入版本、审核状态、收藏 | `owner_id + identity_key + target_market` 唯一；采购价非负 |
| `sourcing_analysis_tasks` | 独立 task UUID、batch UUID、候选/版本/快照、模型配置签名、状态/阶段/次数、租约、下一次执行时间、完成时间、脱敏错误、视觉 checkpoint、parent_task_id | queued/running/succeeded 的候选+版本+配置签名唯一；失败记录保留 |
| `sourcing_ai_evaluations` | task、candidate、input_version、stale、视觉评分及依据、文本建议、资料完整度规则评分、输入/图片哈希/调用证据 | task 唯一；视觉评分 0–100 |
| `sourcing_reviews` | candidate、evaluation、input_version、reviewer、approve/reject/favorite/unfavorite、备注、时间 | 必须关联评估和操作用户；API 不提供覆盖/删除历史 |

来源字段额外预留：`miaoshou_detail_id`、`original_source_id`、`original_url`、`source_record`。妙手记录标记 `miaoshou_api / authorized_account`，仅表示资料来自授权账户，不代表供应商认证、商品质量或平台核验。修改资料后标记 `user_modified`。

仅链接的记录是 `needs_details`，价格未知保持 null，不能填零伪装完整。名称、主图和采购价齐全才是 `ready`。SKU 的原始规格键保留，不猜测平台映射；供应商信息未提供时保持未知。

修改核心资料递增版本，旧评估标记 stale，审核状态回到 pending，旧审核历史保留。排队旧任务直接失败，运行中的任务在写入评估前再次核对版本。过期评估不能通过、拒绝或收藏。

## 5. 接口

以下路径均以 `/api/v1/sourcing` 为前缀，均使用现有 JWT 用户依赖。

| 方法 | 相对路径 | 说明 |
|---|---|---|
| GET | `/providers/status` | provider/model 配置状态、来源能力、fetch_item 待接入信息；不返回密钥 |
| POST | `/candidates` | 手动导入；201；重复返回已有候选 ID |
| POST | `/candidates/import` | `{format: json/csv, content, target_market}`；最大 2 MB、500 条；逐行导入/重复/错误 |
| GET | `/candidates` | keyword、target_market、category、currency、min_price、max_price、review_status、favorite、completeness、sort、page、page_size |
| GET | `/candidates/{id}` | 当前商品及最近评估，含是否过期 |
| PATCH | `/candidates/{id}` | 提交完整 CandidateInput 更新资料；核心变化使旧评估过期 |
| POST | `/analyses` | `{candidate_ids: [...]}`；一次 1–100 个候选；202；独立 task ID 和 batch ID；复用已有有效任务 |
| GET | `/tasks` | 按用户分页；支持 batch_id；活动任务优先，刷新恢复进度 |
| GET | `/tasks/{id}` | 阶段、尝试次数、错误、成功评估、未完成任务的真实视觉部分结果 |
| POST | `/tasks/{id}/retry` | 仅失败任务；创建新 task ID 并关联旧任务；相同视觉输入复用 checkpoint |
| POST | `/candidates/{id}/review` | `{evaluation_id, input_version, action, note}`；行锁核对当前版本；重复同一决策幂等 |
| GET | `/reviews` | 按用户分页；可按 candidate_id 查询不可覆盖的审核历史 |
| GET | `/sources/miaoshou/products` | 查询授权公共采集箱列表；page/page_size；不是关键词搜索 |
| POST | `/sources/miaoshou/import` | `{product_ids, target_market, currency}`；最多 20 个采集箱详情；逐项结果与错误 |

SourceAdapter 使用的真实妙手只读接口：

```text
POST /open/v1/product/common_collect_box/common_collect_box/get_common_collect_box_list
POST /open/v1/product/common_collect_box/common_collect_box/get_common_collect_box_detail
```

列表参数 `pageNo/pageSize`、详情参数 `commonCollectBoxDetailId` 和 HMAC 请求签名均按已读取的官方文档实现。请求签名覆盖实际发送的 JSON 字节，不猜测请求字段。该详情协议没有明确价格币种，因此页面要求操作人确认币种；供应商、认证等缺失值不推断。

官方依据：[快速接入与签名](https://qrzmpphmpd.apifox.cn/)、[公共采集箱列表](https://qrzmpphmpd.apifox.cn/492780421e0)、[公共采集箱详情](https://qrzmpphmpd.apifox.cn/492780423e0)。列表与详情已真实请求验证。

## 6. 模型、证据和任务策略

百炼通过兼容 Chat Completions 接口发送真实图片 base64 与候选资料；最多分析前 3 张不同图片。DeepSeek 只接收实际候选资料与已完成的视觉结果。当前实际验收模型是 `qwen3-vl-plus` 与 `deepseek-flash`，具体名称以服务端配置为准。

输出采用 extra=forbid、严格类型、长度限制、评分范围及有限枚举。拒绝非法 JSON、字符串评分、越界评分、额外销量字段、截断响应和非目标站点建议。提示词禁止真实销量/热度/利润率/供应商资质造假，并对未经支持的数值商业断言做额外拦截。文本建议和风险仍需人工复核，不能当作已证实的市场调查。

视觉评分来自百炼；规则评分仅为五项资料完整度，每项 20 分（名称、主图、采购价、品类、供应商名称）。供应商名称存在也不代表资质有效。市场数据始终明确为未接入/null，不混合成“综合商业潜力评分”。

只有真实响应校验成功才生成评估。DeepSeek 未配置时，视觉评估可完成但 text_status=not_configured；已经配置而调用失败时，整项任务失败，保留真实视觉阶段结果，不能以模拟文本完成。模型鉴权失败是任务业务错误，不会触发前端登录 401 处理。

图片下载限制 HTTP/HTTPS、公开目标地址、无 URL 认证、标准端口、逐次重定向校验、类型与魔数、5 MiB、时间上限。直接连接使用验证后的 IP，并保留原主机的 TLS 校验。当前机器的 Fake-IP 代理将阿里 CDN 解析为保留地址；只允许固定 `cbu01/02/03.alicdn.com` 经已配置 HTTPS_PROXY 下载，禁止该路径跟随重定向，其他任意域名仍拒绝私网地址。没有放开通用内网抓取。

任务执行：

- PostgreSQL 表为队列和事实来源；API 立即返回 202，不依赖浏览器长请求或内存队列。
- 独立进程 `python -m app.services.sourcing_worker` 领取任务，`FOR UPDATE SKIP LOCKED` 防重复领取。
- PostgreSQL advisory lock 并发槽限制同库多个 Worker 的总并发；同库 Worker 必须使用相同并发配置。
- 默认并发 2；租约 90 秒，每 20 秒续租；写入必须持有匹配的 lease_token。
- 默认单次模型超时 90 秒；任务整体上限为 `2 × model_timeout + 75` 秒。
- 明确的 429/502/503/504 错误有限指数退避，最多 3 次尝试。鉴权、输出校验、超时和不确定连接失败不会无条件自动重复付费请求。
- 租约过期标记为 failed/worker_interrupted，需要人工重试。任务可能已在上游计费，不能承诺外部模型 exactly-once。
- 同候选+版本+配置签名复用 queued/running/succeeded；失败重试新建 UUID，保留旧错误。已保存且视觉配置相同的 checkpoint 复用，DeepSeek 失败不会重复视觉调用。
- DeepSeek 使用官方 `thinking.type=disabled`，减少短结构化任务因思考 token 截断的风险。仍验证 finish_reason=stop。

官方模型协议依据：[百炼图像理解](https://www.alibabacloud.com/help/en/model-studio/vision)、[DeepSeek JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)、[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。

## 7. 配置与启动

服务端配置模板：`backend/.env.sourcing.example`。本机已建立 `backend/.env`，该文件被 Git 忽略，不纳入交付或前端打包。密钥不经过前端。

| 环境变量 | 用途 / 默认 |
|---|---|
| DATABASE_URL | 业务 PostgreSQL asyncpg URL；本地脚本使用端口 5433 的 tiktok_ops_local |
| TEST_DATABASE_URL | 必须显式指定独立 PostgreSQL `*_test` 数据库 |
| BAILIAN_API_KEY | 百炼服务端凭证；也支持 DASHSCOPE_API_KEY |
| BAILIAN_BASE_URL | `https://dashscope.aliyuncs.com/compatible-mode/v1`；必须与 key 区域/工作空间匹配 |
| BAILIAN_VISION_MODEL | 可配置 Qwen-VL 模型；实际验收使用 qwen3-vl-plus |
| DEEPSEEK_API_KEY | 可选文本服务端凭证；配置后调用失败不会视为完成 |
| DEEPSEEK_BASE_URL | `https://api.deepseek.com/v1` |
| DEEPSEEK_MODEL | 模型名称；实际验收使用 deepseek-flash |
| SOURCING_MODEL_TIMEOUT | 默认 90 秒，范围 5–180 |
| SOURCING_WORKER_CONCURRENCY | 默认 2，范围 1–10；同库 Worker 保持一致 |
| SOURCING_MAX_ATTEMPTS | 默认 3，范围 1–5 |
| MIAOSHOU_APP_KEY / MIAOSHOU_APP_SECRET | 妙手应用凭证；权限、额度、白名单仍按实际响应核验 |
| HTTPS_PROXY | 可选；既有服务端代理，固定阿里图片 CDN 的 Fake-IP 兼容路径使用 |

修改凭证、模型或 Worker 参数后须重启 API/Worker。前端配置状态只表示密钥存在，具体权限与区域以真实调用为准。

本机 PostgreSQL、Vite 已运行，API 和独立 Worker 已启动。后续启动：

```powershell
# 项目根目录；start-local 提供 PostgreSQL、现有后端与 Vite
powershell -File scripts/start-local.ps1
# 校验迁移版本后，加载最新后端及独立选品 Worker；不执行迁移
powershell -File scripts/start-sourcing-local.ps1
```

一般部署在 backend 目录分别运行：

```text
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m app.services.sourcing_worker
```

本地日志：`.runtime/logs/backend.*.log`、`.runtime/logs/sourcing-worker.*.log`。启动脚本只重启已登记且命令行匹配本项目的进程，拒绝停止其他 PID。

## 8. 测试和真实验收

自动测试 fixture 明确标注 TEST_ONLY，仅用于独立测试库，不作为真实模型验收。

| 检查 | 结果 |
|---|---|
| backend `pytest tests -q` | **28 passed**；登录、商品、订单、导入/去重/筛选、鉴权隔离、批量任务、重试/并发领取/租约、过期审核、严格 schema、私网图片、代理边界、妙手签名 |
| agent `pytest tests -q` | **5 passed**；原有空商品工作流基线，未调用发布/采购接口 |
| `alembic heads` | 单 head `0b8f25ba38cb` |
| 独立测试库 `alembic check` | No new upgrade operations detected |
| backend `compileall` | 通过 |
| frontend `npm run build` | vue-tsc + Vite production build 通过 |
| 运行中 API 只读回归 | login、me、products、orders、candidates、tasks、reviews、provider status 均成功 |
| 浏览器真实导入 | 优先妙手入口查询并导入真实商品，按 MY/TH 两个站点形成 2 个独立候选 |
| 百炼真实图片分析 | 成功；图片哈希、模型、调用 ID、usage 保存到 PostgreSQL |
| DeepSeek 真实文本分析 | 成功；严格结构校验，绑定视觉结果及站点 |
| 多候选任务 | 初次提交 2 个 UUID；页面显示排队、阶段、成功/失败；刷新仍可读取 |
| 真实失败与重试 | TH 文本首次截断失败，页面显示 output_incomplete；人工重试新建任务，复用原视觉请求 ID，文本成功 |
| 人工审核及持久化 | 浏览器保存 MY 收藏/通过、TH 拒绝；刷新后历史仍存在；记录绑定管理员及评估 ID/版本 |
| 数据保留 | 原 3 用户、29 商品、50 订单保持一致；新增 2 候选、3 任务、2 评估、3 审核历史 |

真实商品：1688 `900352236779`，来源为妙手公共采集箱 `4058549593`。实际资料含名称、8 张图片、4 个 SKU、采购价和品类，供应商名称未提供。币种由导入操作确认 CNY。另一个列表记录的详情未正常返回，未作为完整商品导入。

真实持久化调用证据：

| 站点 | 成功任务 ID | 百炼请求 ID | DeepSeek 请求 ID |
|---|---|---|---|
| MY | `18c9735b-ef0b-4a4f-a805-d24151fb0cb7` | `chatcmpl-65bf2ffe-fea0-9506-9be2-cc38b14ad516` | `96965f16-06ed-4075-9c76-b9a06ee6c903` |
| TH | `94fdb0e7-9e28-4ba2-bd8f-a585da206a96` | `chatcmpl-46aedc96-f0de-9b43-bbcc-6911c37c70e8` | `1f4b9cfd-ea24-4e81-bad8-8ba0770a040d` |

TH 原失败任务 `58ed4f9f-79d4-41e1-a2f5-dc463ee2c2cd` 与成功重试任务的视觉请求 ID 相同，证明重试没有重新执行视觉调用。模型调试阶段另有一次百炼成功请求 `chatcmpl-6173a455-2fe3-97b0-83bb-54e3f2bcd58f`；其文本站点校验失败，未伪装成成功评估。

完整脱敏证据及用量：[ai-sourcing-real-acceptance.json](evidence/ai-sourcing-real-acceptance.json)。

浏览器验收截图：[候选池](evidence/ai-sourcing-candidates-acceptance.png)、[刷新后的审核历史](evidence/ai-sourcing-review-acceptance.png)。审核备注明确写为功能验收，不能把该通过记录理解为运营上架批准。

测试复现（backend 目录）：

```powershell
# 将 URL 指向专用 *_test 库，不得使用业务数据库名称。
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://tiktok_ops:tiktok_ops_dev@127.0.0.1:5433/tiktok_sourcing_test'
../.venv/Scripts/python.exe -m scripts.prepare_test_database
$sourcingBusinessUrl = $env:DATABASE_URL
try {
    $env:DATABASE_URL = $env:TEST_DATABASE_URL
    ../.venv/Scripts/python.exe -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw '测试库迁移失败，停止测试' }
} finally { $env:DATABASE_URL = $sourcingBusinessUrl }
$env:DEBUG = 'true' # 既有 /docs 测试需要开启测试环境文档
../.venv/Scripts/python.exe -m pytest tests -q
```

依赖清单为 `backend/requirements-test.txt`。已有测试的两个基线预期已按真实旧 API 契约修正：商品创建返回 200；HTTPBearer 缺少凭证返回 403。没有为满足测试而更改旧登录/商品 API 行为。

## 9. 已知限制与后续边界

- `fetch_item` 尚未接入，等待完整 OpenAPI 请求/响应定义。当前只读取已有授权采集箱，不发起采集、认领或发布。
- 授权平台关键词实时搜索未提供；页面清楚区分本地搜索与妙手采集箱查询。1688 直连明确不可用，无模拟抓取。
- 当前真实批量验收是同一实际商品按两个目标站点形成的两个候选，不声称已验证不同货源商品的效果或规模化吞吐；自动测试另覆盖不同来源 ID。
- 无真实市场销量、热度或利润指标。模型的地域适配、材质判断、合规提醒是建议/推断，业务人员仍须核实，不构成市场事实或供应商认证。
- 首期按导入人隔离候选/任务/审核；尚未提供组织级共享审核队列。
- Worker 中断或模型超时无法判断上游是否计费，需人工重试。失败文本阶段的 token usage 尚未单独持久化；成功视觉和成功文本保留调用用量，重试复用视觉证据。
- 多个 Worker 必须保持一致并发参数。本地脚本负责启动，正式部署仍需进程守护与集中监控。
- 前端有既有的大 chunk 警告；Python 有既有 Pydantic/jose 弃用警告，均未阻止构建/测试。未在本阶段全面重构旧业务。

第一阶段交付到此停止。第二阶段发布能力需新的明确指令后才开发。
