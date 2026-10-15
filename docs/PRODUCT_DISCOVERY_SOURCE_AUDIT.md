# 商品发现数据源调查（PRODUCT_DISCOVERY_SOURCE_AUDIT）

调查日期：2026-10-13（Asia/Shanghai）
范围：为“输入选品目标 → 自动搜索真实 1688 货源”寻找**合法、可调用**的关键词搜索数据源。
原则：不伪造商品；不绕过验证码、反爬、登录或访问控制；第三方是否获得授权，以能核实的证据为准。

## 1. 结论

| # | 数据源 | 实际权限（本项目当前） | 关键词搜索 | 返回真实商品链接 | 结论 |
|---|---|---|---|---|---|
| 1 | 妙手 ERP OpenAPI | 已授权，四个接口已真实联调 | **无** | 只能采集**已知链接**、读取自己的公共采集箱 | 作为**采集器**复用，不能当搜索源 |
| 2 | 1688 开放平台（跨境/分销方案） | **未授权、无凭证** | 方案内有（关键词搜索、图片搜索） | 需申请后在控制台核实 | 合规首选，但当前阻塞，Adapter 预留为“不可用” |
| 3 | 第三方“1688 搜索 API”（TMAPI、万邦、Daji、Apify 等） | 无 | 有 | 宣称有 | 未见 1688 官方授权证明，**不默认接入** |
| 4 | 自建 Scrapy / Playwright 抓取 1688 搜索页 | — | — | — | robots.txt 不允许、需登录和滑块验证，**排除** |
| 5 | Brave Search API | — | 有（支持 `site:` 运算符） | 取决于索引覆盖率 | **已移除**（2026-10-13，按用户要求删除代码与配置） |
| 6 | **1688 CLI**（开源 `1688-cli`，用户本人登录会话） | 用户本人扫码登录后可用 | 有（关键词、以图搜图、供应商搜索） | 是（1688 搜索页真实商品） | **当前采用**：只读调用，经统一 `Alibaba1688Provider`，详见 `docs/ALIBABA1688_CLI_INTEGRATION.md` |

结论（2026-10-13 更新）：Brave Search 路径已移除。自动发现的关键词搜索改为 **1688 CLI（用户本人登录会话、只读）→ 提取 offer ID → 妙手 `fetch_item` 采集真实详情**。CLI 未安装、未登录或触发风控时，搜索阶段按对应错误明确失败，不用示例数据代替。

## 2. 妙手 ERP OpenAPI

依据：项目根目录《妙手开放平台-API接口文档 (1).md》（188 个接口：商品 138 / 包裹 13 / 采购 17 / 仓储 18 / 货源账号 2），以及 `docs/MIAOSHOU_INTEGRATION_REPORT.md` 的真实联调记录。

- 逐条检查接口清单：没有任何“按关键词搜索 1688/货源”的接口。带 “search” 的接口均为本账号内部数据检索，例如 Shopee 全球产品搜索（#104，需 shopId）、采集箱列表、采购单、供应商、商品 SKU 等。
- 与货源发现相关的只有：
  - `#2 fetch_item`：按**已知**链接采集，单次最多 50 个；
  - `#4 get_common_collect_box_list`：列出**自己**公共采集箱的记录，只能按 `sourceItemIdKeyword`（货源 ID）过滤，不支持标题关键词，每页最多 500 条；
  - `#6 get_common_collect_box_detail`：读取详情。
- 妙手 ERP 网页端宣传接入了“1688 跨境寻源通”，但这是 ERP 界面功能，OpenAPI 没有开放。
- 请求限制：账户、应用、接口三级 QPS/QPM/QPD 限流（错误码 `*RateLimit`）。具体额度文档未公布，由平台按账户设定。
- 本阶段用法：作为**发现结果的采集器**，复用已验证的单次提交、超时只查询、公共箱已有记录优先同步等机制。

## 3. 1688 开放平台（官方）

- 1688 开放平台（open.1688.com）面向跨境/代采 ISV 提供解决方案，例如“跨境综合解决方案”和“跨境寻源通”，命名空间为 `com.alibaba.fenxiao.crossborder`。搜索引擎收录了该命名空间下的 `product.search.queryProductDetail` 文档页。多篇二手资料称方案内包含多语言关键词搜索（`product.search.keywordQuery`）和以图搜货。
- open.1688.com 的接口文档页 **robots 禁止自动抓取**，本次没有读取。字段、分页、价格字段、计费和 QPS **都未经官方文档核实**，只能等账号开通后在控制台查看。
- 权限：需要企业认证的 1688 账号创建应用，再申请对应的解决方案或接口权限，经审核开通。项目 `.env` 目前没有任何 1688 凭证。
- 处理：建立 `Alibaba1688OfficialSearchAdapter`，状态固定返回“未授权、未配置，不调用”。**不按猜测的协议实现请求代码**。拿到凭证和控制台文档后，再新增 Provider 并真实联调。

## 4. 第三方 1688 搜索 API

| 服务 | 观察 | 判断 |
|---|---|---|
| TMAPI（tmapi.top） | 文档列出关键词、价格区间、类目、排序等参数，用 API Key 鉴权；页面没有说明数据来源，也没有 1688 授权说明 | 授权不明 |
| Daji Open Platform | 提供关键词搜索、图搜，返回 offerId、价格、图片、月销量；页面称“适配能力”，未声明官方授权 | 授权不明 |
| 万邦（Onebound）等 | 以“代申请/代调用”形式提供 1688 接口 | 授权链条不明 |
| Apify 1688 Search Scraper | 明确是爬虫 | 属于网页抓取，排除 |

除非服务商能出示 1688 的书面授权，否则不接入。如果用户另有已签约、已授权的服务商，可以按同一个 `DiscoveryProvider` 接口新增 Adapter。

## 5. 自建网页采集（Scrapy / Playwright）

- `www.1688.com/robots.txt` 对所有爬虫禁止带查询参数的 URL，而 1688 搜索页（`s.1688.com/selloffer/offer_search.htm?keywords=…`）依赖查询参数。实际访问搜索页通常还要过登录和滑块验证。
- 仓库已有的 `scraper/` 模块：`ROBOTSTXT_OBEY = False`，配置了代理池和 UA 中间件，Mock 开关与 spider 参数不一致，数据库导入路径错误、失败时静默，结果直接写入 `products`（详见 `docs/AI_SOURCING_AUDIT.md` §7.2）。
- 结论：**不启用、不修复后启用**。修复技术问题也解决不了 robots 和登录、验证码的合规问题。

## 6. Brave Search API（已移除）

2026-10-13 按用户要求删除：`backend/app/services/discovery/brave.py`、`backend/scripts/probe_brave_1688.py`、`BRAVE_SEARCH_*` 配置项及对应单测。此前未配置密钥、未做真实探测，没有遗留数据。

## 7. 1688 CLI（当前采用）

- 来源：开源项目 [superjack2050/1688-cli](https://github.com/superjack2050/1688-cli)（Node.js + Playwright + 系统 Chrome），使用用户本人在本机扫码登录的 1688 会话，不需要开放平台 API Key。
- 只读：系统只调用 `search / offer / image-search / supplier search / supplier inspect / doctor / whoami / daemon status`；登录、退出、购物车、下单、联系卖家都不在白名单中。
- 自动发现中的用法：规划关键词 → `Alibaba1688CliSearchAdapter` → 提取 offer ID → 妙手采集。CLI 不分页，每个关键词只取第 1 页（最多 20 条）；排除词由标题过滤实现。
- 风控：遇到滑块时返回 `risk_control`，提示用户本人用 `--headed` 手动验证，系统不绕过。

## 8. 架构决定

- 搜索（Discovery）与采集（妙手）完全解耦：`DiscoveryProvider`（1688 CLI）→ `SourceSearchAdapter`（1688 关键词搜索）→ `DiscoveryResultNormalizer` → `DiscoveryDeduplicator` → 妙手采集任务 → 现有 AI 队列 → `DiscoveryScoringService`。
- 后续接入 1688 官方搜索或已授权的第三方，只需新增 Provider/Adapter，不改编排和采集逻辑。

## 来源

- [superjack2050/1688-cli](https://github.com/superjack2050/1688-cli)（README、AGENTS.md、docs/JSON_CONTRACTS.md、docs/SAFETY.md、docs/RELIABILITY.md）
