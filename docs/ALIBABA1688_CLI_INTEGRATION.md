# 1688 CLI 货源集成说明

日期：2026-10-13
范围：接入开源 [superjack2050/1688-cli](https://github.com/superjack2050/1688-cli)（Node.js + Playwright + 系统 Chrome），使用用户本人的 1688 登录会话**只读**获取真实商品和供应商信息。第一阶段不启用采购、付款、联系卖家和上架。

## 1. 架构

```
Vue 管理后台「1688 货源中心」 ─┐
LangGraph Agent 工具（agent/）─┼─► FastAPI /api/v1/sourcing/1688/*  ──►  Alibaba1688Provider（唯一入口）
自动发现 Discovery 搜索阶段 ───┘                                          │  缓存 / 串行化 / 调用间隔 / 标准化
                                                                         ▼
                                    local：node dist/cli.js（同一系统用户，同一 %USERPROFILE%\.1688 会话）
                                    remote：宿主机 CLI Adapter（令牌鉴权）→ 本机 CLI
                                                                         ▼
                                    候选库 sourcing_candidates + 供应商表 sourcing_suppliers（PostgreSQL）
```

| 模块 | 文件 |
|---|---|
| 配置 | `backend/app/services/alibaba1688/config.py`（`ALIBABA1688_*` 环境变量） |
| 命令白名单与参数校验 | `backend/app/services/alibaba1688/commands.py` |
| CLI 执行（子进程 / 远程 Adapter） | `backend/app/services/alibaba1688/runner.py` |
| 退出码与状态 | `backend/app/services/alibaba1688/errors.py` |
| 数据标准化 | `backend/app/services/alibaba1688/normalize.py` |
| Provider 门面 | `backend/app/services/alibaba1688/provider.py` |
| 候选入库与去重 | `backend/app/services/alibaba1688/candidates.py` |
| 宿主机 Adapter | `backend/app/services/alibaba1688/adapter_server.py` |
| API 路由 | `backend/app/api/v1/alibaba1688.py`；候选运营接口在 `backend/app/api/v1/sourcing.py` |
| 前端页面 | `frontend/src/views/Alibaba1688View.vue`，接口 `frontend/src/api/alibaba1688.ts` |
| Agent 工具 | `agent/app/tools/alibaba_tools.py` |

## 2. 安装与登录

要求 Node.js 20+（本机 v24.21.0），推荐安装 Google Chrome（CLI 默认使用系统 Chrome；没有 Chrome 时 postinstall 会下载 Playwright Chromium）。

```powershell
npm install -g 1688-cli          # 本机已安装 0.1.47
1688 --version
1688 doctor --no-launch --json   # 环境检查
1688 whoami --json               # 是否登录
1688 daemon status --json
```

**登录必须由用户本人完成**：在运行后端的同一台电脑、同一 Windows 用户下执行 `1688 login`（或 `1688 login --headed` 打开浏览器窗口），用 1688 App 扫码。系统不会自动登录、退出账号，也不会读取或导出 Cookie。

- 会话保存在 `%USERPROFILE%\.1688\profiles\default\`（可用 `ALIBABA1688_CLI_HOME` 映射为 `BB1688_HOME`）。
- 遇到滑块验证（状态 `risk_control`）：在终端手动执行一次同样的命令加 `--headed`，由本人完成验证，例如 `1688 search "露营灯" --headed`。系统不破解验证码、不绕过风控。
- 连续失败后 CLI 守护进程会自我暂停一段时间；处理登录/验证后可执行 `1688 daemon reload`。
- 只读检查脚本：`cd backend; ..\.venv\Scripts\python.exe -m scripts.check_1688_cli`。

### 运行环境（Windows / WSL2 / Docker）

- **Windows 原生开发（当前本机）**：后端（`.venv` + uvicorn）与 CLI 在同一 Windows 用户下运行，`transport=local`，直接以 `node <npm 全局目录>\node_modules\1688-cli\dist\cli.js` 调用（不经过 `1688.cmd`，避免 cmd.exe 二次解析参数）。
- **WSL2 / Docker**：Windows 的 Chrome 会话不能被 WSL2 或容器直接复用。后端在容器内时，在**宿主机**（已登录的用户）运行 Adapter：
  ```powershell
  cd backend
  $env:ALIBABA1688_ADAPTER_TOKEN = '<至少 24 字符的随机令牌>'
  ..\.venv\Scripts\python.exe -m app.services.alibaba1688.adapter_server   # 默认只监听 127.0.0.1:8765
  ```
  容器内后端设置 `ALIBABA1688_TRANSPORT=remote`、`ALIBABA1688_ADAPTER_URL`、`ALIBABA1688_ADAPTER_TOKEN`。Adapter 只接受白名单只读命令，不接受宿主机文件路径，浏览器 Profile 和 Cookie 不离开宿主机。若容器需要访问，可把 `ALIBABA1688_ADAPTER_BIND` 设为 Docker 网关地址，不要绑定公网网卡。部署方案另行设计。

## 3. 后端 API（均需本系统 JWT）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/sourcing/1688/status?refresh=` | CLI 安装、版本、浏览器、登录、守护进程、最近一次查询结果 |
| GET | `/api/v1/sourcing/1688/search` | `keyword`（≤50 字）、`max`（≤20）、`sort`（relevance/best-selling/price-asc/price-desc）、`price_min`、`price_max`、`exclude_ads`、`factory_only` |
| POST | `/api/v1/sourcing/1688/image-search` | multipart：`image`（JPG/PNG/WebP，按文件头校验，≤5 MB）、`max` |
| GET | `/api/v1/sourcing/1688/products/{offer_id}` | 详情：图片、属性、SKU、阶梯价、起批量、包装、供应商、发货地；含 `raw` 原始数据 |
| GET | `/api/v1/sourcing/1688/suppliers/search` | 企业搜索：`keyword`、`max`、`factory_only`、`province` |
| GET | `/api/v1/sourcing/1688/suppliers/{supplier_id}` | 供应商画像；`supplier_id` 为商品 offerId 或 `b2b-` 开头的 memberId |
| POST | `/api/v1/sourcing/1688/candidates` | `{offer_id, target_market, use_detail}` 加入候选库 |
| GET | `/api/v1/sourcing/candidates` | 已有接口，新增筛选 `data_source=1688_cli`、`sourcing_status` |
| PATCH | `/api/v1/sourcing/candidates/{id}/operations` | 收藏、备注、`sourcing_status`（saved/to_analyze/to_review）；不改变商品资料版本 |

错误统一返回 `{"detail": {state, code, message, label, hint, retryable, exit_code}}`：

| state | HTTP | 含义 |
|---|---|---|
| `cli_not_installed` | 503 | 未检测到 CLI |
| `browser_error` | 503 | 浏览器缺失或启动失败（退出码 6） |
| `not_logged_in` / `login_expired` | 424 | 未登录 / 登录过期（退出码 3、8），提示手动 `1688 login` |
| `risk_control` | 424 | 风控/滑块（退出码 4），提示 `--headed` 手动验证 |
| `busy` | 429 | 已有查询在执行（同一 Profile 串行） |
| `timeout` | 504 | 查询超时（子进程被终止，不自动重试） |
| `network_error` | 502 | 网络错误 |
| `bad_input` / `not_found` | 422 / 404 | 参数或 ID 无效 |
| `contract_changed` | 502 | CLI 输出不是 JSON 或缺少关键字段（版本变化） |

执行约束：参数列表调用、无 `shell=True`；关键词放在 `--` 之后并拒绝以 `-` 开头；只允许 `search / offer / image-search / supplier search / supplier inspect / doctor / whoami / daemon status / --version`；默认单并发、调用间隔 1.5 秒、排队最长 20 秒；搜索结果缓存 10 分钟，详情缓存 30 分钟；子进程不继承后端的密钥类环境变量；日志只记录命令名、退出码、错误码和耗时，不记录 stdout/stderr 原文和 CLI 返回的 URL（登录跳转 URL 含令牌）。

## 4. 数据库变更（Alembic `a1688c11e001`，只新增）

- `sourcing_candidates` 新增：`source_price_min`、`source_price_max`、`min_order_quantity`、`fetched_at`、`supplier_ref_id`（外键 → `sourcing_suppliers`）、`sourcing_status`（默认 `saved`）、`operator_note`（默认空）。
- 新表 `sourcing_suppliers`：按 `owner_id + source_platform + supplier_key` 唯一；`platform_metrics` 只存平台提供的指标。
- 入库规则：商品数据只取自 CLI（详情，或详情失败时近期搜索结果），不接受前端提交的商品字段；按 `1688 + Offer ID` 去重（同一用户跨站点一条）；重复保存只刷新平台字段（价格区间、起批量、采集时间、原始数据、供应商关联），不改名称、采购价、SKU、备注、状态、收藏，不改变 `version`（已有 AI 评估不失效）；搜索列表数据不会覆盖已保存的详情数据；其他来源（妙手/人工）的同一商品只补供应商关联。
- 价格超过两位小数时不取整：`purchase_price` / SKU 价置空，原值保留在 `source_price_*` 和 `raw_data`。

本地业务库迁移：`powershell -ExecutionPolicy Bypass -File scripts/migrate-1688-local.ps1`（先核对版本，迁移后核对业务表行数不变）。2026-10-13 已执行：`554b31562dd4 → 7c3e9a1d2f40 → a1688c11e001`，users 3 / products 29 / orders 50 / sourcing_candidates 3 等行数不变。

## 5. 前端

菜单「1688 货源中心」，路由 `/sourcing/1688`：

- 状态栏：登录、浏览器、CLI 版本、最近一次查询；未登录/过期/风控时给出手动处理指引。
- 货源搜索：关键词、以图搜图、价格区间、排序、只看工厂、过滤广告、条数；商品卡片（图片、标题、人民币采购价、起批量、1688 成交、供应商、地区）；加载、空状态、失败重试。
- 商品详情抽屉：图片轮播、价格、阶梯价、SKU、属性、包装、发货地、供应商、来源链接、加入候选库。
- 供应商：企业搜索列表与画像抽屉；“平台指标”与“CLI 参考分（非平台）”分开展示，平台未提供时明确提示，不展示推算或伪造的评价。
- 我的候选商品：收藏、备注、待分析/待审核状态、查看来源和详情；AI 分析与审核沿用「选品审核」。

## 6. Agent 工具

`agent/app/tools/alibaba_tools.py` 中的 `search_1688_products`、`get_1688_product_detail`、`search_1688_suppliers`、`search_1688_by_image`、`save_sourcing_candidate` 全部调用后端 API（统一 Provider），可通过 `get_langchain_tools()` 注册为 LangChain 工具；原有随机 mock 数据已移除。

- 需要在 `agent/.env` 配置 `BACKEND_API_TOKEN`（本系统 JWT）。
- 选品节点在只给出 `product_data.keyword` 时会先搜索 1688；1688 订单数放在 `source_1688_order_count`，不作为 TikTok 月销量。
- `create_1688_purchase_order` 改为拒绝执行：Agent 不得采购、付款、联系卖家或发布商品。
- 基础搜索与候选库不依赖大模型密钥。

## 7. 测试

- 单元测试 `backend/unit_tests/test_alibaba1688_units.py`：白名单、参数注入、错误分类、令牌不外泄、标准化、契约变化、缓存、图片校验与临时文件清理、状态检测；用 `fixtures/fake_1688_cli.js` 驱动真实子进程验证 stdout/stderr/退出码/超时/并发；远程 Adapter 鉴权与白名单。
- 集成测试 `backend/tests/test_alibaba1688.py`（隔离 PostgreSQL）：搜索 → 详情 → 入库 → 刷新可见、去重与人工字段保护、详情失败回退、无 CLI 数据拒绝入库、错误映射、上传校验、按用户隔离。
- Agent 测试 `agent/tests/test_sourcing_1688_tools.py`。
- 所有夹具均为 `TEST_ONLY` 脱敏数据，不使用真实账号。

## 8. 真实联调记录（2026-10-13，用户本人已登录 1688）

环境：Windows 11，1688-cli 0.1.47，系统 Chrome；验证用后端 127.0.0.1:8001、前端 127.0.0.1:3011（连接本地业务库 `tiktok_ops_local`）。

| 步骤 | 结果 |
|---|---|
| 1. 打开后台「1688 货源中心」 | 通过：状态显示“登录有效”、CLI 0.1.47、浏览器正常 |
| 2–4. 搜索“露营灯”，调用真实 CLI，显示真实商品 | 通过：20 条（筛选前 60），含图片、人民币价格、1688 成交数、供应商、地区、工厂/广告标识 |
| 5. 点击商品查看 SKU | 通过：offer 1054735896634，价格 ¥13.5–14.5、起批量 1 个、混批 5、6 个 SKU（价格/库存/已售）、阶梯价、41 项属性、包装尺寸 |
| 6. 打开供应商详情 | 通过：公司名、所在地、经营 8 年、工厂、成立时间、员工规模、在售 160 件、店铺链接；平台未返回复购/服务分，页面明确提示“平台未提供” |
| 7. 加入候选库 | 通过：201，入库 1 条（`data_source=1688_cli`、completeness=ready、6 个 SKU、供应商关联） |
| 8. 刷新页面后仍可查看 | 通过；再次保存返回 `duplicate`，备注/收藏/“待审核”状态和 version 不变 |
| 供应商搜索（露营灯，只看工厂） | 通过：真实企业列表，平台指标与 CLI 参考分分列展示 |
| 以图搜图 | 接口通过（JPG 上传、临时文件已清理、数量上限生效），但 **1688 返回结果与图片无关**（用原始主图 URL 直接调用 CLI 结果相同），已在结果中提示人工确认 |

联调中发现并修复：

- **隐私**：`offer` 原始数据 `freight.receiveAddress` 是当前登录买家账号的收货地址，已在标准化时从 `raw` 中移除，不返回前端、不入库（单测覆盖）。
- SKU 规格中的 HTML 实体（如 `&gt;`）在展示字段中反转义；`raw` 保留原值。
- 单件重量、包装尺寸为 0 时视为“未提供”，避免后续利润计算误用。
- 缓存命中时 `fetched_at` 沿用 CLI 实际获取时间。
- 以图搜图 API 的数量参数被图片字节上限变量覆盖，导致始终返回 20 条；已修复并加回归测试。

## 9. 已知限制

- 真实联调需要用户本人先执行 `1688 login`；未登录时搜索和详情会返回 `not_logged_in`。
- 1688 以图搜图当前返回的结果与图片无明显相关性（上游行为），仅供参考。
- 供应商“身份”字段为 1688 原始编码（如 `cht`），标签含 `ranking_list#hot` 等内部编码，暂按原值展示。
- 部分商品的阶梯价由 SKU 价格区间构成（同一起订量对应多个价格），按 CLI 原值展示。
- 本系统 JWT 有效期 30 分钟；页面停留较久后操作会要求重新登录本系统（与 1688 登录无关）。
- `search` 列表不含起批量和 SKU；需打开详情获取。CLI 搜索不分页，每次最多 20 条。
- `supplier inspect` 不支持仅凭 loginId 查询（上游已知会解析到错误供应商）。
- 进程内缓存与并发闸门只对单个后端进程有效；多进程部署需改用 Redis 等共享锁。
