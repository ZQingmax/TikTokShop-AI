# 妙手 ERP 真实货源集成报告

实施与验收日期：2026-10-13，Asia/Shanghai。主项目：`tiktok-ecommerce-automation-system`。

## 1. 结果与实施边界

已贯通妙手真实鉴权、单条 1688 链接采集、公共采集箱读取与详情同步、PostgreSQL 候选池、百炼图片分析、DeepSeek 文本分析和审核持久化。没有使用模拟响应代替真实接口或模型验收。

实施前读取了 `docs/AI_SOURCING_AUDIT.md`、项目根目录的 `妙手开放平台-API接口文档 (1).md`、首轮实施报告和实际代码。原有 AI 分析、任务管理、审核闭环已经完成；缺口是来源请求嵌在适配器中、缺少持久化采集任务、详情没有完整保留原始字段及单位、SKU price 被当作采购价。本轮补齐这些缺口，复用现有 SourceAdapter、SourcingCandidate、AI Worker 和审核服务，没有重写已有业务模块。

只实现文档 #1、#2、#4、#6。未调用 TikTok 发布、认领、采购、改价、履约或订单同步接口，没有自建 1688 页面采集，没有读取或复制 `tk-autopilot` 源码。审核验收不创建 Product、ListingDraft 或 TikTok 商品 ID，旧 `Product.score` 的含义不变。

## 2. API 客户端与签名

代码：`backend/app/clients/miaoshou_client.py`。服务地址固定为 `https://openapi-erp.91miaoshou.com`，路径白名单仅允许以下四项，全部通过 POST JSON 调用。

| 文档接口 | 真实路径 | 本轮使用的请求字段 |
|---|---|---|
| #1 获取店铺数据列表 | `/open/v1/product/shop/shop/get_shop_list` | `platform`、`site`、`pageNo`、`pageSize`；每页最多 100 |
| #2 通过货源链接采集货源 | `/open/v1/product/common_collect_box/common_collect_box/fetch_item` | `collectLinks` 数组，最多 50；不增加猜测字段 |
| #4 获取公共采集箱列表 | `/open/v1/product/common_collect_box/common_collect_box/get_common_collect_box_list` | `pageNo`、`pageSize`；可选 `filter.tabPaneName`、`filter.sourceItemIdKeyword`；每页最多 500 |
| #6 获取公共采集箱详情 | `/open/v1/product/common_collect_box/common_collect_box/get_common_collect_box_detail` | 正整数 `commonCollectBoxDetailId` |

签名消息为 `AppSecret + Path + Timestamp + AppKey + Body + AppSecret`；以 AppSecret 为 HMAC-SHA256 密钥，输出小写 hex。Body 先序列化为紧凑 UTF-8 JSON 字节，再签名；httpx 用 `content=body` 发送同一份字节，不再用 `json=` 二次序列化。时间戳为 Unix 秒。只发送必要的 Content-Type 和签名字段，不附带浏览器 Cookie、debug 或 timerToken。

密钥使用服务端 SecretStr 配置。日志不打印密钥、完整请求头、请求体或上游 reason/message，只记录路径、错误码、类别及结果是否不确定。SQLAlchemy 隐藏绑定参数，避免 debug SQL 和数据库异常泄露原始货源资料。原始响应保留在数据库，前端投影递归遮蔽 token、secret、password、Authorization 等字段及原始响应文本。

默认请求超时 30 秒；禁止重定向及客户端自动重试。错误分类覆盖 configuration/input、auth、permission、rate_limit、upstream、HTTP、network、timeout、response 和其他 platform 错误。文档中的 HTTP 500 SimpleErrorResponse 同样解析真实错误码；未知 5xx、网络超时、无效响应或采集映射不完整均保守处理，不推定采集失败后再次提交。

默认每个事件循环内同应用请求间隔 1 秒；429/平台频率错误进入冷却。货源 Worker 用 PostgreSQL advisory lock 串行执行来源任务，AI Worker 保持独立并发槽。多 API 进程之间的账户级全局限流尚未引入；生产多实例需要统一网关或共享限流器，并按平台实际额度设置频率。

## 3. 数据映射与价格含义

代码：`backend/app/services/sourcing_sources.py` 和 `miaoshou_mapping.py`。所有来源通过 SourceAdapter；妙手是优先入口，手动链接及 CSV/JSON 保留为备用。候选池关键词查询与授权公共箱源商品 ID 查询在页面上明确分开，后者不是 1688 全站搜索。

| 妙手原始字段 | 保存位置 / 行为 |
|---|---|
| `sourceList[].sourceItemId` | `source_product_id`、`original_source_id`；原 sourceList 也保留 |
| `commonCollectBoxDetailId` | `miaoshou_detail_id`、source_record 中明确标为 common_collect_box_id；不是 TK 采集箱 ID |
| `sourceItemUrl` | `original_url` 保留平台原值；`product_url` 为候选去重后的标准链接 |
| `title`、`notesText`、`imgUrls`、`cateList` | 名称、描述、主图/图片、品类；完整原字段在 raw_data |
| `price` | `source_spu_price` 无固定小数位 Numeric，原值保留；可表达为本地两位金额时映射到候选采购价参考字段 |
| `skuMap` | 完整规格键、price、oriPrice、stock、oriStock、重量、尺寸等保留在 raw_data；归一化 SKU 的 purchase_price 保持 null |
| `stock` | `source_stock`；原库存整数也在 raw_data；不是销量、热度或已核实可售库存 |
| `weight` / SKU weight | 原值保留，单位 kg |
| 包装长、宽、高 | 原值保留，单位 cm；不根据规格名称里的 mm 再次换算接口尺寸 |
| `sourceSupplierInfo` | `source_supplier_info` 和 raw_data 原对象；缺失时不生成供应商或资质 |
| `sourceMataInfo` | `source_meta_info` 和 raw_data；保留接口字段原拼写 |
| 完整详情响应 / ossMd5 | raw_data.detail_response、raw_response_text、source_record；保留其他未知字段 |
| 同步状态 / 时间 | `sync_status=synced`、`synced_at`；失败原因及中间状态保留在来源任务 |

`price` 是文档定义的 SPU 货源价。`skuMap.price` 是公共采集箱的 SKU 价格字段，文档标为“售价”；`oriPrice` 是“原始售价”。系统不把这两者推定为 SKU 采购成本，也不当成未来 TikTok 售价。公共箱接口没有币种，本轮操作选择 CNY，不能宣称币种来自 API；正式运营仍须确认。

超出本地采购价精度或范围的价格不强行四舍五入为完整资料，raw_data 与 source_spu_price 仍保留；名称、主图或采购价缺失的记录保持 needs_details。仅链接不补模拟标题、图片、价格或评分。

去重键沿用 `owner_id + identity_key + target_market`。相同站点重复同步复用候选；不同站点可以保存不同选品决策。实际核心字段、SKU、库存、重量/尺寸、来源、供应商或源资料改变时递增版本，使旧评估 stale、审核回到 pending；旧评估及审核历史保留。仅拉取时间更新不使评估过期。

现有 AI 快照增加 source_details，包含 SPU/SKU 原值、价格语义、库存和重量单位；不把供应商联系资料发送给模型。视觉分、资料完整度规则分、市场指标仍分别展示。没有销量、热度或利润率指标时为“未接入”。

## 4. 持久化采集任务与恢复

代码：`miaoshou_tasks.py`、`miaoshou_sync_worker.py`。新增表 `sourcing_miaoshou_tasks` 保存独立 UUID、操作用户、request_key、请求指纹、kind、站点/币种、每项进度与映射 ID、提交标记、原始成功响应、租约、轮询次数及错误。

状态为 queued、running、waiting、succeeded、failed、uncertain；任务逐项保存，部分已成功的商品不会因其他商品失败而再次采集。request_key 幂等，相同 key 不允许用于不同请求。相同未完成采集集合复用已有任务；冲突站点、币种或分析选项返回 409。

外部写操作遵循：

1. 按 sourceItemId 查询公共箱；存在记录时直接同步，优先实际 success 记录，避免把 skip 重复记录当作新采集。
2. 对仍缺失的链接，在数据库提交 external_started_at 后，最多执行一次 fetch_item。
3. 成功返回映射后查询详情。若平台处理尚未完成，默认每 5 秒查询、最多 8 轮；每次网络请求仍有独立超时。
4. 超时、不确定响应或 Worker 中断时进入查询恢复。租约 90 秒，每 20 秒续租；过期租约恢复只读查询，不重发采集。
5. 页面“查询平台状态”和 reconcile API 仅查询；它们不是外部写操作重试。需要业务人员确认平台确实没有结果后，才应发起新的采集意图。

独立后台进程入口仍为 `python -m app.services.sourcing_worker`，同时调度原 AI Worker 和新的货源 Worker。无需 LangGraph、Redis、RabbitMQ 才能完成此闭环。

## 5. 本系统接口与页面

以下新接口均位于 `/api/v1/sourcing/miaoshou`，使用现有 JWT。采集、同步和 reconcile 限管理员/运营角色，候选、任务和审核数据按用户隔离。

| 方法 | 相对路径 | 用途 |
|---|---|---|
| GET | `/status` | 只检查服务端配置；connected=null，不冒充真实连接成功 |
| POST | `/connection-check` | 用真实店铺接口验证鉴权；返回站点、店铺数量或错误类别 |
| GET | `/shops` | 真实店铺分页读取 |
| GET | `/common-products/{id}` | 公共采集箱详情、原字段、单位及价格解释 |
| POST | `/collect` | 202；`request_key`、`links`、`target_market`、`currency`、`analyze_after_sync` |
| POST | `/sync` | 202；`request_key`、`common_detail_ids`、`target_market`、`currency`、`analyze_after_sync` |
| GET | `/tasks` | 用户任务分页；刷新后恢复进度 |
| GET | `/tasks/{id}` | 逐项源 ID、公共详情 ID、候选 ID、错误、AI task ID |
| POST | `/tasks/{id}/reconcile` | 失败/不确定任务重新查询平台；不再 fetch_item |

原有 `/api/v1/sourcing/sources/miaoshou/products` 和 `/import` 保持兼容；products 增加可选 source_id/tab 过滤，import 复用完整原字段映射。原候选、分析、重试、审核及历史接口不改路径。来源任务成功且资料 ready 时可以进入原 AI 队列；已有同版本任务/评估复用，避免无意义费用。

`MiaoshouPanel.vue` 嵌入现有 SourcingView：连接验证、最多 50 个链接采集、公共箱分页/状态/源 ID 查询、选择同步、可选导入后分析、来源任务进度和只读恢复。`MiaoshouSourceDetails.vue` 分开展示 SPU价、SKU价、库存、重量、尺寸、图片及原资料。现有候选卡片/表格、批量分析、风险和审核入口保留。

## 6. 数据库与环境

追加迁移：`554b31562dd4_miaoshou_sourcing_integration.py`，前驱 `0b8f25ba38cb`；当前仅一个 head：`554b31562dd4`。迁移只新增 sourcing_candidates 的 raw_data、SPU价/库存/重量、供应商/源资料、同步状态/时间以及来源任务表，不修改 Product、订单或旧评分列。

先在独立 PostgreSQL `tiktok_sourcing_test` upgrade 并通过测试及 alembic check，再核对本地业务数量、应用追加迁移到 `tiktok_ops_local`。没有 stamp 或删除业务数据。其他部署数据库仍须先在独立副本验证。本地启动脚本只检查当前 head，不自动迁移。

| 服务端环境变量 | 默认 / 说明 |
|---|---|
| `MIAOSHOU_APP_KEY` / `MIAOSHOU_APP_SECRET` | 真实开放平台凭证，仅 backend/.env 或服务端 Secret 管理 |
| `MIAOSHOU_TIMEOUT` | 30 秒，允许 5–120 |
| `MIAOSHOU_REQUEST_INTERVAL` | 1 秒，允许 0.1–60 |
| `MIAOSHOU_POLL_INTERVAL` | 5 秒，允许 1–300 |
| `MIAOSHOU_MAX_POLLS` | 8，允许 1–30 |
| `BAILIAN_API_KEY` / `DASHSCOPE_API_KEY` | 现有视觉模型密钥 |
| `BAILIAN_VISION_MODEL` | 本轮实际配置 qwen3-vl-plus |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | 本轮实际配置 deepseek-flash |
| `DATABASE_URL` | 目标业务 PostgreSQL；测试不得复用此库 |
| `TEST_DATABASE_URL` | 明确的独立 PostgreSQL *_test 库；测试入口拒绝缺失或非测试库 |

新增配置示例位于 `backend/.env.sourcing.example`，不会覆盖用户已填写的 `.env`。现有业务 mock 开关不控制新 SourceAdapter 或 ModelProvider。

## 7. 真实联调证据

验收顺序为签名/响应解析测试 → 真实只读接口 → 用户明确提供的单条商品 → 原始详情/数据库 → 重复同步 → 模型 → 审核。

| 项目 | 实际结果 |
|---|---|
| 鉴权与 #1 店铺 | result=success、code=success；tiktok / TH 的 shopList=[]；证明鉴权成功，不宣称已有店铺 |
| #4 公共箱列表 | 采集前读取 2 条已有记录；目标源 ID 查询为 0 条；采集后列表含新商品，源 ID 查询为 1 条 |
| #2 单条采集 | 用户提供 `635021027818`；仅提交标准 1688 offer 链接；原带跟踪参数输入留在本地任务，不转发/记录到报告 |
| #6 商品详情 | `4063817105`；完整详情真实返回，保存 12 张图片、8 个 SKU；缺失供应商不填造数据 |
| PostgreSQL 候选 | `82811147-b81d-46d3-bf37-3b80232c5913`，TH、v1、synced；SPU价6.2，库存36068767，weight1.1kg 均为接口原值，尚未人工核实 |
| 采集任务 | `15054092-81c7-4ce1-a393-746cab5fb9ea`；一次提交，3轮查询后 complete；17:33:28–17:33:45 |
| 重复同步 | `a1fdfeea-3c3d-4cfa-baad-4991bbd2caa8`；复用同一候选、v1 和同一 AI task；候选仍3条、AI任务仍4条 |
| 百炼 | qwen3-vl-plus，真实送入3张商品图；视觉78，request_id=`chatcmpl-3e4ff36b-ebcf-92b9-b267-9411a4ff8fb9` |
| DeepSeek | deepseek-flash，text_status=succeeded，request_id=`3e5c3502-0283-4588-a226-a4917edfd6fc` |
| AI任务 / 评估 | task=`6d513cde-787e-4caf-b915-481e98c63c5e`；evaluation=`0a7d6051-bd27-471f-8079-c2073e679af6`；视觉78、资料完整度规则80、市场指标未接入 |
| 审核 | 浏览器通过功能验收决策，绑定上述评估与v1、当前登录用户；备注明确仅验证流程，供应商/材质/需求仍需业务核实；刷新后保留 |

实际 #2 成功响应的必要字段摘录（没有请求头）：

```json
{
  "result": "success",
  "code": "success",
  "data": {
    "sourceItemIdAndDetailIdMap": {
      "635021027818": 4063817105
    }
  }
}
```

实际 SKU 原值示例：`;方盘1#加厚蓝色615*400*125mm;;` 的 price=22、oriPrice=22、stock=4353109、weight=1.1kg、包装尺寸61.5×40×12.5cm；`;方盘4#加厚蓝色370*250*65mm;;` 的 price=6.2、weight=0.3kg。接口的库存数字仅保留原值，不能当成已确认供应能力，更不是销量。

本轮数量变化：用户3→3，Product29→29，订单50→50，候选2→3，AI任务3→4，评估2→3，审核3→4。既有任务及失败记录、评估、审核历史保留。没有创建虚构 TikTok ID。

持久化证据：`docs/evidence/miaoshou-real-acceptance.json`；截图：`miaoshou-source-detail-acceptance.png`、`miaoshou-review-acceptance.png`、`miaoshou-candidates-acceptance.png`。JSON 是可公开检查的字段投影，完整响应文本和供应商/源资料原对象只在 PostgreSQL。可以用只读导出工具重新核对：

```powershell
# 在 backend 中先明确设置目标 DATABASE_URL；此命令不发起外部调用、不写数据库
../.venv/Scripts/python.exe -m scripts.export_miaoshou_evidence --source-item-id 635021027818
```

## 8. 测试结果

| 验证 | 结果 |
|---|---|
| 纯签名及请求/响应单元测试 | 19项通过；UTF-8、空白影响、请求Body与签名一致、四路径/字段、200/500错误分类、脱敏、限流、禁止发布、写请求不自动重试 |
| 货源 PostgreSQL 集成测试 | 5项通过；任务幂等、映射原值/单位、去重、AI入口、超时查询恢复、租约中断、用户隔离、缺价保持null、核心/源资料变更使评估过期 |
| 后端完整回归 | 52项通过，包括登录、商品、订单和既有选品流程；仅清理独立测试数据库 |
| Alembic | 测试库upgrade head与check通过，metadata无差异；业务追加迁移成功 |
| 前端 | `npm run build` 包含 vue-tsc 类型检查和 Vite 生产构建，通过 |
| 浏览器 | 登录、真实连接、链接采集、详情、源ID查询、公共箱重复同步、AI建议、审核保存及刷新恢复通过 |
| 实际 API 与凭证检查 | 登录用户、商品、订单、候选、来源任务及审核查询均200；251个 Git可见文件及前端JS产物扫描未发现已配置密钥，backend/.env被忽略；证据见 `docs/evidence/miaoshou-delivery-checks.json` |

测试中的 MockTransport 与 UNIT_ONLY 响应只用于单元/隔离测试，与上面的真实调用证据分开。测试仍有旧 Pydantic class Config 和 python-jose utcnow 弃用提示；生产构建仍提示既有较大 chunk，均不阻断本轮交付。

## 9. 遗留问题与第二阶段关联 ID

- tiktok / TH 读取到的店铺数为0。第二阶段必须读取用户实际店铺/site与权限，不能制造店铺ID。
- 公共箱没有返回币种和完整供应商资质。SPU价、SKU价格、库存、材质、承重和当地需求仍须人工核实；本轮未接市场销量或热度数据。
- 只验证用户指定的一条新链接，不对50条做真实外部写压测；批量上限和故障恢复通过隔离测试验证。平台处理时长可能超过默认轮询窗口，应使用查询恢复，不能盲目重采。
- API多实例的共享账户限流为生产扩展项；当前客户端进程内限流和来源Worker串行锁已生效。
- 早期候选不强制回填raw_data。需要时用公共箱同步；若新资料改变分析输入，重新评估，历史保留。
- 本机网络存在代理/Fake-IP DNS。商品图片仍沿用前阶段固定阿里CDN代理下载边界，拒绝任意内网地址及代理重定向；此次3张图片确实送入视觉模型。
- 当前机器仅完成本地库验收；其他部署迁移必须在独立副本验证。

本轮可供后续关联的是真实 `sourceItemId=635021027818`、`commonCollectBoxDetailId=4063817105`、标准原商品链接、候选UUID、AI task/评估UUID、输入版本与操作用户。**TK collectBoxDetailId、TK商品ID、发布SKU映射ID、实际shopId均尚未取得，也没有设置。**第二阶段应通过届时授权并实施的真实接口创建关联，不把公共箱ID复用为TK ID。

第一阶段完成后停止，等待用户的第二阶段上架开发指令。
