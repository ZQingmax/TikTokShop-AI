# 妙手开放平台 API 接口文档

## 本项目使用说明（2026-10-15）

本节为仓库维护说明；后续内容为 2026-10-13 整理的第三方接口参考，原接口定义保留。本文不表示已经重新向平台核验所有接口，也不表示本项目实现了下方全部 188 个接口。

当前签名、请求字段、超时和错误分类见 `backend/app/clients/miaoshou_client.py`（相对项目根目录）；业务路由注册见 `backend/app/api/v1/router.py`。

| 本项目场景 | 实现入口（均在 backend/app 下） |
|---|---|
| 授权店铺、货源采集、公共采集箱与详情 | `clients/miaoshou_client.py`、`services/miaoshou_tasks.py`、`services/miaoshou_sync_worker.py` |
| 采集箱草稿、认领店铺、类目 / 属性 / 仓库、图片转存、保存与回读 | `services/workbench_service.py`、`services/workbench_worker.py` |
| 店铺商品预检、发布产品、发布结果核对 | `services/listing_publish_service.py`、`services/listing_worker.py` |
| TK 采集箱商品、包裹及采购单读取与同步 | `services/product_sync_service.py`、`services/order_sync_service.py` |

首轮集成报告中的“仅四个接口、不认领、不发布、不做订单同步”描述的是当轮范围；后续实现已扩展到上表场景，不能作为当前客户端全量白名单。

公共箱 ID、TK 箱 ID、店铺 ID 不互换。SKU 来源价和店铺售价、货源库存和仓库库存分别使用；正式发布需通过店铺模式预检。外部写入结果未知时按任务恢复流程查询，不盲目重发。密钥仅配置在服务端。

项目内说明：[工作台](../docs/PRODUCT_WORKBENCH.md)、[首轮集成报告](../docs/MIAOSHOU_INTEGRATION_REPORT.md)、[当前需求索引](README.md)。

<!-- project-integration-note-end -->

---

> 文档来源：Apifox 分享文档《妙手开放平台》
> 整理时间：2026-10-13
> 接口总数：188（商品 138 / 包裹 13 / 采购 17 / 仓储 18 / 货源账号 2）

---

## 目录

- [一、快速接入](#一快速接入)
  - [1. 接口域名](#1-接口域名)
  - [2. 接入流程](#2-接入流程)
  - [3. 签名机制](#3-签名机制)
  - [4. 响应格式](#4-响应格式)
  - [5. 常见错误码](#5-常见错误码)
  - [6. 常见问题](#6-常见问题)
- [二、全局约定](#二全局约定)
- [三、接口列表](#三接口列表)
  - [商品（138）](#1-商品138)
  - [包裹（13）](#2-包裹13)
  - [采购（17）](#3-采购17)
  - [仓储（18）](#4-仓储18)
  - [货源账号（2）](#5-货源账号2)
- [四、附带说明](#四附带说明)

---

## 一、快速接入

面向妙手用户，介绍如何完成应用注册、签名生成与 API 调用。

### 1. 接口域名

- 正式环境接口基础域名：`https://openapi-erp.91miaoshou.com`
- 完整地址格式：正式域名 + 接口路径（例如路径 `/open/v1/order/create`，完整地址为 `https://openapi-erp.91miaoshou.com/open/v1/order/create`）
- **签名拼接时只传接口路径，不要带域名、不要带 query 参数。**

### 2. 接入流程

接入流程分为四步：**注册应用 → 获取密钥 → 生成签名 → 调用 API**。

1. **注册应用**：登录妙手 → 进入「开放平台」→「创建应用」→ 填写应用名称、描述 → 提交审核（通过后可用）。
2. **获取密钥**：应用创建成功后，系统分配 `AppKey`（应用标识，公开）与 `AppSecret`（应用密钥，保密，妥善保存，切勿泄露）。
3. **IP 白名单配置（可选）**：账户级别配置，一个用户一份白名单，名下所有应用共享；不配置则允许任意 IP 访问，配置后仅白名单内 IP 可访问该用户所有应用；不同用户白名单相互独立。
4. 调用 API：按签名机制构造请求头后发起 POST 请求。

### 3. 签名机制

- **算法**：HmacSHA256；输出为小写 hex 字符串。
- **有效期**：5 分钟（`timestamp` 与服务器时间偏差超过 300 秒则拒绝）。
- **签名公式**：

  ```text
  sign = HmacSHA256(appSecret, appSecret + path + timestamp + appKey + bodyJson + appSecret)
  ```

- **拼接规则**：以 `AppSecret` 开头 → 请求路径（不含域名、不含 Query）→ 秒级 Unix 时间戳 → `AppKey` → 请求 Body（JSON 字符串，无 body 时拼空字符串）→ 以 `AppSecret` 结尾。
- **请求头（每次请求必填）**：
  | 请求头 | 说明 |
  |---|---|
  | `x-app-key` | 应用 Key（AppKey） |
  | `x-timestamp` | 秒级 Unix 时间戳 |
  | `x-sign` | 签名值 |
- 文档另附 Java（Hutool `SecureUtil`）、Python（`hmac.new(app_secret, content, hashlib.sha256).hexdigest()`）与 HTTP/curl 示例，拼接逻辑均为：`appSecret + path + timestamp + appKey + bodyJson + appSecret`，curl 形式如下：

  ```bash
  curl -X POST "${BASE_URL}${PATH}" \
    -H "x-app-key: ${APP_KEY}" \
    -H "x-timestamp: ${TIMESTAMP}" \
    -H "x-sign: ${SIGN}" \
    -H "Content-Type: application/json" \
    -d "${BODY}"
  ```

### 4. 响应格式

- **成功响应**：

  ```json
  {"result":"success","code":"success","message":"success","data":{...}}
  ```

- **失败响应**：

  ```json
  {"result":"fail","code":"signInvalid","message":"签名验证不通过","data":null}
  ```

### 5. 常见错误码

| 错误码 | 说明 | 处理建议 |
|---|---|---|
| `success` | 成功 | — |
| `appNotFound` | 应用不存在或已禁用 | 检查 `x-app-key` 与审核状态 |
| `signMissing` | 缺少签名参数 | 检查三个请求头是否齐全 |
| `signExpired` | 请求已过期 | 检查本机时间，确保秒级时间戳，偏差≤300 秒 |
| `signInvalid` | 签名验证不通过 | 检查算法与 AppSecret |
| `appNoPermission` | 应用无权限访问该接口 | — |
| `ipNotInWhitelist` | IP 不在白名单中 | — |
| `accountQpsRateLimit` / `accountQpmRateLimit` / `accountQpdRateLimit` | 账户秒/分钟/天频率超限 | 降低请求频率，或联系平台提升限额 |
| `appQpsRateLimit` / `appQpmRateLimit` / `appQpdRateLimit` | 应用级秒/分/天频率超限 | 降低请求频率，或联系平台提升限额 |
| `apiQpsRateLimit` / `apiQpmRateLimit` / `apiQpdRateLimit` | 应用接口级超限 | 降低请求频率，或联系平台提升限额 |
| `platformQpsRateLimit` / `platformQpmRateLimit` / `platformQpdRateLimit` | 平台接口级超限 | 降低请求频率，或联系平台提升限额 |
| `accountApiQpsRateLimit` / `accountApiQpmRateLimit` / `accountApiQpdRateLimit` | 账户接口级超限 | 降低请求频率，或联系平台提升限额 |
| `routeNotFound` | 路由不存在 | 检查路径与域名拼接 |
| `upstreamError` | 下游服务连接失败 | 稍后重试 |
| `upstreamConnectTimeout` | 下游服务连接超时 | 稍后重试 |
| `upstreamReadTimeout` | 下游服务响应超时 | 稍后重试 |
| `upstreamDnsError` | 下游域名解析失败 | 检查域名与本地 DNS |
| `upstreamReset` | 下游连接被重置 | 稍后重试 |
| `systemError` | 系统内部错误 | 稍后重试，或联系平台技术支持 |
| `redisConnectionError` | 缓存服务连接失败 | 稍后重试，或联系平台技术支持 |
| `redisTimeout` | 缓存服务响应超时 | 稍后重试，或联系平台技术支持 |

### 6. 常见问题

- **Q1 签名总验证失败**：检查 AppSecret（大小写）、时间戳必须为秒级、路径不带域名和多余参数、POST 正确拼接 Body（无 body 拼空串）、签名输出为小写 hex。
- **Q2 返回“请求已过期”**：服务器时间同步，`timestamp` 偏差 ≤ 300 秒，必须是秒级时间戳。
- **Q3 域名解析失败 / ping 找不到主机**：确认域名拼写 `openapi-erp.91miaoshou.com`；切换公共 DNS（阿里 223.5.5.5 或 114.114.114.114）；检查本地防火墙/代理。
- **Q4 支持哪些 HTTP 方法**：目前仅支持 POST 方法，`Content-Type` 固定为 `application/json`。

---

## 二、全局约定

- 接口基础域名：`https://openapi-erp.91miaoshou.com`；签名拼接只用接口路径（不含域名、不含 query）。
- 鉴权：HmacSHA256，请求头 `x-app-key` / `x-timestamp`（秒级）/ `x-sign` 必填；`sign = HmacSHA256(appSecret, appSecret + path + timestamp + appKey + bodyJson + appSecret)`；有效期 5 分钟。
- **全部 188 个接口均为 POST**；`Content-Type` 固定为 `application/json`。
- 通用公共参数（几乎所有接口都有，下文记作「通用 5 项」）：Cookie `mserp`、Query `timerToken`、Header `x-gwms-account-id`（默认 `1000000`）、Header `x-enable-debug`、Header `Cookie`。
- 通用响应：`200`「成功」`{result, code, data}`（个别接口另带 `message` 字段）；`500`「error」→ `SimpleErrorResponse{result(返回结果), code(结果码/错误码), reason(错误信息)}`；另有 `SimpleSuccessResponse{result, code}`。

**标记说明**：下文接口条目中 `[必填]` 表示必填字段；未标注即为选填。

---

## 三、接口列表

### 1. 商品（138）

#### 1.1 店铺

**#1 获取店铺数据列表** `POST /open/v1/product/shop/shop/get_shop_list`
通用 5 项。Body 必填 `platform, site, pageNo, pageSize`：
- `platform` string 平台：TK 普通店铺 `tiktok`、TK 全球店铺 `tiktokGlobal`、TEMU 全托 `pddkj`、TEMU 半托 `pddkjChoice`、虾皮 `shopee`、虾皮全球 `shopeeGlobal`、美客多 `mercadolibre`、Ozon `ozon`
- `site` string 站点：TK 站点：印尼=ID、越南=VN、泰国=TH、马来=MY、菲律宾=PH、巴西=BR、墨西哥=MX、西班牙=ES、法国=FR、英国=GB、全球=TIKTOKGLOBAL、全球-美国=TIKTOKGLOBALUS、欧盟=TIKTOKGLOBALEU、美国=US、德国=DE、意大利=IT、日本=JP；TEMU 全托站点 PDDKJ；TEMU 半托站点 PDDKJCHOICE；虾皮站点：印尼=ID、台湾=TW、越南=VN、泰国=TH、马来西亚=MY、新加坡=SG、菲律宾=PH、巴西=BR、墨西哥=MX、智利=CL、哥伦比亚=CO、波兰=PL、西班牙=ES、法国=FR、阿根廷=AR；虾皮全球站点：全球=SHOPEEGLOBAL；美客多站点：传统模式=CBT、新 UP 发品模式=UP；Ozon 站点：OZON
- `pageNo` integer 当前页码（minimum 1）；`pageSize` integer 每页数量（maximum 100）
- 请求示例：`{"platform": "shopee", "site": "PH", "pageNo": 1, "pageSize": 100}`

响应 200 成功：`{result, code, data: {shopList[]` 店铺列表（`shopId` integer 店铺 ID、`site` string 站点、`siteName` string 站点名称、`platformShopName` string 平台店铺名称、`shopNick` string 店铺别名、`platform` string 平台、`parentShopId` integer 全球主店铺 ID、`isCb` integer 是否是跨境店铺、`isCnsc` integer 是否是全球店铺、`status` string 店铺状态、`gmtExpire` string 过期时间、`gmtLastAuth` string 最后授权时间）}}；500 → `SimpleErrorResponse`。

#### 1.2 公共采集箱

**#2 通过货源链接采集货源** `POST /open/v1/product/common_collect_box/common_collect_box/fetch_item`
通用 5 项（注：该接口无 Header `Cookie` 参数）。Body 必填 `collectLinks`：
- `collectLinks` array<string> 链接列表（maxItems 50）

响应 200 成功：`{result, code, data: {sourceItemIdAndDetailIdMap` object<integer> 货源 ID 和公共采集箱 ID 的映射}}；500 → `SimpleErrorResponse`。

**#4 获取公共采集箱列表** `POST /open/v1/product/common_collect_box/common_collect_box/get_common_collect_box_list`
通用 5 项。Body（无必填字段）：
- `pageNo` integer 当前页码；`pageSize` integer 每页数量（maximum 500）
- `filter` object 过滤器：`tabPaneName` string 状态（`all` 全部、`noClaimed` 未认领、`claimed` 已认领、`collectFail` 采集失败、`collectSuccess` 采集成功）、`sourceItemIdKeyword` string 货源 ID（maxLength 255）
- 请求示例：`{"pageNo": 1, "pageSize": 10}`

响应 200 成功：`{result, code, data: {detailList[]` 列表页数据列表（`commonCollectBoxDetailId` integer 公共采集箱详情 ID、`appAccountId` integer 主账号 ID、`subAppAccountId` integer 子账号 ID、`itemNum` string 货号、`title` string 标题、`thumbnail` string 主图缩略图、`price` number 价格、`minSkuPrice` number 最低 SKU 价格、`maxSkuPrice` number 最高 SKU 价格、`stock` integer 库存、`remark` string 备注、`status` string 状态、`reason` string 失败原因、`gmtCreate` string 创建时间、`gmtModified` string 修改时间、`weight` number 重量、`maxSkuWeight` number 最高 SKU 重量、`minSkuWeight` number 最低 SKU 重量、`commonCollectBoxGroupId` integer 采集箱分组 ID、`commonCollectBoxGroupName` string 采集箱分组名称，`sourceList[]` 来源信息列表（`remark` string 备注 maxLength 255、`sourceItemId` string 来源商品 ID maxLength 255、`source` string 来源平台 maxLength 255、`sourceSite` string 来源站点 maxLength 255、`sourceItemUrl` string 来源商品链接 maxLength 255）、`ownerSubAccountAliasName` string 子账号别名、`listThumbnail` string 列表缩略图、`isMark` string 是否标记）、`total` integer 总数，`isCommonCollectHuger` boolean 是否数量巨大}}；500 → `SimpleErrorResponse`。

**#6 获取公共采集箱详情** `POST /open/v1/product/common_collect_box/common_collect_box/get_common_collect_box_detail`
通用 5 项。Body 必填 `commonCollectBoxDetailId`（integer，公共采集箱 ID）。
响应 200 成功：`{result, code, data: {editCommonCollectBoxDetail` object 公共采集箱详情（`commonCollectBoxDetailId` integer 公共采集箱 ID、`title` string 产品标题、`itemNum` string 产品主编号、`notesText` string 简易描述、`notes` string 详细描述、`cateList` array<string> 类目列表、`sourceAttrs[]` 属性列表（`name` string 属性名 maxLength 255、`value` string 属性值 maxLength 255）、`price` number SPU 货源价格、`stock` integer 总库存、`imgUrls` array<string> 图片 URL 列表、`colorMap` object<颜色 key→颜色条目> 颜色 Map（值对象：`name` string 颜色名称 maxLength 255、`imgUrls` array<string> 颜色图片 URL 列表 maxItems 10、`imgUrl` string 颜色主图 URL）、`sizeMap` object<尺码 key→尺码条目> 尺码 Map（值对象：`name` string 尺码名称 maxLength 255）、`skuMap` object<SKU 规格组合串→SKU 条目> SKU Map（值对象：`itemNum` string 平台 SKU、`packageHeight` number 包装高度（cm）0~99999、`packageLength` number 包装长度（cm）0~99999、`packageWidth` number 包装宽度（cm）0~99999、`price` number 售价 0.01~99999.99、`stock` integer 库存 minimum 0、`weight` number 重量（kg）minimum 0.01、`oriPrice` number 原始售价、`oriStock` integer 原始库存）、`weight` number 重量（kg）、`packageLength` number 包装长度（cm）、`packageWidth` number 包装宽度（cm）、`packageHeight` number 包装高度（cm）、`colorPropName` string 颜色属性名（对应 sourceAttrs 中的 name）、`sizePropName` string 尺码属性名（对应 sourceAttrs 中的 name）、`saleProp3Name` string 第三销售属性名、`saleProp3Map` object<属性 ID→属性条目> 第三销售属性 Map（值对象：`name` string 第三销售属性名称 maxLength 255）、`sizeChart` string 尺码表 URL、`mainImgVideoUrl` string 主图视频 URL、`mainImgAppVideoId` string 主图 APP 视频 ID、`productCertifications[]` 产品认证列表（`fileName` string 文件名称 maxLength 255、`fileUrl` string 文件 URL）、`guideInfo` object 说明书信息（`productGuideFileName` string 文件名称 maxLength 255、`productGuideFileUrl` string 文件 URL maxLength 255）、`sourceMataInfo` object 货源元信息、`sourceSupplierInfo` object 货源供应商信息、`sourceList[]` 货源信息列表（`remark` string 备注 maxLength 255、`sourceItemId` string 来源商品 ID maxLength 255、`source` string 来源平台 maxLength 255、`sourceSite` string 来源站点 maxLength 255、`sourceItemUrl` string 来源商品链接 maxLength 255））、`ossMd5` string 公共采集箱详情 OssMd5 标识}}；500 → `SimpleErrorResponse`。

其余公共采集箱接口（清单级）：

| 编号 | 接口名称 | 文档链接 |
|---|---|---|
| #3 | 创建公共采集箱产品 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/446814585e0.md) |
| #5 | 编辑公共采集箱产品 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/446814586e0.md) |
| #7 | 批量删除公共采集箱产品 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/446814584e0.md) |
| #8 | 认领到平台采集箱 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/446814587e0.md) |

#### 1.3 TK 采集箱

**#20 产品翻译** `POST /open/v1/product/collect_box/tiktok/collect_box/translate_collect_item_info`
通用 5 项。Body 必填 `sourceLanguage, targetLanguage, collectItemInfo, isTranslateSkuItemNum, isTranslateSkuProperty`：
- `sourceLanguage` string 原始语言，可选值：`auto` 自动识别、`zh` 简体中文、`zh-tw` 中繁体、`en` 英文、`th` 泰文、`vi` 越南文、`id` 印尼文、`ms` 马来语、`es` 西班牙文、`pt` 葡萄牙语、`pl` 波兰语、`fr` 法文、`bn` 孟加拉语、`it` 意大利文、`de` 德语、`fi` 芬兰语、`cs` 捷克语、`ja` 日文、`he` 希伯来语、`ur` 乌尔都语、`uk` 乌克兰语、`el` 希腊语、`kk` 哈萨克语、`nl` 荷兰语、`sv` 瑞典语、`ko` 韩文、`ru` 俄文、`ar` 阿拉伯语、`tr` 土耳其语、`ro` 罗马尼亚语、`bg` 保加利亚语、`hu` 匈牙利语、`se` 瑞典语、`ga` 爱尔兰语
- `targetLanguage` string 目标语言，可选值同上（无 `auto`）
- `collectItemInfo` object 需翻译的产品详情：`title` string 商品标题、`notes` string 备注、`warrantyPolicy` string 保修政策、`skuMap` object<SKU 标识码→SKU 条目> SKU Map（值对象：`price` number 售价、`priceIncludeVat` number 本地展示价、`originPrice` number 货源价格、`itemNum` string 货品编号、`stock` integer 库存数量、`identifierCode` string 识别码、`identifierCodeType` string 识别码类型、`isDelete` string 是否已删除（0 否、1 是）、`weight` number 重量（kg）、`shopIdToWarehouseIdAndStockMap` object 店铺 ID 到仓库 ID 及库存的映射 array<shopId, array<warehouseId, stock>>）、`skuPropertyList[]` SKU 销售属性列表（`attrId` string 属性 ID、`attrName` string 属性名称、`attrValueList[]` 属性值列表（`attrValueId` string 属性值 ID、`attrValue` string 属性值、`imgUrl` string 属性图片 URL、`supplementarySkuImageUrls` array<string> 补充 SKU 图片 URL 列表））、`productAttributes[]` 商品属性列表（`attributeId` string 属性 ID、`attributeName` string 属性名称、`attributeValues[]` 属性值列表（`valueName` string 属性值名称、`valueId` string 属性值 ID））
- `isTranslateSkuItemNum` integer 是否翻译平台 sku（0=否，1=是）；`isTranslateSkuProperty` integer 是否翻译 SKU 规格名称（0=否，1=是）

响应 200 成功：`{result, code, data: {collectItemInfo` object 翻译后的产品详情（只翻译，没有保存翻译后的数据，用户需自行保存）}}；500 → `SimpleErrorResponse`。

**#21 AI 匹配类目** `POST /open/v1/product/collect_box/tiktok/collect_box/ai_match_cid_by_shop_ids`
通用 5 项。Body 必填 `collectBoxDetailId`（integer，采集箱详情 ID）、`shopIds`（array<integer>，店铺 ID 列表，minItems 1, maxItems 3）。
响应 200 成功：`{result, code, data: {shopIdAndCidMap` object<integer> 店铺与匹配 CID 的映射（示例 `{100001: 11231, 100002: 12345}`）、`failedShopIds` array<integer> 匹配失败的店铺 ID 列表（失败即代表该店铺没有匹配上类目）}}；500 → `SimpleErrorResponse`。

**#23 AI 属性匹配** `POST /open/v1/product/collect_box/tiktok/collect_box/ai_match_product_attribute`
通用 5 项。Body 必填 `collectBoxDetailId`（integer，采集箱详情 ID）、`cid`（string，类目 ID）、`site`（string，站点）；选填 `shopIds`（array<integer>，店铺 ID 列表，当产品与店铺关联时传入，用于精确查找）、`productAttributes[]` 当前产品属性列表（`attributeId` string 属性 ID、`attributeName` string 属性名称、`attributeValues[]` 属性值列表（`valueName` string 属性值名称、`valueId` string 属性值 ID））。
响应 200 成功：`{result, code, data: {productAttributes[]` AI 匹配后的产品属性列表（`attributeId` string 属性 ID、`attributeName` string 属性名称、`attributeValues[]` 属性值列表（`valueName` string 属性值名称、`valueId` string 属性值 ID））}}；500 → `SimpleErrorResponse`。

**#25 产品发布：发布产品** `POST /open/v1/product/collect_box/tiktok/collect_box/save_move_collect_task`
通用 5 项。Body 必填 `shopIds`（array<integer>，店铺 ID，maxItems 200）、`detailIds`（array<integer>，采集箱详情 ID，maxItems 200）。
响应 200 成功：`SimpleSuccessResponse`；500 → `SimpleErrorResponse`。

其余 TK 采集箱接口（清单级）：

| 编号 | 接口名称 | 文档链接 |
|---|---|---|
| #9 | 获取类目列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/446814588e0.md) |
| #10 | 获取类目属性信息 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/446814589e0.md) |
| #11 | 获取店铺仓库列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/446814590e0.md) |
| #12 | 获取制造商列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/449869292e0.md) |
| #13 | 获取欧盟责任人列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/449869293e0.md) |
| #14 | 认领预发布店铺 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/446814594e0.md) |
| #15 | 获取采集箱列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/446814591e0.md) |
| #16 | 获取采集箱店铺模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/446814592e0.md) |
| #17 | 保存采集箱店铺模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/446814593e0.md) |
| #18 | 获取采集箱站点模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/449650816e0.md) |
| #19 | 保存采集箱站点模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/449650817e0.md) |
| #22 | 批量删除采集箱产品接口 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/496804330e0.md) |
| #24 | 获取品牌列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/497001483e0.md) |
| #26 | 产品发布：发布记录列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/482189163e0.md) |
| #27 | 定价模板：获取定价模板列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/482189164e0.md) |
| #28 | 定价模板：获取各个站点的默认配置 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/482189165e0.md) |

#### 1.4 TEMU 全托采集箱

| 编号 | 接口名称 | 文档链接 |
|---|---|---|
| #29 | 产品发布：发布产品 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/468724006e0.md) |
| #30 | 产品发布：发布记录列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/511668107e0.md) |
| #31 | 车型库：获取车型库站点列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/468724008e0.md) |
| #32 | 车型库：获取车型库站点属性结构映射 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/468724009e0.md) |
| #33 | 车型库：获取站点顶级车型节点列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/468724010e0.md) |
| #34 | 车型库：获取车型属性依赖树 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/468724011e0.md) |
| #35 | 车型库：根据类目 ID 查询有车型库数据的类目列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/468724007e0.md) |
| #36 | 采集箱：获取类目属性规则 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545320e0.md) |
| #37 | 采集箱：获取商品基本选项 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545321e0.md) |
| #38 | 采集箱：创建采集箱商品 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545322e0.md) |
| #39 | 采集箱：认领预发布店铺 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545323e0.md) |
| #40 | 采集箱：获取采集箱店铺模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545324e0.md) |
| #41 | 采集箱：保存采集箱店铺模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545325e0.md) |
| #42 | 采集箱：获取采集箱站点模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545326e0.md) |
| #43 | 采集箱：保存采集箱站点模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545327e0.md) |
| #44 | 采集箱：获取原产地国家列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545328e0.md) |
| #45 | 采集箱：店铺模特列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545329e0.md) |
| #46 | 采集箱：获取类目列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545330e0.md) |
| #47 | 采集箱：获取尺码模板列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545331e0.md) |
| #48 | 采集箱：获取尺码表详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545332e0.md) |
| #49 | 采集箱：获取模特分类配置 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545333e0.md) |
| #50 | 采集箱：获取采集箱列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545334e0.md) |
| #51 | 采集箱：批量删除采集箱产品接口 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/471545335e0.md) |
| #52 | 采集箱：获取需要设置净重的类目列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/490449047e0.md) |

#### 1.5 TEMU 半托采集箱

| 编号 | 接口名称 | 文档链接 |
|---|---|---|
| #53 | 商品发布：发布产品 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/468726294e0.md) |
| #54 | 商品发布：发布记录列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/511667358e0.md) |
| #55 | 车型库：获取车型库站点列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/468726296e0.md) |
| #56 | 车型库：获取车型库站点属性结构映射 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/468726297e0.md) |
| #57 | 车型库：获取站点顶级车型节点列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/468726298e0.md) |
| #58 | 车型库：获取车型属性依赖树 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/468726299e0.md) |
| #59 | 车型库：根据类目 ID 查询有车型库数据的类目列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/468726295e0.md) |
| #60 | 采集箱：获取类目属性规则 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347599e0.md) |
| #61 | 采集箱：店铺模特列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347600e0.md) |
| #62 | 采集箱：获取商品基本选项 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347601e0.md) |
| #63 | 采集箱：创建采集箱商品 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347602e0.md) |
| #64 | 采集箱：认领预发布店铺 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347603e0.md) |
| #65 | 采集箱：获取采集箱站点模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347606e0.md) |
| #66 | 采集箱：保存采集箱店铺模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347605e0.md) |
| #67 | 采集箱：获取采集箱店铺模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347604e0.md) |
| #68 | 采集箱：保存采集箱站点模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347607e0.md) |
| #69 | 采集箱：获取原产地国家列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347608e0.md) |
| #70 | 采集箱：获取发布站点选项 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347609e0.md) |
| #71 | 采集箱：获取店铺运费模板 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347610e0.md) |
| #72 | 采集箱：获取店铺发货仓库（支持同步） | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347611e0.md) |
| #73 | 采集箱：获取类目列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347612e0.md) |
| #74 | 采集箱：获取尺码模板列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347613e0.md) |
| #75 | 采集箱：获取尺码表详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347614e0.md) |
| #76 | 采集箱：获取模特分类配置 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347615e0.md) |
| #77 | 采集箱：获取采集箱列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347616e0.md) |
| #78 | 采集箱：批量删除采集箱产品接口 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/477347617e0.md) |
| #79 | 采集箱：获取包装清单属性值列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/501791146e0.md) |

#### 1.6 OZON 采集箱

| 编号 | 接口名称 | 文档链接 |
|---|---|---|
| #80 | 获取采集箱编辑币种（ozon 采集箱涉及售价、原价、最低售价均为该币种，货源价格为 CNY） | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/474774623e0.md) |
| #81 | 获取类目列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/474774625e0.md) |
| #82 | 获取类目属性信息 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/474774626e0.md) |
| #83 | 获取采集箱列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/474774624e0.md) |
| #84 | 获取店铺仓库列表 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/474774627e0.md) |
| #85 | 获取采集箱站点模式详情 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/474774628e0.md) |
| #86 | 创建采集箱站点模式数据 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/474774629e0.md) |
| #87 | 编辑采集箱站点模式数据 | [查看文档](https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68/474774630e0.md) |


#### 1.7 OZON 采集箱：产品发布

**#88 发布记录列表** `POST /open/v1/product/collect_box/ozon/move_collect/search_move_collect_list`
通用 5 项。Body 必填 `pageNo, pageSize`：
- `pageNo` int 当前页码（min 1）；`pageSize` int 每页数量（min 1, max 20）
- `filter` object：`status`（`success` 发布成功、`fail` 发布失败、`processing` 发布中、`cancel` 已取消）、`itemId` 产品 ID（max 255）、`sourceItemId` 货源 ID（max 255）

响应 `data`：`moveCollectDetailList[]`（`subDetailList[]` SKU 对应产品发布详情：`ozonOfferId` 平台 SKU、`platformItemId` 产品 ID、`stock` 库存、`status` 发布状态、`reason` 发布失败原因、`gmtCreate`/`gmtModified`；`moveCollectTaskDetailId` 发布任务详情 ID、`collectBoxDetailId` 采集箱详情 ID、`shopId`、`itemNum`、`cid`、`source`、`sourceSite`、`sourceItemId`、`title`、`thumbnail`、`isTiming` 是否定时发布、`status` 发布状态、`reason` 失败原因、`gmtCreate`/`gmtModified`、`platformItemId` 平台商品 ID、`isRenewItem` 是否翻新、`shopName`、`siteName`、`site`、`sourceItemUrl` 来源商品链接、`itemEditUrl` 商品编辑链接、`breadcrumb` 类目路径、`ownerSubAppAccountId` 归属子账号 ID、`ownerSubAccountAliasName` 归属子账号名称）；`total` 总数。

**#89 发布产品** `POST /open/v1/product/collect_box/ozon/move_collect/save_move_collect_task`
通用 5 项。Body 必填：
- `shopIds` array<int> 店铺 ID（max 200）
- `detailIds` array<int> 采集箱详情 ID（max 200）

响应：`SimpleSuccessResponse`。

#### 1.8 Shopee 采集箱

**#90 获取站点编辑信息** `POST /open/v1/product/collect_box/shopee/collect_box/get_site_detail_simple_data`
通用 5 项。Body 必填 `detailId`（int，采集箱产品 ID）、`site`（站点，如 SHOPEEGLOBAL / TW / ID / MY）。

响应 `data`：
- `supportSizeChartInfo` 尺码图支持信息：`shopeeCategorySupportSizeChartId`、`site`、`cid`、`isSupportSizeChart`（0, 1）、`sizeChartMandatory`、`supportImageSizeChart`、`supportTemplateSizeChart`、`gmtCreate`/`gmtModified`
- `siteDetailSimpleData` 站点信息详情（必填 `cid,title,imgUrls,weight,notes,brand,logisticList,isPreOrder`）：`cid` 类目 ID；`title` 商品标题（min 10, max 255）；`itemNum` 主货号；`price` 销售价（单规格必填）；`stock` 库存（单规格必填）；`sellerStock[]` 按仓库分配库存（`locationId, stock, shopId`）；`colorPropName`/`sizePropName` 颜色/尺码属性名称；`colorMap`（key=颜色名：`name, imgUrls, imgUrl, mapKey` 前端唯一键, `index, isMock` 是否为模拟数据）；`sizeMap`（key=尺码名：`name, mapKey`）；`skuMap`（key=规格组合：`itemNum` SKU 商家编码，`price` number 销售价 min 0.01 [必填], `originPrice` 货源价格，`stock` int 库存 min 0 [必填]，`sellerStock[]`，`weight` 重量（kg），`packageHeight`/`packageLength`/`packageWidth` 包裹尺寸（cm），`colorPropName`/`sizePropName`，`daysToShip` 发货天数，`barcode` 识别码，`barcodeType` 识别码类型）；`imgUrls[]` 产品图片 URL（JPG/JPEG/PNG, ≤3M，建议 800x800）；`weight` 重量（kg）min 0.01；`packageLength`/`packageWidth`/`packageHeight` 包裹尺寸（必须全填或者全不填）；`notes` 商品描述 min 3；`richTextDesc` 富文本描述；`wholesaleList[]`（`min` 最小数量，`max` 最大数量，`price` 批发单价）；`attributeMaps`（key=属性 ID：`attributeId, attributeName, valueList[]{valueId, valueName, valueUnit, originalValueName}, unit, isRequire`）；`brand` 品牌信息（`brandId, brandName`）；`logisticList[]`（`logisticId` 物流方式 ID、`logisticName`、`enabled` 是否启用、`estimatedShippingFee` 预估运费、`isFree` 是否包邮、`sizeId` 尺寸 ID、`customPrice` 自定义运费、`site` 站点）；`isPreOrder` 是否预售（1=是，0=否）；`daysToShip` 发货天数；`sizeChart` 尺码表图片 URL（类型为 image 时必填）；`mainImgVideoUrl` 产品视频 URL（像素≤1280×1280, 10s~60s, <30M, MP4）；`mainImgAppVideoId` 产品视频 AppVideoId；`mainImgVideoExpire` 产品视频过期时间；`isMainImgVideoExpire` 产品视频是否过期；`originPrice` 货源价格；`colorPropGroupName`/`sizePropGroupName` 颜色/尺码属性分组名称；`preOrderType` 是否按 SKU 配置出货天数（spu/sku）；`sizeChartType` 尺码表类型（template/image，部分类目必填）；`shopIdAndSizeChartIdMap<int>` 店铺 ID 与尺码表 ID 映射（template 时必填）；`certificationInfoList[]`（`certificationType` 认证类型 ID、`certificationNo` 认证编码、`expireTime` 过期时间戳、`certificationProofs[]{fileType` 文件类型, `fileName` 文件名, `fileUrl` 文件 URL, `uid` 文件 UUID}, `permitId` 认证 ID、`name` 认证名称）；`isSuppSizechart` 是否支持尺码表；`hasTranslate` 是否已翻译（1=是）；`barcode`/`barcodeType` 识别码/识别码类型；`isFirstCreateSiteData`；`logisticOptions`（`label` 物流名称，`value` 物流 ID）；`ossMd5`

**#91 保存站点编辑数据** `POST /open/v1/product/collect_box/shopee/collect_box/save_site_detail_data`
通用 5 项。Body 必填 `detailId`（int，采集箱产品 ID）、`site`（站点）、`ossMd5`（OSS 数据的 MD5 值）、`siteDetailSimpleData`（站点编辑数据，字段集同 #90，必填 `cid,title,imgUrls,weight,notes,brand,logisticList,isPreOrder`）。
- `syncSites[]` 需要同步的其他站点列表；`syncSiteFields[]` 需要同步的站点字段列表；`shopIdAndSizeChartIdMap<int>` 店铺 ID 与尺码表 ID 映射

响应 `data`：`ossMd5`；`syncErrors[]` 同步错误列表（`site` 站点，`errorMsg` 错误信息）。

**#92 创建采集箱 SPU（手动添加商品）** `POST /open/v1/product/collect_box/shopee/collect_box/create_collect_box_item`
通用 5 项。Body 必填 `site`（站点）、`siteDetailSimpleData`（字段集同 #90）。
响应 `data`：`collectBoxDetailId` int 采集箱详情 ID。

**#93 获取采集箱产品的源数据** `POST /open/v1/product/collect_box/shopee/collect_box/get_collect_box_item_detail`
通用 5 项。Body 必填 `detailId`（int，采集箱产品 ID）。
响应 `data`：
- `itemDetail` 采集箱详情数据（必填 `title,notes,weight,imgUrls,isPreOrder`）：`title` 标题，`notes` 简易描述，`richTextDesc` 图文描述，`colorPropName` 颜色属性名称，`sizePropName` 尺码属性名称，`skuMap` SKU 映射（多规格必填，结构同 #90），`colorMap` 颜色映射（多规格必填），`sizeMap` 尺寸映射（多规格必填），`imagePaths[]` 图片路径列表，`sourceAttrs[]{name` 属性名 max 255, `value` 属性值 max 255} 来源属性列表，`brandName` 品牌名称，`itemNum` 商品编码，`width`/`length`/`height` 宽度/长度/高度，`weight` 重量（kg）min 0.01，`videoInfo` 视频信息（`videoUrl, coverUrl`），`appAccountId`/`subAppAccountId` 应用账户 ID/子应用账户 ID，`sourceItemId` 来源商品 ID，`source` 来源，`site` 站点，`price` 价格（单规格必填），`stock` 库存（单规格必填），`packageLength`/`packageWidth`/`packageHeight` 包裹长度/宽度/高度，`imgUrls[]` 图片 URL 列表，`mainImgVideoUrl` 主图视频 URL，`mainImgAppVideoId` 主图应用视频 ID，`isPreOrder` 是否预售（0, 1），`daysToShip` 预购天数（`isPreOrder`=1 时必填），`preOrderType`（spu/sku）
- `ossMd5` OSS 数据的 MD5 值

**#94 保存采集箱产品源数据信息** `POST /open/v1/product/collect_box/shopee/collect_box/save_edit_item`
通用 5 项。Body 必填 `collectBoxDetailId`（string，采集箱 ID）、`itemDetail`（字段集同 #93）、`ossMd5`（OSS 标识）。
响应 `data`：`ossMd5`。

**#95 获取采集箱列表** `POST /open/v1/product/collect_box/shopee/collect_box/search_collect_box_detail_list`
通用 5 项。Body：`pageNo` 当前页码；`pageSize` 每页数量（max 500）；`filter`（`status`：`notPublished` 未发布、`timingPublish` 定时发布、`published` 已发布；`sourceItemIdKeyword` 货源 ID max 255）。
响应 `data`：`detailList[]{collectBoxDetailId` 采集箱详情 ID, `itemNum` 商品编号，`stock` 库存，`price` 价格，`thumbnail` 缩略图，`gmtCreate` 创建时间，`editModel` 编辑模式，`commonCollectBoxDetailId` 公共采集箱详情 ID, `appAccountId`/`subAppAccountId`, `platform` 平台，`title` 商品标题，`remark` 备注，`copyType` 复制类型，`collectBoxGroupId` 采集箱分组 ID, `collectBoxDetailShopList[]{shopId` 店铺 ID} 预发布店铺信息列表}。

**#96 获取品牌列表** `POST /open/v1/product/collect_box/shopee/collect_box/get_brand_list`
通用 5 项。Body 必填 `cid`（类目 ID）、`site`（站点，max 32）。
响应 `data`：`isMandatory` 品牌是否必填；`inputType` 输入类型；`brandList[]{brandId` 品牌 ID, `brandName` 品牌名称}；`gmtModified` 最后修改时间；`isFromOss` 是否来自 OSS 缓存。

**#97 根据站点获取运费模板（物流方式）** `POST /open/v1/product/collect_box/shopee/collect_box/get_logistic_options_by_site`
通用 5 项。Body 必填 `site`（站点）。
响应 `data`：`label` 物流选项标签；`value` 物流选项值；`feeType` 运费类型；`isEnableEditShippingFee` 是否允许编辑运费。

**#98 获取类目树** `POST /open/v1/product/collect_box/shopee/collect_box/get_category_tree_by_site`
通用 5 项。Body 必填 `site`（站点，如 TW / ID / MY / SHOPEEGLOBAL，max 32）。
响应 `data`：`cateTree` 分类树 Map（key=cid）：`cid`、`aid` 祖先分类 ID、`fid` 父分类 ID、`name` 分类名称（英文）、`nameChinese` 中文、`isLastLevel` 是否末级分类、`disabled` 是否禁用、`children` 子分类 Map（key=cid）。

**#99 获取类目属性信息** `POST /open/v1/product/collect_box/shopee/collect_box/get_category_attributes`
通用 5 项。Body 必填 `cid`（类目 ID）、`site`（站点）。
响应 `data`：`categoryAttributes[]{attributeId` 属性 ID, `attributeUnit[]` 属性参数单位值（单选）, `attributeValueList[]{valueId, displayValueName, originalValueName}` 属性选项, `displayAttributeName` 属性别名（一般中文）, `formatType` 属性参数格式类型（NORMAL，QUANTITATIVE，YEAR_MONTH_DATE，YEAR_MONTH）, `inputType` 属性内容类型（DROP_DOWN, MULTIPLE_SELECT, TEXT_FILED, COMBO_BOX, MULTIPLE_SELECT_COMBO_BOX）, `inputValidationType` 属性内容校验类型（INT_TYPE STRING_TYPE ENUM_TYPE FLOAT_TYPE DATE_TYPE TIMESTAMP_TYPE）, `isMandatory` 是否必填，`maxInputValueNumber` 最大输入值数量，`originalAttributeName` 接口原始属性名} 类目属性列表。

**#100 获取仓库信息列表** `POST /open/v1/product/collect_box/shopee/collect_box/get_global_shop_warehouse`
通用 5 项。Body 必填 `shopId`（int，店铺 ID）。
响应 `data`：`warehouseLocationList[]{locationId` 属性 ID, `shopName` 店铺别名，`warehouseLocationType` 仓库类型（local 本土，cb 跨境）, `warehouseName` 仓库名称} 仓库信息列表。

**#101 商品发布：发布记录列表** `POST /open/v1/product/collect_box/shopee/move_collect/search_move_collect_list`
通用 5 项。Body 必填 `pageNo`（min 1）、`pageSize`（min 1, max 20）；`filter`（`status`：`success` 发布成功、`fail` 发布失败、`processing` 发布中、`cancel` 已取消；`itemId` 产品 ID max 255、`sourceItemId` 货源 ID max 255）。
响应 `data`：`moveCollectDetailList[]`（`moveCollectTaskDetailId` 发布任务详情 ID、`collectBoxDetailId`、`shopId`、`itemNum`、`cid`、`source`、`sourceSite`、`sourceItemId`、`title`、`thumbnail`、`isTiming` 是否定时发布、`status` 发布状态、`reason` 失败原因、`gmtCreate`/`gmtModified`、`platformItemId` 平台商品 ID、`isRenewItem` 是否翻新、`shopName`、`siteName`、`site`、`sourceItemUrl` 来源商品链接、`itemEditUrl` 商品编辑链接、`breadcrumb` 类目路径、`ownerSubAppAccountId` 归属子账号 ID、`ownerSubAccountAliasName` 归属子账号名称）；`total` 总数。

**#102 商品发布：提交全球商品发布到店铺任务** `POST /open/v1/product/collect_box/shopee/move_collect/save_move_collect_global_task`
通用 5 项。Body 必填 `shopeeGlobalItemIds`（array<int>，全球商品 ID）、`shopIds`（array<int>，店铺 ID）；`isUseShopeeGlobalSetting` int 是否使用全球发布配置（1 是，0 否）。
响应 `data`：`moveCollectTaskDetailIds` array<int> 任务 ID。

**#103 商品发布：采集箱产品发布任务** `POST /open/v1/product/collect_box/shopee/move_collect/save_move_collect_task`
通用 5 项。Body 必填：`shopIds` array<int> 店铺 ID（max 200）；`detailIds` array<int> 采集箱详情 ID（max 200）。
响应：`SimpleSuccessResponse`。

#### 1.9 在线产品管理：Shopee 全球在线产品管理

**#104 全球产品搜索** `POST /open/v1/product/item/shopee_global/item/search_item_list`
通用 5 项。Body 必填 `pageNo, pageSize, filter`：
- `pageNo` 页码，默认 1（min 1）；`pageSize` 每页条数，默认 20（min 1, max 100）
- `filter` 搜索条件（必填 `shopId` 店铺 ID [必传，性能问题无法支持多店铺检索]）：`shopId`、`platformItemId` 平台产品 ID、`itemNum` 主货号，`cids[]` 类目 ID、`status` 产品状态，`title` 标题，`minStock` 最小库存，`maxStock` 最大库存，`publishedProductStatus` 发布产品状态

响应 `data`：`itemList[]{shopId/itemId/itemNum/platformItemId/title`, `picUrl` 产品图片链接，`salePrice` 售价，`stock` 库存，`platformStatus` 发布状态，`status` 产品状态，`weight` 重量，`gmtCreate` 创建时间} 产品列表；`total` 总数。

**#105 全球产品详情** `POST /open/v1/product/item/shopee_global/item/get_item_detail`
通用 5 项。Body 必填 `shopId`（店铺 ID）、`platformItemId`（平台产品 ID）。
响应 `data`：
- `itemInfo` 全球商品详情（必填 `globalItemId`）：`globalItemId` Shopee 全球商品唯一标识，`globalItemName` 全球商品名称，`description` 全球商品描述，`globalItemSku` 全球商品 SKU、`globalItemStatus` 商品状态（NORMAL）、`createTime`/`updateTime` 创建/更新时间戳、`stockInfo[]` 库存信息（无规格时返回：`stockType` 库存类型，`stockLocationId` 库存位置 ID、`normalStock` 正常库存，`reservedStock` 预留库存）、`priceInfo[]` 价格信息（无规格时返回：`currency` 币种，`originalPrice` 原价，`sipItemPrice` SIP 商品价格，`sipItemPriceSource` SIP 价格来源（auto / manual））、`image` 图片信息（必填 `imageIdList`：`imageIdList`/`imageUrlList[]`）、`weight` 重量（单位 KG）、`dimension` 包裹尺寸（`packageLength`/`packageWidth`/`packageHeight`，单位 CM）、`preOrder` 预售信息（必填 `daysToShip`：`daysToShip` 发货天数 DTS）、`sizeChart` 尺码表图片 URL、`condition` 是否二手（NEW / USED）、`hasModel` 是否包含规格、`video[]` 视频信息（获取商品详情时此字段有值，编辑时无效：`videoUrl, thumbnailUrl, duration` 视频时长单位秒）、`videoUploadId` 视频 ID（通过上传视频接口获取，编辑商品时用于更新商品视频）、`categoryId` 分类 ID、`brand` 品牌信息（`brandId, originalBrandName`）、`attributeList[]{attributeId, originalAttributeName, attributeValueList[]{valueId, originalValueName, valueUnit}}` 属性列表、`descriptionInfo` 新版描述信息（`extendedDescription` 扩展描述：`fieldList[]{fieldType` 字段类型 text / image、`text` 文本内容（field_type 为 text 时返回）、`imageInfo` 图片信息（field_type 为 image 时返回：`imageId, imageUrl`）} 扩展描述字段列表；`descriptionType` 描述类型 normal / extended）、`isFulfillmentByShopee` 是否为 Shopee 履约商品、`sizeChartId` 尺码表模板 ID
- `modelList` 全球规格列表：`tierVariation[]{name` 层级规格名称，`optionList[]{option` 层级规格选项值} 层级规格选项列表，`image` 层级规格图片（`imageUrl`/`imageId`）}、`globalModel[]` 全球规格列表（SKU 列表：`globalModelId` 全球规格 ID、`globalModelSku` 全球规格 SKU、`priceInfo`（`originalPrice` 原价）价格信息、`stockInfo[]{stockType` 库存类型（1 = WMS 在库，2 = 卖家在库）、`stockLocationId`、`currentStock`/`normalStock`/`reservedStock`} 库存信息、`tierIndex[]` 层级索引，`weight` 重量（单位 KG）、`dimension` 包裹尺寸（必填 `packageHeight`/`packageLength`/`packageWidth`）、`preOrder` 预售信息（必填 `daysToShip`）、`isFulfillmentByShopee` 是否为 FBS 规格）、`standardiseTierVariation[]` 标准化层级规格信息（`variationId` 标准化层级规格 ID、`variationName` 标准化层级规格名称，`variationGroupId` 标准化层级规格组 ID、`variationOptionList[]{variationOptionId, variationOptionName}` 标准化层级规格选项列表，`imageId`/`imageUrl`）

**#106 保存产品编辑** `POST /open/v1/product/item/shopee_global/item/save_edit_item`
通用 5 项。Body 必填 `shopId`（店铺 ID）、`itemInfo`（全球商品详情，前端修改后的 GetItemDetailVo.itemInfo，仅传新数据，必填 `globalItemId`，字段集同 #105）；`modelList` 全球规格列表（前端修改后的 GetItemDetailVo.modelList，仅传新数据，字段集同 #105）。
响应：`SimpleSuccessResponse`。

**#107 获取属性列表** `POST /open/v1/product/item/shopee_global/item/get_attribute_list`
通用 5 项。Body 必填 `cid`（类目 ID）；选填 `shopId`（店铺 ID）、`site`（站点）。
响应 `data`：`attributes[]{attributeId, originalAttributeName, displayAttributeName, isMandatory, inputValidationType, formatType, inputType, attributeUnit[], attributeValueList[]{valueId, originalValueName, displayValueName, parentAttributeList[]{parentAttributeId, parentValueId}}, maxInputValueNumber, introduction, mandatoryRegion[]}` 属性列表；`lang` 语言。

**#108 获取全球店铺类目尺寸模板列表** `POST /open/v1/product/item/shopee_global/item/get_shop_id_and_size_chart_list_map`
通用 5 项。Body 必填 `shopIds`（array<int>，店铺 ID 列表）、`cid`（类目 ID）。
响应 `data`：`shopIdAndSizeChartListMap` 店铺 ID 与尺寸模板列表映射（key=shopId, value=array：`shopId`、`sizeChartId` 尺寸模板 ID、`sizeChartName` 尺寸模板名称，`categoryId` 类目 ID、`measurementList[]` 尺码表格数据（包含 measurementList）：`measurement` 测量定义（`inputType` 输入类型如 Single Dropdown、`unit` 单位如 cm、`displayName` 显示名称如 Width/Length）、`measurementValueList[]` 测量值列表（`value`/`minValue`/`maxValue` 值/最小值/最大值，`option` 选项））。

**#109 上传商品视频** `POST /open/v1/product/item/shopee_global/item/upload_item_video`
通用 5 项。Body 必填 `shopId`（店铺 ID）、`sourceVideoUrl`（视频 URL）。
响应 `data`：`videoUploadId` int。

**#110 同步产品** `POST /open/v1/product/item/shopee_global/item/rsync_item_single`
通用 5 项。Body 必填 `shopId`（店铺 ID）、`platformItemIds`（array<string>，平台产品 ID，maxItems 10）。
响应 `data`：`successPlatformItemIds[]`；`failedPlatformItemIds[]`；`errorMap<string>`。

**#111 全球产品删除** `POST /open/v1/product/item/shopee_global/item/delete_item`
通用 5 项。Body 必填 `shopId`（店铺 ID）、`platformItemId`（平台产品 ID）。
响应：`SimpleSuccessResponse`。

#### 1.10 Mercadolibre 采集箱

**#112 发布产品：发布产品** `POST /open/v1/product/collect_box/mercadolibre/move_collect/save_move_collect_task`
通用 5 项。Body 必填 `detailIds`（array<int>，采集箱详情 ID，max 200）。
响应：`SimpleSuccessResponse`。

**#113 发布产品：发布记录列表** `POST /open/v1/product/collect_box/mercadolibre/move_collect/search_move_collect_list`
通用 5 项。Body 必填 `pageNo`（min 1）、`pageSize`（min 1, max 20）；`filter`（`status`：`success` 发布成功、`fail` 发布失败、`processing` 发布中、`cancel` 已取消；`itemId` 产品 ID max 255、`sourceItemId` 货源 ID max 255）。
响应 `data`：`moveCollectDetailList[]{subDetailList[]` SKU 对应产品发布详情（传统模式：`platformItemId` 对应站点产品 ID、`site` 对应站点，`siteName` 对应站点别名，`status` 发布状态，`reason` 发布失败原因，`gmtCreate`/`gmtModified`）、`skuSubDetailList[]` SKU 对应产品发布详情（UP 模式：`cbtItemId` CBT 产品 ID、`platformItemId` 对应站点产品 ID、`site` 对应站点，`siteName` 对应站点别名，`sku`、`status` 发布状态，`reason` 发布失败原因，`gmtCreate`/`gmtModified`）；其余 24 个字段同 #101}；`total` 总数。

**#114 采集箱：获取类目属性规则** `POST /open/v1/product/collect_box/mercadolibre/collect_box/get_category_attribute_rules`
通用 5 项。Body 必填 `cid`（类目 ID）、`shopId`（店铺 ID）。
响应 `data`：`saleAttributeRules[]`/`productAttributeRules[]`/`skuAttributeRules[]` 销售/产品/SKU 属性规则列表（同结构）：`attributeGroupId` 属性组 ID（暂无用）、`attributeGroupName` 属性组名称（暂无用）、`displayName` 属性显示名称，`hierarchy` 层级（枚举：CHILD_DEPENDENT 子属性、PARENT_PK 必填主属性、FAMILY 选填主属性、ITEM 前台展示属性）、`id` 属性 ID、`name` 属性英文名称（如 "Color"）、`relevance` 属性权重（1 核心属性、2 次级属性，3 选填属性）、`tags<string>` 标签映射（hidden / readOnly / multivalued / allowVariations / definesPicture / required / catalogRequired / gridFilter）、`valueType` 属性类型（list 列表类型、string 字符串类型、grid_id 尺码表网格 id、boolean 布尔类型）、`values[]{id` 选项 id、`displayName` 选项显示名称，`name` 选项英文名称，`metadata<string>` 属性值规则（rgb 颜色 RGB 值、parentId 父属性值 ID、value 布尔值）} 可选值列表（从中选取 name）。

**#115 采集箱：获取类目配置** `POST /open/v1/product/collect_box/mercadolibre/collect_box/get_category_setting`
通用 5 项。Body 必填 `cid`（类目 ID）、`shopId`（店铺 ID）。
响应 `data`：`catalogDomain` 类目 domain；`maxDescriptionLength` 类目最大描述长度；`maxTitleLength` 类目最大标题长度。

**#116 采集箱：获取尺码表 domain 列表** `POST /open/v1/product/collect_box/mercadolibre/collect_box/get_size_chart_domain_list`
通用 5 项。Body：`shopId` 店铺 ID。
响应 `data`：`domains[]{domainId` domain ID、`domainName` domain 英文名称，`domainZhName` domain 中文名称} domain 列表。

**#117 采集箱：获取尺码表表头和主属性信息** `POST /open/v1/product/collect_box/mercadolibre/collect_box/get_size_chart_attribute_info`
通用 5 项。Body 必填 `domainId`（尺码表 domain ID，对应 getSizeChartDomainList 返回的 domainId）、`genderId`（1. 类目属性中的性别 ID（getSiteCollectItemInfo 中 attributes→GENDER 属性 values 中的 name 值；2. 在获取类目属性规则接口返回数据的 productAttributeRules 中对应 GENDER 属性规则 values 值的 id）。
响应 `data`：`mainAttributeList` 主属性列表，格式 `{MANUFACTURER_SIZE:{name:"Manufacturer size",nameZh:"自定义尺码",unit:"US"}}`，value=（`name` 表头英文名称，`nameZh` 表头中文名称，`unit` 表头单位）；`measureTypeList` 测量属性列表，格式 `{BODY_MEASURE:{name:"With body measurements",nameZh:"身体尺寸",relevanceRequired:["FILTRABLE_SIZE","CHEST_CIRCUMFERENCE_FROM"],unit:"US"}}`，value=（`name`/`nameZh`/`unit`、`relevanceRequired[]` 关联必填属性）；`isTopsAndBottoms` 是否为上衣或下装。

**#118 采集箱：获取尺码表所需填写属性信息** `POST /open/v1/product/collect_box/mercadolibre/collect_box/get_size_chart_need_attribute_info`
通用 5 项。Body 必填 `domainId`（domain ID，对应 getSizeChartDomainList 返回的 domainId）、`genderId`（同 #117）、`measureType`（测量类型，对应 getSizeChartAttributeInfo 返回的 measureTypeList key）。
响应 `data`：`sizeChartIdAndInfoMap` 尺码 ID 和尺码内容映射，value=（`name` 尺码英文名称，`nameZh` 尺码中文名称，`unit` 尺码单位）；`equivalencies[]` 尺码列表（XL、XXL 等）。

**#119 采集箱：获取授权站点和名称映射** `POST /open/v1/product/collect_box/mercadolibre/collect_box/get_auth_site_and_site_name_map`
通用 5 项。Body 必填 `includeCbt`：`shopId` 店铺 ID；`includeCbt` int 是否包含 CBT 全球站点（1 是、0 否，min 0 max 1）。
响应 `data`：`siteAndSiteNameMap<string>` 站点和站点名称映射，格式：`{"AR":"阿根廷","BR":"巴西"}`。

**#120 采集箱：获取商品基本选项** `POST /open/v1/product/collect_box/mercadolibre/collect_box/get_item_options`
通用 5 项；无 Body。
响应 `data`：`weightUnitOptions[]{key/value}` 重量单位选项（保存到 siteCollectItemInfo.skuMap.weightUnit）；`warrantyTypeOptions[]{key/value}` 保修类型选项（保存到 siteCollectItemInfo.warrantyType、siteCollectItemInfo.warrantyTimeUnit）；`warrantyTimeUnitOptions[]{key/value}` 保修时间单位选项（保存到 siteCollectItemInfo.warrantyTimeUnit）；`lengthUnitOptions[]{key/value}` 包裹尺寸单位选项（保存到 siteCollectItemInfo.skuMap.lengthWidthHeightUnit）；`siteAndSupportListingTypeOptions` 站点和支持产品类型映射，格式：`{"BR":[{"label":"经典（Classic）","value":"gold_special"}]}`，value=（`label` 选项键值，`value` 选项显示文本）。

**#121 采集箱：查询尺码表模板列表** `POST /open/v1/product/collect_box/mercadolibre/collect_box/search_size_chart_template`
通用 5 项。Body 必填 `shopIds`（array<int>，店铺 ID 列表）；`filter`（`domainId` 尺码表 domain ID、`genderId` 类目属性中的性别 ID、`templateName` 模板名称（模糊搜索））；`pageSize` 每页数量（min 10, max 500）；`pageNo` 当前页码（min 1）。
响应 `data`：`sizeChartTemplateList[]{attributes[]{id` 属性 ID、`values[]{id` 属性值 ID、`name` 属性值名称} 属性值列表} 尺码表模板属性列表，`chartId` 平台尺码表 ID、`copySerialNumber` 复制模板序列号，`domainId` 尺码表 domainId、`genderId` 性别 ID、`mainAttributeId` 主属性 ID、`mainAttribute[]{attributes[]{siteId` 站点 ID、`id` 主属性属性 ID} 表头英文名称} 主属性映射，`measureType` 测量类型，`names<string>` 站点 ID 对应名称映射（格式 `{MCO:"renzituo"}`）、`rows[]{attributes[]{id` 行属性 ID、`values[]{name` 行属性值名称，`struct{number` 行属性值名称拆分：数字部分，`unit` 行属性值名称拆分：单位部分}} 行属性值列表} 表头英文名称，`id` 行 ID、`sites[]` 站点 ID 列表}、shopId 店铺 ID、siteId 站点 ID、`templateName` 尺码模板名称，`type` 尺码模板类型} 尺码表列表；`total` 总数。

**#122 采集箱：获取采集箱详情** `POST /open/v1/product/collect_box/mercadolibre/collect_box/get_site_collect_item_info`
通用 5 项。Body 必填 `detailId`（int，采集箱 ID）；`shopId` 店铺 ID（切换店铺的时候调用）；`cid` 新类目 id（切换类目时填写）。
响应 `data`：`saleAttributeRules`/`productAttributeRules`/`skuAttributeRules` 销售/产品/SKU 属性规则列表（结构同 #114）；`siteCollectItemInfo` 站点采集箱数据：`title` 商品标题，`itemNum` 非服饰类货号，`attributes[]{name` 属性名称，`valueType` 属性数据类型，`values[]{name` 属性值名称} 行属性值列表} 商品属性列表（品牌/型号等）、`cateList[]` 类目面包屑列表，`firstSkuKey` 第一个 SKU 的 key（对应 skuMap 中的 key，如 `;0a310071;502c632b;` 中的 `;0a310071;`）、`originPrice` 原始价格，`price` 价格，`cid` 类目 ID、`notes` 商品备注/描述，`notesFull` 商品完整备注/描述，`warrantyType` 保修类型，`warrantyTime` 保修时长，`warrantyTimeUnit` 保修时长单位，`sourceImgUrls[]` 原始图片 URL 列表，`videoUrl` 视频 URL、`sourceAddress` 货源地址，`oriItemNum` 原始货号，`sourceItemMetaInfo` 货源商品元信息（source/sourceNameFw/sourceAddress/sourceAddressFw/sourceItemId/oriItemNum、`maxSkuPrice` 最大 SKU 价格）、`mainImgVideoUrl` 主图视频 URL、`mainImgAppVideoId` 主图 APP 视频 ID、`sourceItemUrl` 货源商品 URL、`collectBoxDetailId` 采集箱明细 ID、`detailId` 明细 ID、`sourceList[]{remark/sourceItemId/source/sourceSite/sourceItemUrl}` 货源列表，`source`/`sourceNameFw`/`sourceAddressFw`/`sourceItemId`/`maxSkuPrice` 同上，`mainImgVideoGmtExpire` 主图视频过期时间，`siteAndListingTypeList[]{site` 站点标识，`listingType` 刊登类型} 站点与刊登类型列表，`siteAndTitleList[]{site, title` 站点商品标题} 站点与标题列表，`pricingMode` 售价模式，`shopId` 店铺 ID、`saleAttributes[]{name` 销售属性名称（如 Color、Size）、`values[]{skuKey` SKU 标识 key、`name` 销售属性值名称} 销售属性值列表} 销售属性列表（如颜色/尺码）、`sites[]` 已选择的站点列表，`siteAndPriceMap` 站点价格映射（格式 `{"AR": 5.73, "BR": 200, "CL": 300, "CO": 400, "MX": 500, "MX(Full)": 11.32, "UY": 5.73}` 或 `{}`）、`skuMap` SKU 映射表（key 为 SKU 组合 key 如 `;0a310071;502c632b;`，value 为 SKU 详情：`stock` 库存数量，`itemNum` SKU 货号，`upc` UPC 码，`length`/`width`/`height` 长度/宽度/高度，`lengthWidthHeightUnit` 长宽高单位，`weight` 重量，`weightUnit` 重量单位，`isDelete` 是否删除，`goodsSkuId` 商品 SKU ID、`isSupplierDisable` 是否供应商禁用，`siteAndPriceMap` 站点价格映射，`siteAndListingTypeInfoMap` 站点产品类型信息映射（value=`{listingType` 刊登类型，`site` 站点标识，`siteDisplayName` 站点展示名称}）、`imgUrls[]` SKU 图片 URL 列表，`originPrice` 原始价格，`sizeGridRowId` 尺码表行 ID）、`hasSaveSite` 是否已保存站点，`saveDetailTs` 保存明细时间戳，`hasSavePrice` 是否已保存价格，`site` 站点标识，`registrationType` 注册类型。

**#123 采集箱：创建采集箱商品** `POST /open/v1/product/collect_box/mercadolibre/collect_box/create_collect_box_item`
通用 5 项。Body 必填 `siteCollectItemInfo`（必填 `price,cid,title,warrantyType,warrantyTime,warrantyTimeUnit,shopId,sites,siteAndPriceMap`）：
- `price` 价格；`cid` 类目 ID；`title` 商品标题；`notes` 商品备注/描述；`warrantyType` 保修类型（`sellerWarranty` 卖家保修、`factoryWarranty` 工厂保修、`noWarranty` 无保修）；`warrantyTime` 保修时长；`warrantyTimeUnit` 保修时长单位（days 天、years 年、months 月）；`videoUrl` 视频 URL；`sourceList[]{source/sourceItemId/sourceSite/sourceItemUrl}` 货源列表；`detailId` 明细 ID；`firstSkuKey` 第一个 SKU 的 key（对应 skuMap 中的 key）；`siteAndListingTypeList[]{site/listingType}` 站点与刊登类型列表；`siteAndTitleList[]{site/title}` 站点与标题列表；`pricingMode` 售价模式（`sellPrice` 售价、`netProceeds` 净收益）；`shopId` 店铺 ID；`attributes[]{name` 属性名称，`values[]{name` 属性值名称} 属性值列表} 商品属性列表（品牌/型号等）；`saleAttributes[]{name` 销售属性名称（如 Color、Size）、`values[]{skuKey` int SKU 标识 key、`name` 销售属性值名称} 销售属性值列表，`id` 销售属性 ID（如 COLOR、SIZE）} 销售属性列表（如颜色/尺码）；`sites[]` 已选择的站点列表（结构 `["BR","BR(Full)(Up)"]`）；`siteAndPriceMap<number>` 站点价格映射（结构 `{"MX": 100, "AR": 100}`）；`skuMap` SKU 映射表（key 为 SKU 组合 key，value 为 SKU 详情；当类目规则 saleAttributes 不为空时必填）：`length`/`width`/`height`/`weight` 长度/宽度/高度/重量，`lengthWidthHeightUnit`/`weightUnit` 长宽高单位/重量单位，`stock` 库存数量，`imgUrls[]` SKU 图片 URL 列表 [必填]，`itemNum` SKU 货号，`upc` UPC 码，`isDelete` 是否删除，`sizeGridRowId` 尺码表行 ID（从 searchSizeChartTemplate 接口中 sizeChartTemplateList.rows.id 获取）、`originPrice` 原始价格，`siteAndListingTypeInfoMap` 站点产品类型信息映射（value=`{listingType/site/siteDisplayName}`）、`siteAndPriceMap<number>` 站点价格映射，`skuName` SKU 名称，`price` 价格，`siteAndItemMarketplaceMap` 站点商品市场信息映射（value=`{listingType/site/siteDisplayName}`）；`hasSaveSite` 是否已保存站点（1 是；0 否，min 0 max 1）
- 注：cid 用于校验属性规则和模特配置；各枚举字段取值参考 getItemOptions / getCategoryAttributeRules 接口

响应 `data`：`collectBoxDetailId` int 创建成功的采集箱详情 ID。

**#124 采集箱：保存采集箱站点详情** `POST /open/v1/product/collect_box/mercadolibre/collect_box/save_site_collect_item_info`
通用 5 项。Body 必填 `detailId`（int，采集箱详情 ID）、`siteCollectItemInfo`（字段集同 #123，必填同 #123；差异：`saleAttributes[].values[].skuKey` 为 string）。
响应：`SimpleSuccessResponse`。

**#125 采集箱：同步店铺尺码表** `POST /open/v1/product/collect_box/mercadolibre/collect_box/rsync_size_chart_template`
通用 5 项。Body 必填 `shopIds`（array<int>，店铺 ID 列表）。
响应 `data`：`shopIdAndRsyncRet` 店铺 Id 同步结果映射（key 为 shopId，value 为该店铺同步结果：`result` 同步结果（success 表示成功，fail 表示失败）；`reason` 同步失败原因，如果同步成功则为空）。

**#126 采集箱：获取采集箱列表** `POST /open/v1/product/collect_box/mercadolibre/collect_box/search_collect_box_detailList`
通用 5 项。Body 必填 `pageNo`（当前页码，min 1）、`pageSize`（每页数量，min 20, max 500）；`filter`（`status`：`notPublished` 未发布、`timingPublish` 定时发布、`published` 已发布；`filterCidSite` 过滤类目站点（固定值 CBT）；`sourceItemIdKeyword` 货源 ID max 255）。
响应 `data`（单个对象，无 list/total）：`collectBoxDetailId` 采集箱详情 ID、`itemNum` 商品编号，`breadcrumb` 类目面包屑，`cid` 类目 ID、`globalPrice` 全球净收益/售价，`stock` 库存，`price` 货源价格，`thumbnail` 缩略图，`gmtCreate` 创建时间，`editModel` 编辑模式，`commonCollectBoxDetailId`/`appAccountId`/`subAppAccountId`、`platform` 平台，`title` 商品标题，`remark` 备注，`copyType` 复制类型，`collectBoxGroupId` 采集箱分组 ID、`collectBoxDetailShop` 预发布店铺信息（`shopId` 店铺 ID、`pricingMode` 售价模式，`siteAndMaxPriceMap`/`siteAndMinPriceMap`/`siteAndPriceMap<string>` 站点最大/最小/价格映射，`sites[]` 已选择的站点列表（BR(Full)(Up)、BR(Full) 等））。

**#127 采集箱：获取类目列表** `POST /open/v1/product/collect_box/mercadolibre/collect_box/get_category_tree_by_site`
通用 5 项。Body 必填 `site`（美客多站点，固定值 `"CBT"`）。
响应 `data`：`cateTree` 分类树 Map（key=cid）：`cid`/`aid`/`fid` 分类/祖先/父分类 ID、`name` 分类名称（英文）、`nameChinese` 中文、`isLastLevel` 是否末级分类、`disabled` 是否禁用、`children` 子分类 Map（key=cid）。

#### 1.11 AI 公共服务：图片处理

**#128 AI 白底图** `POST /open/v1/product/picture/matting/auto_ai_matting_multi`
通用 5 项。Body 必填 `imgUrls`（array<string>，图片 URL 列表，不计重复）、`imageScene`（int，图片应用场景：1 产品图片、2 描述图片、3 sku 或产品属性图片、4 证书图片、5 尺寸图图片）。
响应 `data`：`imgMattingList[]{result` 单张 AI 白底图结果（success/fail）、`width`/`height` 图片宽度/高度，`md5` 图片 MD5、`newImageUrl` 抠图后图片 URL、`oriImageUrl` 原始图片 URL} AI 白底图结果列表。

**#129 AI 智能消除** `POST /open/v1/product/common/image_removal/remove_image`
通用 5 项。Body 必填 `imageUrls`（array<string>，待消除图片 URL 列表）、`traceInfo`、`removeConfig`：
- `traceInfo` 调用场景信息（必填 `imageRemovalSource`）：`imageRemovalSource` 图片消除业务来源 必传，可选值：`collect_box` 平台采集箱、`collect_box_add` 采集箱创建产品、`common_collect_box` 公共采集箱、`common_collect_box_add` 公共采集箱创建产品、`item` 在线产品、`item_add` 添加产品；`collectBoxDetailId` 平台采集箱 DetailId（imageRemovalSource=collect_box 时必传）；`commonCollectBoxDetailId` 公共采集箱 DetailId（imageRemovalSource=common_collect_box 时必传）；`platform` 平台（平台采集箱和在线产品必传）
- `removeConfig` 消除配置（必填 `isRemoveWatermark,isRemoveLogo,isRemoveText,removeAreas`）：`isRemoveWatermark`/`isRemoveLogo`/`isRemoveText`/`isRemovePsoriasis` int 消除对象（是否去除水印/logo/文字/牛皮藓，0=否，1=是）；`removeAreas[]` 消除区域，可选值 background（背景区域）、subject（主体区域）

响应 `data`：`imageRemovalUrlResultList[]{result` 单张消除结果（success/fail）、`reason` 单张消除失败原因，`oriImageUrl` 原始图片 URL、`newImageUrl` 消除后图片 URL} 消除结果列表；`imageRemovalUseNum` 图片消除使用次数；`appResourceCode` 应用资源编码；`appResourceUseNum` 应用资源使用次数；`freeUseNum` 免费使用次数。

**#130 搜索水印列表** `POST /open/v1/product/item/tiktok/watermark/search_watermark_list`
通用 5 项。Body 必填 `watermarkSubType`（string，水印子类型：`normal` 普通水印、`byLayer` 描述图水印）、`pageNo`（int，当前页码，min 1）、`pageSize`（int，每页数量，min 1）；选填 `watermarkIds`（string，水印 ID 列表，多个以英文逗号分隔）、`watermarkName`（string，水印名称，支持模糊搜索）。
响应 `data`：`watermarkList[]{watermarkId/appAccountId/platform/watermarkImageUrl/watermarkType/watermarkSubType/name}` 水印列表；`total` 总数。

**#131 图片打水印** `POST /open/v1/product/item/tiktok/watermark/watermark_images`
通用 5 项。Body 必填 `imageUrls`（array<string>，需要打水印的图片链接列表）、`watermarkId`（string，用于打水印的水印 ID）、`isAutoMatchImageSize`（boolean，是否自动匹配图片大小：开启则添加水印时自动适配原图尺寸比例，关闭则输出图片尺寸默认为 800×800）；选填 `collectBoxDetailId`（int，采集箱详情 ID，若有就传）。
响应 `data`：`watermarkDetail[]{imageUrl` 原图片 URL、`result` 打水印结果（success 成功；fail 失败）、`watermarkImageUrl` 打完水印后的图片 URL（result 为 success 时有值）、`msg` 失败原因（result 为 fail 时有值）} 打水印结果列表。

**#132 获取支持的翻译语言配置** `POST /open/v1/product/common/translate/get_support_language_config`
通用 5 项；无 Body。
响应 `data`：`supportLanguageConfig` object 支持的语言配置，结构为 `{平台: {类型: {源语言: [目标语言列表]}}}`。平台可选值：`aeAi` / `tosoIot` / `ykt`；类型可选值：`realTime`（实时翻译）/ `idle`（闲时翻译）；源语言和目标语言为语言编码，如 zh、en、ja 等。示例：`{"ali": {"realTime": {"zh": ["en", "ja"], "en": ["zh", "ja"]}}}`。

**#133 图片翻译** `POST /open/v1/product/common/translate/translate_image`
通用 5 项。Body 必填 `imageUrls`（array<string>，待翻译图片 URL 列表）、`sourceLang`（源语言编码，如 zh、en，可选值见 getSupportLanguageConfig 返回的 supportLanguageConfig）、`targetLang`（目标语言编码，可选值同上）、`translatePlatform`（翻译平台：ali / aeAi / tosoIot / ykt，可选值见 getSupportLanguageConfig 返回的 supportLanguageConfig 的键）；选填 `noTranslateImageTextOptions[]` 不翻译的图片文字选项，可选值：`textInTheProduct`（不翻译产品文案）、`brand`（不翻译品牌），不传则都翻译。
响应 `data`：`translateImageUrlResultList[]{oriImageUrl` 原始图片 URL、`newImageUrl` 翻译后图片 URL、`result` 单张翻译结果（success/fail）} 翻译成功结果列表；`translateImageUrlErrorResultList[]{failImageCount` 失败图片数量，`failImageUrls[]` 失败图片 URL 列表，`reason` 失败原因} 翻译失败结果列表。

#### 1.12 AI 公共服务：AI 润色

**#134 AI 生成产品信息（标题/描述）** `POST /open/v1/product/common/open_ai/generate_product_info`
通用 5 项。Body 必填 `generateTypeList, functionModule, platform, aiName, title, languageName`：
- `generateTypeList[]` 生成类型列表 必传，可选值：`title` 生成标题、`notes` 生成描述
- `functionModule` 功能模块 必传，可选值：`createCollectBox` 手动创建采集箱、`editCollectBox` 编辑采集箱、`createItem` 手动创建在线产品、`editItem` 编辑在线产品
- `functionModuleProductId` 功能模块产品 ID（当 functionModule 为 editCollectBox / editItem 时必传）
- `platform` 平台；`aiName` AI 名称（使用接口 get_ai_name_list 获取的 name）；`title` 原始标题；`originalContent` 原始描述内容（生成描述时使用）；`titleLengthLimit` 标题长度限制；`languageName` 目标语言名称（使用接口 get_language_name_code_map 获取的 code）；`keywordsList[]` 关键词列表；`negativeWordsList[]` 排除词列表；`categoryName` 类目名称；`site` 站点；`cid` 类目 ID；`imageInfoList[]{imageUrl` 图片 URL [必填], `imageSource` 图片来源 可选值：`productImage` 产品图片、`otherImage` 其他图片} 图片信息列表

响应 `data`：`titleResult` 标题生成结果（`result` 结果状态 success/fail、`contents[]` 标题内容列表）；`notesResult` 描述生成结果（`result` 结果状态 success/fail、`contents[]` 描述内容列表）。

**#135 AI 生成支持的语言 map** `POST /open/v1/product/common/open_ai/get_language_name_code_map`
通用 5 项；无 Body。
响应 `data`：`languageNameCodeMap<string>` 语言名称与语言代码的映射，key 为语言名称（如"繁体中文"、"泰语"），value 为语言代码（如 `zh-TW`、`th`）。

**#136 获取支持的 AI 名称列表** `POST /open/v1/product/common/open_ai/get_generate_product_info_support_ai_name_list`
通用 5 项；无 Body。
响应 `data`：`aiNameList[]` 支持的 AI 名称列表，可选值：`deepSeekR1` / `douBao1.6` / `tongYiQianWen`。

**#137 AI 润色销售规格** `POST /open/v1/product/common/open_ai/generate_sku_spec_name`
通用 5 项。Body 必填 `platform`（平台，目前只支持 tiktok）、`aiName`（AI 模型名称，目前只支持 `douBao1.6`）、`functionModule`（功能模块，可选值：createCollectBox / editCollectBox / createItem / editItem）、`skuPropertyList`：
- `title` 原始标题（作为 AI 润色上下文）；`languageName` 目标语言名称（取值见 getLanguageNameCodeMap 接口，默认"当前语言"）；`skuPropertyList[]{attrName` 属性名称（如 Color、规格）、`attrId` 属性 ID（可为空字符串）、`attrValueList[]{attrValueId` 属性值 ID、`attrValue` 属性值名称，`imgUrl` 属性值主图 URL（无图时为空字符串）、`supplementarySkuImageUrls[]` 补充 SKU 图片 URL 列表} 属性值列表} SKU 属性列表；`productId` 产品 ID（functionModule 为 editCollectBox / editItem 时传入）

响应 `data`：`newSkuPropertyList[]` AI 润色后的 SKU 规格列表，格式：`[{"name": "Color", "valueList": ["Red", "Blue"]},...]`；`reasoningContent` AI 思考过程内容（部分 AI 模型返回的推理过程）；`openaiRequestLogId` AI 请求日志 ID（对应历史记录 ID，默认 0）。

#### 1.13 图片空间

**#138 通过图片 URL 上传图片到图片空间** `POST /open/v1/product/picture/picture_space/upload_picture_link`
通用 5 项。Body 必填 `imgUrl`（图片 URL）、`scene`（图片场景：产品 `product`、分销 `distributionGoods`、仓库产品 `stockGoods`）。
响应 `data`：`appPictureId` int 图片空间中的图片 ID（成功时有值）；`picturePath` 上传后的图片 URL（成功时有值）；`width` int 图片宽度（成功时有值）；`height` int 图片高度（成功时有值）；`md5` 图片 MD5（成功时有值）。


### 2. 包裹（13）

#### 2.1 履约：基础管理

**#139 获取当前账号有效的线下物流列表** `POST /open/v1/order/logistics_agent/manage/get_enable_offline_product_list`
通用 5 项。描述：三方物流商以及三方仓。Body（均选填）：`logisticsAgentId` int 物流 id；`opOrderPackageIds` array<int> 包裹 ids。
响应 `{result, code, message, data}`：`data.logisticsAgentAuthConfigOption` object（key=授权 ID），为渠道配置结构：`label` 标签，`agentCode` 物流商代码，`agentName` 物流商名称，`options[]` 渠道信息（`label` 渠道标签，`logisticsAgentAuthId` 物流授权 id、`logisticsAgentProductId` 物流渠道 id、`productCode` 物流渠道编码，`logisticsCompany` 物流公司，`status` 渠道状态，`isEnabled` 是否启用，`isSupportPlatformLastMile` 是否支持尾程平台，`productName` 物流渠道名称，`platformLogisticsProductMap` 平台渠道映射表（`platform` 支持的平台，`productKeyword[]` 对应线上物流渠道，`printWaybillType` 面单打印设置（firstMile 头程面单 / lastMile 尾程面单））、`toLogisticsAgentProductInfo` 渠道配置，`value` 映射尾程配置 id）、`logisticsAgentWarehouseName` 仓库 id、`logisticsAgentWarehouseId` 仓库名称，`type` 类型（`logisticsAgent` 物流商物流渠道、`thirdWarehouse` 三方仓物流渠道、`supplier` 供应商渠道、`selfWarehouse` 自营仓渠道）。

**#140 获取当前包裹有效的线上物流列表** `POST /open/v1/order/logistics_agent/manage/get_enable_online_product_list`
通用 5 项。描述：在线发货以及拼接物流。Body 必填 `opOrderPackageId`（int，包裹 id）、`logisticsAgentAuthId`（int，物流授权 id）、`agentCode`（string，物流商编码）；选填 `weight`（string，重量，小数点后两位）、`length` 长、`width` 宽、`height` 高、`weightUnit` 重量单位（枚举 g、mg、kg、oz、lbs）、`dimensionUnit` 尺寸单位（枚举 cm、in、mm、m、ft）、`signatureOnDelivery` boolean 运输签名（temu 专属）、`warehouseId` string 仓库 id。
响应 200：`{result, code, message, data: array<{logisticsAgentAuthConfigOption: {label` 渠道标签，`agentCode` 物流渠道编码，`agentName` 物流商名称，`options[]` 物流渠道数据（`label` 物流渠道编码，`logisticsAgentAuthId` 物流授权 id、`logisticsAgentProductId` 物流渠道 id、`productCode` 物流渠道 code、`logisticsCompany` 物流公司，`status` 渠道状态，`isEnabled` 是否启用，`isSupportPlatformLastMile` 是否支持尾程平台，`agentCode` 物流渠道编码，`productName` 物流渠道名称，`estimatedInfo` 物流预估费用（`fee` 物流费用，`currency` 物流费用货币单位，`estimatedDayStr` 预估履约时间段，`estimatedDayUnit` 预估履约时间单位，`signServiceName`/`signServiceId` 签名服务名称/id（temu 专属）、`estimatedMinDayStr`/`estimatedMaxDayStr` 预估履约时间最小/最大值，`preRequestId` 与下单请求 id（shein 专属）、`aplLevelCode`/`aplLevelName`/`aplLevelRank` 线路等级 Code/名称/排序（速卖通 专属）、`aplDeliveryTag`/`aplDeliveryName`/`aplDeliveryRank` 线路标签 Code/名称/排序（速卖通 专属））}、`type` 物流渠道类型（`logisticsAgent` 物流商物流渠道、`thirdWarehouse` 三方仓物流渠道、`supplier` 供应商渠道、`selfWarehouse` 自营仓渠道）、`logisticsAgentAuthIdAndLastMileOptionInfoMap[]` 拼接渠道数据（`label`/`agentCode`/`agentName`、`options[]` 开启的渠道数据（同上 + `platformLogisticsProductMap` 渠道配置（key=平台，如 pddkjChoice：`platform` 支持的平台，`productKeyword[]` 对应线上物流渠道，`printWaybillType` 面单打印设置（firstMile 头程面单、lastMile 尾程面单））、`lastMilePlatforms[]` 尾程支持平台，`estimatedInfo` 渠道测算信息（同上）、`lastMileLogisticsAgentAuthConfigId` 尾程授权配置 id）、`type` 物流类型）}}>}。

#### 2.2 售后

**#141 获取退货退款列表** `POST /open/v1/order/after_sales/fetch/order_return_list`
通用 5 项。Body（均选填）：`gmtStartFrom` 售后/订单起始时间；`gmtStartTo` 售后/订单结束时间；`platformReturnSns` 平台售后单号；`platformOrderSns` 平台订单号；`platform` 平台；`page` 页码（min 1）；`pageSize` 每页数量（min 1, max 50）。示例：`gmtStartFrom` '2025-04-27 14:49:20'，`gmtStartTo` '2025-04-27 14:49:24'，`platform` shopee，`page` 1，`pageSize` 20。
响应 200 成功：`{result, code, data: {returnList[]` 退货退款单列表（`opOrderReturnId` 售后单 ID、`opOrderId` 订单 ID、`platformReturnSn` 平台售后单号，`platformOrderSn` 平台订单号，`shopId` 店铺 ID、`shopName` 店铺名称，`shopNickName` 店铺自定义名称，`platform` 平台，`site` 站点，`siteName` 站点名称，`status` 售后状态，`platformReturnStatus` 平台售后状态，`appReturnStatusText` 妙手售后状态文案，`reverseType` 售后类型，`textReason` 售后/退货原因文案（原文）、`textReasonCn` 售后/退货原因文案（中文）、`refundAmount` 退款金额，`currency` 币种，`returnTrackingNo` 退回运单号，`returnLogisticsCompany` 退货物流商，`needsLogistics` 是否需要退回物流，`gmtCreateTime` 售后时间，`gmtDueDate` 最晚处理时间，`items[]` 商品列表（`title` 商品标题，`picUrl` 商品图片 URL、`platformOuterSkuId` 平台 SKU、`platformSkuId` 平台 SKUID、`quantity` 数量）、`consigneeInfo` 退货人信息（`opOrderId` 订单 ID、`name` 收件人姓名，`katakana` 收件人假名/日语假名，`phone` 主电话，`phone1`/`phone2` 备用电话 1/2、`email` 邮箱，`company` 公司名称，`country` 国家二字码，`countryName` 国家名称，`state` 省/州，`city` 城市，`district` 区，`town` 镇/街道，`houseNumber` 门牌号，`zipcode` 邮编，`address` 简化地址，`address1`/`address2`/`address3` 详细地址 1/2/3、`fullAddress` 完整地址，`customsClearanceCode` 清关编码））、`total` 总数，`page` 当前页码，`pageSize` 每页数量}}；500 → `SimpleErrorResponse`。

**#142 获取取消订单列表** `POST /open/v1/order/after_sales/fetch/order_cancel_list`
通用 5 项。Body（均选填）：`platformOrderSns` 平台订单号；`platform` 平台；`gmtStartFrom` 售后起始时间；`gmtStartTo` 售后结束时间；`page` 页码（min 1）；`pageSize` 每页数量（min 1, max 50）。示例：`platform` tiktok，`gmtStartFrom` '2026-06-24 16:58:32'，`gmtStartTo` '2026-06-24 16:58:35'，`page` 1，`pageSize` 20。
响应 200 成功：`{result, code, data: {cancelList[]` 取消订单列表（`platformOrderSn` 平台订单号，`shopId` 店铺 ID、`shopName` 店铺名称，`platform` 平台，`platformName` 平台名称，`site` 站点，`siteName` 站点名称，`textReason` 取消原因（原文）、`textReasonCn` 取消原因（中文）、`appReturnStatusText` 妙手取消状态文案，`appOrderStatus` 订单状态，`reverseTypeText` 售后类型文案，`gmtCreateTime` 售后时间，`items[]` 商品列表（同 #141 items））、`total` 总数，`page` 当前页码，`pageSize` 每页数量}}；500 → `SimpleErrorResponse`。

#### 2.3 包裹：运单

**#143 申请运单号** `POST /open/v1/order/package/logistics/tracking_no/apply`
通用 5 项。Body 必填 `opOrderPackageId`（int，包裹 ID）。
响应 200：`{result, code, message, data: array<{platformPackageNo` 物流商单号，`headLogisticsNo` 头程物流商跟踪号，`logisticsNo` 物流商跟踪号，`logisticsType` 物流类型，`headLogisticsNoCompany` 头程物流商公司}>}`。

**#144 设置包裹物流** `POST /open/v1/order/package/logistics/tracking_no/save_logistics_agent_product`
通用 5 项。Body 必填：
- `opOrderPackageIds` array<int> 包裹 IDs（item 描述：opOrderPackageId 订单包裹 ID）
- `logisticsAgentAuthConfigId` int 授权物流配置 ID
- `type` string 物流类型（`logisticsAgent` 物流商，`thirdWarehouse` 三方仓物流）
- `packageWeightAndDimension` object 包裹尺寸数据。描述示例：`{"1044122969":{"length":1,"width":1,"height":1,"dimensionUnit":"in","weight":1,"weightUnit":"lb","isSavePackageWeightAndDimension":0}}`
- 选填：`logisticsAgentWarehouseChannelConfigId` int 三方仓物流渠道配置 ID（type=thirdWarehouse 时必填）；`aliexpressDomesticLogisticsCompanyName` string 速卖通国内物流公司；`aliexpressDomesticLogisticsCompanyId` int 速卖通国内物流公司 ID；`aliexpressDomesticTrackingNo` string 速卖通国内物流单号；`warehouseId` int 发货仓库（暂时只对 temu 在线物流生效）；`partItemRelationSupplierGoodsProcessType` string 部分商品关联了分销商品时候处理方式（`skipPackage` 跳过整个包裹，`skipNotRelationItem` 跳过没关联的商品）；`isShipLater` string 是否延迟发货（暂时只对 temu 在线物流生效）

响应 200：`{result, code, message, data: array<{successCount` string、`failCount` string、`errors` 订单错误对象（`errMsg` 错误描述，`errCode` 错误 code、`opOrderPackageId` 妙手包裹 id、`opOrderId` 妙手订单 id、`platformOrderSn` 妙手订单编号，`platformPackageId` 平台包裹 id、`appPackageNo` 包裹号，`logisticsNo` 跟踪号，`logisticsCompany` 物流公司，`logisticsAgentAuthId` 授权 id、`logisticsAgentProductId` 物流渠道 id、`logisticsAgentId` 物流 id、`gentName` 物流名称）}>}`。

**#145 获取包裹物流轨迹** `POST /open/v1/order/package/logistics/tracking/get_tracking_list`
通用 5 项。Body 必填 `opOrderPackageId`（int，订单包裹 ID，示例 1567020375）。
响应 200 成功：`{result, code, data: {trackingInfoList[]` 物流轨迹列表（`description` 物流轨迹明细，`descriptionCn` 物流轨迹明细（中文）、`gmtCreate` 时间）}}；500 → `SimpleErrorResponse`。

**#146 获取运单面单** `POST /open/v1/order/package/logistics/waybill/get_waybill`
通用 5 项。Body 必填 `opOrderPackageId`（string，包裹 id，示例 43717）。
响应 200：`{result, code, message, data: array<{waybillUrlInfo` 成功数据（`platformOrderSn` 平台单号，`platformPackageId` 平台包裹 id、`url` 面单 url）、`error` 订单错误对象（同 #144）}>}`。

#### 2.4 包裹：基础信息修改

**#147 保存包裹本地备注** `POST /open/v1/order/package/base_info_modify/saveOrderPackageAppNote`
通用 5 项。Body 必填 `opOrderPackageId`（int，包裹 id）、`appNote`（string，本地备注内容）、`isRsyncToForwarder`（int，是否同步到货代，1 是、0 否）。
响应 200：`{result, code, message, data: array<string>}`。

**#148 保存包裹商家备注** `POST /open/v1/order/package/base_info_modify/saveSellerNote`
通用 5 项。Body 必填 `opOrderIds`（array<string>，订单 id；item 描述：opOrderId）、`sellerNote`（string，备注内容）、`isCoverOriginalSellerNote`（int，是否覆盖原始卖家备注，1 是、0 否）。
响应 200：`{result, code, message, data: array<{sellerNoteMap` array<string>（orderId-note 的 map）、`successCount` string、`failCount` string、`failResultMap` object（orderId-note 的 map）}>}`。

#### 2.5 包裹：获取包裹

**#149 获取包裹详情** `POST /open/v1/order/package/fetch/get_package_info`
通用 5 项。Body 必填 `opOrderPackageId`（int，包裹 id，示例 43717）。
响应 200：`{result, code, message, data: array<{orderPackageInfo: {platform` 平台（mock tiktok）、`platformName` 平台名称（mock tiktok）、`site` 站点（mock MX）、`siteName` 站点名称（mock 墨西哥）、`shopId` int 店铺 id、`shopNick` 店铺昵称，`shopName` 店铺名称，`orderInfo` 包裹信息（`opOrderId` 订单 id、`shopId` 店铺 id、`platform` 平台，`platformOrderSn` 平台号，`platformOrderStatus` 订单平台状态，`site` 站点，`currency` 货币单位，`productAmount` 产品金额，`orderAmount` 订单金额，`estimatedShippingFee` 预估运费费用，`commissionFee` 平台佣金，`escrowAmount` 预估回款金额，`payAmount` 支付金额，`actualShippingCost` 实际运费，`discountAmount` 折扣金额，`paymentMethod` 支付方式，`gmtOrderStart` 妙手包裹创建时间，`gmtOrderModified` 妙手包裹修改时间，`gmtPay` 支付时间，`gmtLastDelivery` 最迟发货时间，`gmtDelivery` 发货时间，`gmtRefund` 取消时间，`gmtSettlement` 结算时间，`isCod` 是否货到付款，`gmtFinish` 完结时间，`appOrderStatus` 妙手平台包裹状态，`appNote` 本地备注，`appOrderStatusText` 妙手平台包裹状态，`platformOrderDetailUrl` 图片，`buyerMessage` 卖家留言，`sellerNote` 商家备注，`exchangeRate` 费率）、`consigneeInfo` 收件人信息（`country` 收件人国家二字码，`countryName` 收件国家名称，`state` 收件人 州/省，`city` 收件人城市）、`items[]` 商品信息（`opOrderItemId` 订单 itemId、`opOrderPackageId` 妙手包裹 id、`opOrderPackageItemId` 订单包裹 item id、`platformOrderItemIndex` 平台商品唯一标识，`platformItemId` 产品 id、`platformSkuId` 平台 skuId、`platformItemNum` 平台主货号，`platformOuterSkuId` 平台对外展示 skuId、`title` 标题，`skuSubName` 规格，`quantity` 数量，`originalPrice` 原始价格，`discountedPrice` 折扣价格，`picUrl` 商品图片）、`giftItems[]` 赠品信息（`opOrderPackageGiftId` 包裹赠品 id、`opOrderPackageId` 妙手包裹 id、`goodsId` 商品 id、`goodsSkuId` 商品 skuId、`goodsName` 商品标题，`itemNum` 平台主货号，`goodsSkuSubName` 规格，`goodsSkuOuterId` 对外展示 sku、`quantity` 数量，`originalPrice` 原始价格，`discountedPrice` 折扣价格，`picUrl` 图片）、`logisticsAgentProductInfo` 物流信息（`logisticsAgentProductId` 物流渠道 id、`logisticsAgentId` 物流 id、`productCode` 物流渠道编码，`productName` 物流渠道名称，`status` 渠道状态，`logisticsAgentAuthId` 物流授权 id、`logisticsAgentAuthConfigId` 物流授权配置 id、`platformPackageNo` 物流运单包裹号，`logisticsNo` 物流跟踪号，`logisticsCompany` 物流公司，`extInfo` 物流拓展信息，`shippingFee` 费用，`shippingFeeCurrency` 费用货币，`warehouseName` 仓库名称）、`opOrderPackageToPlatformLastMile` 尾程物流信息（物流信息字段 + `combineProductName` 拼接渠道）、`appPackageNo` 包裹号，`platformPackageStatus` 平台包裹状态，`appPackageStatus` 妙手包裹状态，`appPackageStatusText` 妙手包裹状态描述，`applyTrackingNoFailReason` 申请运单失败原因，`applyTrackingNoFailCode` 申请运单失败编码，`fulfillmentType` 履约类型（`platformFulfillment` 平台仓 / `sellerFulfillment` 卖家自发货 / `platformLogisticsFulfillment` 平台物流；mock sellerFulfillment）、`logisticsNo` 跟踪号}}>}。

**#150 批量获取包裹列表** `POST /open/v1/order/package/fetch/search_package_list`
通用 5 项。Body 必填 `page`（int，页数）、`pageSize`（int，数量）；选填：
- `gmtModifiedTo` string 妙手修改时间-结束；`gmtModifiedFrom` string 妙手修改时间-开始
- `gmtCreateTo` string 妙手创建时间-结束；`gmtCreateFrom` string 妙手创建时间-开始
- `platformOrderSns` string 订单号（多个逗号分割）
- `appPackageStatus` string 包裹状态：`unpaid` 未付款、`wait_confirmed` 待审核、`wait_seller_send` 待发货、`wait_receiver_confirm` 已发货、`finished` 已完成、`cancelled` 未发货退款已关闭、`returned` 已发货退款已退款、`refunding` 售后中
- `shopIds` array<string> 店铺 ids（item 描述：shopId）；`platform` string 平台
- `appPackageTab` string 妙手包裹 tab（顶层 tab）：`waitAudit` 待审核、`waitProcess` 待处理、`waitShip` 待打单发货、`submitPlatform` 交运平台、`waitReceiverConfirm` 已发货、`isolation` 搁置、`problem` 问题件、`closed` 平台售后、`distributeOrder` 分销订单
- 示例：page 1, pageSize 10

响应 200：`{result, code, message, data: array<{orderPackageList[]: {opOrderPackageId` string 妙手包裹 id + #149 全部字段（`items` 另含 `originalPicUrl` 商品原图）}}>}`。

#### 2.6 包裹：发货

**#151 包裹发货** `POST /open/v1/order/package/ship_package/ship_packages`
通用 5 项。Body 必填 `opOrderPackageIds`（array<int>，包裹 IDs；item 描述：opOrderPackageId 订单包裹 ID）、`isVirtualShipment`（int，是否虚拟发货）、`tiktokLocalShopShipType`（string，tiktok 本土订单发货类型：枚举值 1、2；1 = pick-up，2 = drop-off）。
响应 200：`{result, code, message, data: {successOpOrderPackageIds` string、`successCount` string、`failCount` string、`shipFailErrors` array<订单错误对象（同 #144）>}}。


### 3. 采购（17）

#### 3.1 采购单

**#152 添加采购单** `POST /open/v1/ewm/goods_purchase_order/goods_purchase_order/operate/add_goods_purchase_order`
通用 5 项。Body 必填 `supplierId, warehouseId, warehouseType, goodsShareFeeType, goodsSkuList, saveOption`：
- `supplierId` string 供应商 ID；`warehouseId` string 仓库 ID；`warehouseType` string 仓库类型（`self` 自营仓、`forwarder` 货代仓库）
- `goodsShareFeeType` string 费用分摊方式：1 数量、2 金额、3 重量
- `goodsSkuList` array<object> 采购商品列表（item 必填：`goodsSkuId` int 商品 SKU ID、`purchaseNum` int 采购数量、`purchasePrice` string 采购单价；`thirdWarehouseGoodsSkuId` string 映射的三方仓商品 SKU ID，仓库类型为 forwarder 时必填）
- `saveOption` string 存选项（`save` 保存、`submitAudit` 提交审核、`passAudit` 提交并通过审核）
- 选填：`thirdWarehouseProviderAuthId` string 三方仓授权 id（仓库类型为 forwarder 时必填）；`gmtPredictArrival` string 预计到货时间；`accountNote` string 采购备注；`otherFee` string；`shippingFee` string 其他费用

响应 200 成功：`{result, code, data: {goodsPurchaseOrderInternalSn` string 采购单号}}；500 → `SimpleErrorResponse`。

**#153 创建 1688 采购单** `POST /open/v1/ewm/goods_purchase_order/goods_purchase_order/operate/batch_add1688_goods_purchase_order`
通用 5 项。Body 必填 `goodsPurchaseOrderList`（array，采购单列表，可批量，minItems 1）、`saveOption`（string 保存选项：`save` 保存到草稿箱，`create1688Order` 保存并下单）。
- item 必填：`resellerAccountId` string 1688 采购账号 ID、`supplierId` string 供应商 ID、`warehouseId` string 收货仓库 ID、`warehouseType` string 仓库类型（`self` 自营仓、`forwarder` 货代仓库）、`goodsShareFeeType` string 费用均摊方式：'1'（按数量）/ '2'（按金额）/ '3'（按重量）、`flow` string 下单方式：`general` 批发、`fenxiao` 代发、`consigneeInfo` object 收货地址信息（必填 `province` 省，`city` 市，`fullname` 全名，`mobile` 手机，`address` 地址；选填 `county` 区，`town` 镇）、`goodsSkuList` array<object> 商品列表信息（item 必填：`goodsSkuId` int 商品 SKU ID、`purchaseNum` int 采购数量、`purchasePrice` string 采购单价；选填 `sourceItemId` string 1688 商品 ID、`sourceSkuId` string 1688 SKU ID、`sourceSpecId` string 1688 规格 ID、`sourceImgUrl` string 1688 商品图片 URL、`sourceSkuSubName` string 1688 SKU 规格名称，`sourcePrice` string 1688 价格，`sourceTitle` string 1688 商品标题，`sourceProductUrl` string 1688 商品链接，`sourcePurchaseUrl` string 1688 采购链接（同 productUrl）、`thirdWarehouseGoodsSkuId` string 映射的三方仓商品 SKU ID，仓库类型为 forwarder 时必填）
- item 选填：`thirdWarehouseProviderAuthId` string 三方仓授权 id（仓库类型为 forwarder 时必填）、`shippingFee` string 采购运费，`otherFee` string 其他费用，`discountFee` string 优惠金额，`gmtPredictArrival` string 预计到货日期，`accountNote` string 采购备注，`buyerRemark` string 买家留言（1688 下单用）

响应 200 成功：`{result, code, data: {successDataList` 成功数据列表（`index` string 序号，`goodsPurchaseOrderSn` string 采购单号（与 goodsPurchaseOrderInternalSn 含义相同）、`purchaseOrderSn` string 1688 单号，`goodsPurchaseOrderId` string 采购单 ID）、`errors` 错误数据列表（`index` string 序号，`errorMsg` string 错误信息，`errorType` string 错误类型，`goodsPurchaseOrderSn` string 采购单号，`purchaseOrderSn` string 1688 单号，`goodsPurchaseOrderId` string 采购单 ID）、`successGoodsPurchaseOrderIds` array<int> 成功的采购订单 ID 列表}}；500 → `SimpleErrorResponse`。

**#154 编辑采购单** `POST /open/v1/ewm/goods_purchase_order/goods_purchase_order/operate/update_goods_purchase_order`
通用 5 项。Body 必填 `goodsPurchaseOrderId`（int，采购单 ID）、`supplierId`（string，供应商 ID）、`warehouseId`（string，仓库 ID）、`warehouseType`（string，仓库类型：`self` 自营仓、`forwarder` 货代仓库）；选填：`thirdWarehouseProviderAuthId` string 三方仓授权 id（仓库类型为 forwarder 时必填）；`gmtPredictArrival` string 预计到货时间；`accountNote` string 采购备注；`goodsShareFeeType` string 费用分摊方式（1 数量、2 金额、3 重量）；`ali1688Payment` string 1688 费用；`totalPurchasePrice` string 总采购价格；`discountFee` string 折扣费用；`otherFee` string 其他费用；`shippingFee` string；`goodsSkuList` array<object> 采购商品列表（item：`goodsPurchaseOrderSkuId` int 采购单 SKU 记录 ID（编辑时有值）、`goodsSkuId` int 商品 SKU ID [必填]、`purchaseNum` int 采购数量 [必填]、`purchasePrice` string 采购单价 [必填]、`sourceItemId` string 1688 商品 ID、`sourceSkuId` string 1688 SKU ID、`sourceSpecId` string 1688 规格 ID、`sourceImgUrl` string 1688 商品图片 URL、`sourceSkuSubName` string 1688 SKU 规格名称，`sourcePrice` string 1688 价格，`sourceTitle` string 1688 商品标题，`sourceProductUrl` string 1688 商品链接，`sourcePurchaseUrl` string 1688 采购链接（同 productUrl）、`thirdWarehouseGoodsSkuId` string 映射的三方仓商品 SKU ID，仓库类型为 forwarder 时必填 [必填]）；`saveOption` string 存选项（`save` 保存、`submitAudit` 提交审核、`passAudit` 提交并通过审核）。
响应 200 成功：`{result, code, data: {goodsPurchaseOrderInternalSn` string 采购单号}}；500 → `SimpleErrorResponse`。

**#155 采购单手动填写运单号** `POST /open/v1/ewm/goods_purchase_order/goods_purchase_order/operate/add_goods_purchase_order_shipping`
通用 5 项。Body 必填 `goodsPurchaseOrderId`（string，采购单 id）；`packageList` array<object> 包裹列表（`logisticsName` string 物流公司，`waybillCode` string 快递单号）。
响应 200 成功：`SimpleSuccessResponse{result, code}`；500 → `SimpleErrorResponse`。

**#156 采购单修改运单信息** `POST /open/v1/ewm/goods_purchase_order/goods_purchase_order/operate/update_goods_purchase_order_shipping`
通用 5 项。Body 必填 `goodsPurchaseOrderId`（string，采购单 id）；选填：`packageList` array<object> 包裹列表（`logisticsName` string 物流公司，`waybillCode` string 快递单号）；`orderShippingId` string 运单信息 id。
响应 200 成功：`SimpleSuccessResponse`；500 → `SimpleErrorResponse`。

**#157 采购单更新平台运单信息** `POST /open/v1/ewm/goods_purchase_order/goods_purchase_order/operate/update_goods_purchase_order_outer_shipping`
通用 5 项。Body 必填 `goodsPurchaseOrderId`（string，采购单 ID）、`purchaseOrderInfo`（object 采购单信息：`purchasePlatform` string 下单平台，`purchaseOrderSn` string 货源单号，`purchaseOrderBuyer` string 买家帐号，`purchaseOrderSeller` string 卖家帐号，`purchaseOrderPackages` array 包裹信息（object：`purchaseOrderLogisticsName` string 物流公司，`purchaseOrderWaybillCode` string 快递单号））；选填 `shippingId` string 运单 ID。
响应 200 成功：`SimpleSuccessResponse`；500 → `SimpleErrorResponse`。

**#158 取消采购单** `POST /open/v1/ewm/goods_purchase_order/goods_purchase_order/operate/cancel_goods_purchase_order`
通用 5 项。Body 必填 `goodsPurchaseOrderId`（int，采购单 ID）、`cancelReason`（string，取消原因：`outOfStock` 缺货、`exchangeGoods` 换货、`dontWant` 不想要了、`other` 其他）；选填 `cancelNote` string 备注说明。
响应 200 成功：`SimpleSuccessResponse`；500 → `SimpleErrorResponse`。

**#159 标记采购单结束** `POST /open/v1/ewm/goods_purchase_order/goods_purchase_order/operate/finish_goods_purchase_order`
通用 5 项。Body 必填 `goodsPurchaseOrderId`（int，采购单 ID）。
响应 200 成功：`SimpleSuccessResponse`；500 → `SimpleErrorResponse`。

**#160 通过采购单 id 批量添加 1688 商品采购单** `POST /open/v1/ewm/goods_purchase_order/goods_purchase_order/operate/batch_add1688_goods_purchase_order_by_goods_purchase_order_ids`
通用 5 项。Body 必填 `goodsPurchaseOrderIds`（array<int>，采购单 IDs）。
响应 200 成功：`{result, code, data: {successDataList` 成功数据列表（`index` string 序号，`goodsPurchaseOrderSn` string 采购单号，`purchaseOrderSn` string 1688 单号，`goodsPurchaseOrderId` string 采购单 ID）、`errors` 错误数据列表（`index` string 序号，`errorMsg` string 错误信息，`errorType` string 错误类型，`goodsPurchaseOrderSn` string 采购单号，`purchaseOrderSn` string 1688 单号，`goodsPurchaseOrderId` string 采购单 ID）、`successGoodsPurchaseOrderIds` array<int> 成功的采购订单 ID 列表}}；500 → `SimpleErrorResponse`。

**#161 获取采购单列表** `POST /open/v1/ewm/goods_purchase_order/goods_purchase_order/fetch/search_goods_purchase_order_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）；选填：
- `goodsSkuOuterIds` string 商品 SKU；`goodsSkuOuterIdsRp` string 商品 SKU 搜索类型：`rss` 前缀、`lss` 后缀、`ss` 模糊、`eq` 精确
- `goodsPurchaseOrderNumValue` string 采购单号/运单号；`goodsPurchaseOrderNumRp` string 采购单号/运单号搜索类型：`rss` 前缀、`lss` 后缀、`ss` 模糊、`eq` 精确
- `waybillCode` string 采购物流单号；`waybillCodeRp` string 采购物流单号搜索类型：`rss` 前缀、`lss` 后缀、`ss` 模糊、`eq` 精确
- `goodsPurchaseOrderSnList` array<string> 货源单号；`goodsPurchaseOrderSnListRp` string 货源单号列表搜索类型（`rss` 前缀、`lss` 后缀、`ss` 模糊、`eq` 精确）
- `gmtCreateStart` string 采购单创建日期开始；`gmtCreateEnd` string 采购单创建日期结束
- `source` string 来源 `1688` / `other`
- `tab` string 订单状态：`inDraft` 草稿箱、`waitAudit` 待审核、`hasSend` 待收货、`finish` 已完成、`cancelAndReturn` 已取消/已退货
- 示例：page 1, pageSize 10

响应 200 成功：`{result, code, data: {goodsPurchaseOrderList[]` 商品采购订单列表（`goodsPurchaseOrderId` int 采购单 ID、`goodsPurchaseOrderInternalSn` string 采购单号，`goodsPurchaseOrderSn` string 1688 货源单号（有值代表已下 1688 单）、`goodsPurchasePlatform` string 采购平台标识 other / 1688、`status` string 订单状态，`goodsPurchaseTotalPrice` string 商品总采购价，`goodsPurchaseOrderAmount` string 订单应付金额，`shippingFee` string 运费，`otherFee` string 其他费用，`goodsPurchaseOrderDiscount` string 折扣金额，`confirmPaymentAmount` string 已付款金额，`applyPaymentAmount` string 已申请付款金额，`goodsPurchaseTotalNum` string 采购总数量，`gmtCreate` string 创建时间，`gmtPredictArrival` string 预计到货时间，`createSubAppAccountName` string 创建人（采购员）姓名，`resellerAccount` string 1688 货源账号，`accountNote` string 备注内容，`auditReason` string 审核不通过原因，`goodsPurchaseOrderSupplier` object 供货商信息（`shopName` 供货商名称，`sellerId` 供货商 ID、`homeUrl` 供货商店铺主页（有值时名称可点击跳转））、`warehouse` object 收货仓库信息（`warehouseName` 收货仓库名称，`fullAddress` 仓库地址，`contactName` 仓库联系人，`contactPhone` 仓库联系电话）、`goodsPurchaseOrderSkuList[]` SKU 明细列表（`goodsPurchaseOrderSkuId` int ID、`goodsSkuId` string 商品 SKU ID、`goodsName` string 商品名称，`goodsSkuSubName` string 规格名称，`goodsSkuOuterId` string 商品 SKU、`logoUrl` string 商品图片，`purchaseNum` string 采购数量，`purchasePrice` string 采购单价，`receiveNum` string 已收货数量（到货量列及到货量汇总用）、`totalPurchasePrice` string SKU 小计金额，`ali1688SkuInfo` object 1688 SKU 信息（1688 采购单专用：`imgUrl` 1688 商品图片，`title` 1688 商品标题，`productUrl` 1688 商品链接，`skuSubName` 1688 规格名称，`quantity` int 1688 侧采购数量（摘要区件数汇总用）））、`shippingList[]` 运单信息列表（`goodsPurchaseOrderShippingId` string 运单 ID、`goodsPurchaseOrderId` string 关联采购单 ID、`platformOrderSn` string 货源单号，`platformOrderStatus` string 平台订单状态，`platformBuyer` string 平台买家账号，`platformOrderStartTime` string 平台下单时间，`platform` string 物流平台标识，`platformName` string 物流平台名称，`purchaseOrderDetailUrl` string 1688 采购订单详情链接，`platformOrderFullAddress` string 平台订单收货地址，`platformOrderOriginStatus` string 1688 订单状态，`platformOrderOriginStatusText` string 平台订单原始状态文案（1688 订单状态展示）、`resellerAccount` string 买家账号，`packageList[]` 快递包裹列表（`goodsPurchaseOrderShippingPackageId` string 包裹 ID、`goodsPurchaseOrderShippingId` string ID、`goodsPurchaseOrderId` string 物流 id、`logisticsName` string 物流公司名称，`waybillCode` string 快递单号，`contactPhone` string 联系手机号））、`financePaymentList[]` 付款申请记录列表（`id` string id、`paymentId` string 申请记录 id、`paymentSn` string 付款申请单号，`paymentAmount` string 申请付款金额，`status` string 付款申请状态，`statusText` string 付款申请状态文案）、`fianceReceiptList[]` 退款收款记录列表（`id` string id、`receiptSn` string 收款单号，`receiptAmount` string 收款金额，`statusText` string 收款状态文案）、`goodsPurchaseOrderModifyList[]` 变更单记录列表（`goodsPurchaseOrderModifyId` string 变更单 ID、`goodsPurchaseOrderModifySn` string 变更单编号，`status` string 变更单状态，`statusText` string 变更单状态文案））、`total` int 总计}}；500 → `SimpleErrorResponse`。

**#162 签收记录列表** `POST /open/v1/ewm/goods_purchase_order/goods_purchase_order_receive/fetch/search_goods_purchase_order_receive_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）；选填 `goodsSkuOuterIds` / `goodsSkuOuterIdsRp` / `goodsPurchaseOrderNumValue` / `goodsPurchaseOrderNumRp` / `waybillCode` / `waybillCodeRp` / `goodsPurchaseOrderSnList` / `goodsPurchaseOrderSnListRp` / `gmtCreateStart` / `gmtCreateEnd` / `source` / `tab`（同 #161）；`goodsSupplierId` int 供应商 ID；`warehouseId` array<int> 收货仓库 ID。
响应 200 成功：`{result, code, data: {purchaseOrderReceiveList[]` 商品采购订单收货列表（`goodsPurchaseOrderId` string 采购单 id、`goodsPurchaseOrderInternalSn` string 采购单号，`createSubAppAccountName` string 创建人账号姓名，`gmtCreate` string 创建时间，`gmtModified` string 更新时间，`receiveInfo` object 签收明细（`goodsPurchaseOrderReceiveId` string 签收记录 id、`createSubAppAccountName` string 签收人姓名（子账号时展示）、`gmtCreate` string 创建时间，`gmtReceive` string 签收时间，`skuList[]` 签收 sku 列表（`goodsPurchaseOrderReceiveSkuId` string ID、`currentReceiveNum` string 本次签收数量，`warehouseShelfCellId` string 签收仓位 id、`goodsSkuId` string sku id、`orderSkuInfo` object sku 信息（`goodsPurchaseOrderId` string 采购单 id、`goodsId` string 商品 id、`goodsSkuId` string 商品 sku id、`goodsSkuOuterId` string 商品 sku、`purchaseNum` string 采购数量，`receiveNum` string 总签收数量）））、`goodsPurchaseOrderSupplier` object 供应商（`shopName` 供货商名称，`sellerId` 供货商 ID、`homeUrl` 供货商店铺主页（有值时名称可点击跳转））、`shippingList[]` 运单列表（同 #161 shippingList）、`warehouse` object 仓库（`warehouseName` 收货仓库名称，`fullAddress` 仓库地址，`contactName` 仓库联系人，`contactPhone` 仓库联系电话））、`total` int 总计}}；500 → `SimpleErrorResponse`。

**#163 获取缺货、备货建议列表** `POST /open/v1/ewm/goods_purchase_order/goods_purchase_suggest/fetch/search_goods_purchase_suggest_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）；选填：`warehouseId` array<int> 仓库 ID；`goodsSupplierId` int 供货商；`type` string 类型（默认备货）：`stockUp` 备货、`outOfStock` 缺货；`source` string other / 1688；`shopIds` array<int> 店铺 id；`goodsCodeValue` string 商品 sku。
响应 200 成功：`{result, code, data: {purchaseSuggestList[]` 商品采购建议列表（`goodsId` int 商品 id、`goodsSkuId` int 商品 sku id、`dailySales` int 日销量，`minTriggerSuggestNum` int 采购下限，`maxPrepareDays` int 最大备货天数，`minPrepareDays` int 最小备货天数，`orderNeedNum` int 订单需求量，`recentSaleNumDt7` int 近 7 天销量，`recentSaleNumDt30` int 近 30 天销量，`suggestNum` int 建议数量，`safeStockNum` int 安全库存）、`total` int 总计}}；500 → `SimpleErrorResponse`。

#### 3.2 供应商

**#164 获取供应商列表** `POST /open/v1/ewm/supplier/fetch/search_supplier_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）；选填：`source` string 供应商类型；`settlementMethod` string 结算方式（`payBeforeDelivery`、`payOnDelivery`、`payPeriod`、`payWeek`、`payHalfMonth`、`payMonth`、`installment`）；`goodsSupplierId` int 供应商 id；`paymentMethod` string 支付方式（`bank` 银行转账、`thirdPay` 第三方支付（支付宝等））。
响应 200 成功：`{result, code, data: {supplierList[]` 供应商列表（`goodsSupplierId` string 供应商 ID、`source` string 供应商类型 code、`shopName` string 供应商名称，`homeUrl` string 主页 url、`purchaseUrl` string 采购网址，`address` string 详细地址，`arrivalDays` string 到货天数，`accountNote` string 账户备注，`contactName` string 联系人姓名，`contactPhone` string 联系人电话，`companyPhone` string 公司电话，`wangwang` string 淘宝旺旺，`email` string 邮箱，`qq` string QQ、`settlementMethod` string 结算方式，`paymentMethod` string 付款方式，`bankName` string 银行名称，`bankCardOwnerName` string 开户名，`bankCardNumber` string 银行卡号，`totalPurchaseOrderNum` string 采购次数，`returnPurchaseGoodsRate` string 退货采购商品率，`exceptionPurchaseOrderRate` string 异常采购订单率，`supplyTime` string 供货时效，`totalPurchaseGoodsNum` string 总采购商品数，`returnPurchaseGoodsNum` string 退货采购商品数，`exceptionPurchaseOrderNum` string 异常采购订单数，`provinceName` string 省名称，`cityName` string 市名称，`countyName` string 区名称，`townName` string 镇名称，`fullAddress` string 完整地址，`sourceName` string 供应商类型名称）、`total` int 总数}}；500 → `SimpleErrorResponse`。

**#165 获取供应商信息** `POST /open/v1/ewm/supplier/fetch/get_supplier_info`
通用 5 项。Body 必填 `goodsSupplierId`（int，供应商 id）。
响应 200 成功：`{result, code, data: {supplierDetail` object 供应商详情（字段同 #164 supplierList 项）}}；500 → `SimpleErrorResponse`。

**#166 获取供应商类型列表** `POST /open/v1/ewm/supplier/fetch/get_supplier_platform_list`
通用 5 项；无请求 Body。
响应 200 成功：`{result, code, data: {supplierPlatformOptions[]: {label` string 供应商类型名称，`value` string 供应商类型 code}}}；500 → `SimpleErrorResponse`。

**#167 修改供应商** `POST /open/v1/ewm/supplier/operate/edit_supplier`
通用 5 项。Body 必填 `goodsSupplierId`（int，供应商 id）、`shopName`（string，供应商名称）；选填：`source` string 供应商类型 code；`homeUrl` string 主页网址；`purchaseUrl` string 采购网址；`arrivalDays` string 到货周期；`accountNote` string 备注；`address` string 地址；`contactName` string 联系人姓名；`contactPhone` string 联系人电话；`companyPhone` string 公司电话；`wangwang` string 网旺号；`email` string 邮箱；`qq` string QQ；`settlementMethod` string 结算方式；`paymentMethod` string 付款方式；`bankName` string 银行名称；`bankCardNumber` string 银行卡号；`bankCardOwnerName` string 开户人姓名。
响应 200 成功：`{result, code, data: {'@api': object（description: POST）}}`；500 → `SimpleErrorResponse`。

**#168 创建供应商** `POST /open/v1/ewm/supplier/operate/add_supplier`
通用 5 项。Body 必填 `shopName`（string，供应商名称）、`source`（string，供应商类型 code）；选填字段同 #167 选填（`homeUrl` 主页网址，`purchaseUrl` 采购网址，`arrivalDays` 到货周期，`accountNote` 备注信息，`address` 地址，`contactName` 联系人姓名，`contactPhone` 联系人电话，`companyPhone` 公司电话，`wangwang` 网旺号，`email` 邮箱，`qq` QQ、`settlementMethod` 结算方式，`paymentMethod` 付款方式，`bankName` 银行名称，`bankCardNumber` 银行账号，`bankCardOwnerName` 开户人姓名）。
响应 200 成功：`{result, code, data: {'@api': object（description: POST）}}`；500 → `SimpleErrorResponse`。


### 4. 仓储（18）

#### 4.1 商品

**#169 获取多规格商品列表** `POST /open/v1/ewm/goods/goods/fetch/search_goods_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）；选填：`goodsSkuOuterIds` array<string> sku（maxItems 100）；`groupId` string 分组 ID；`itemNum` array<string> SPU（maxItems 100）；`keyword` string 商品 sku。
响应 200 成功：`{result, code, data: {goodsList[] {goodsId` string 商品 ID、`goodsGroupId` string 商品分组 ID、`goodsName` string 商品名称，`foreignGoodsName` string 商品英文，`goodsType` string 商品类型，`goodsMode` string 商品模式（single 单品）、`goodsBrandId` string 商品品牌 ID、`units` string 商品单位，`itemNum` string 商品编号，`weight` string 商品重量，`width` string 商品宽度，`height` string 商品高度，`length` string 商品长度，`goodsStatus` string 商品状态（1 在售、2 热销、4 新品、3 滞销、5 清仓、0 停售）、`goodsSaleStatus` string 商品销售状态（0 普通、1 热销、2 滞销）、`isNew` string 是否新品，`isStockEmpty` string 是否库存为空，`marketName` string 市场名称，`staffName` string 档口名称，`invoiceNcm` string 发票 NCM、`icmsOrigem` string 发票-原场地，`invoiceNcmDesc` string 发票 NCM 描述，`gmtCreate` string 创建时间，`gmtModified` string 修改时间，`minGoodsSkuPurchasePrice` string 最小商品 SKU 采购价，`skuList[]` SKU 列表（`goodsSkuId` string 商品 SKU ID、`goodsId` string 商品 ID、`status` string 商品状态，`isInWarehouse` string 是否入库，`goodsSkuOuterId` string 商品 SKU、`goodsSkuSubName` string 规格，`goodsSkuCustomCode` string 商品编码，`goodsSkuCustomBarcode` string 商品条码，`appPictureId` string 图片 ID、`logo` string 图片 URL、`logoOssPath` string 图片 OSS 路径，`purchasePrice` string 单价，`stockNum` string 库存数量，`lockStockNum` string 锁定库存数量，`platformItemId` string 平台 SKU ID、`defaultGoodsSupplierId` string 默认供应商 ID、`weight` string 重量，`width` string 宽度，`height` string 高度，`length` string 长度，`lastPurchasePrice` string 最近一次购买价格，`goodsMode` string 商品模式，`goodsSkuNote` string 商品 SKU 备注，`gmtCreate` string 创建时间，`gmtModified` string 修改时间，`logoUrl` string 图片 URL、`goodsName` string 商品名称，`goodsGroupId` string 商品分组 ID、`goodsStatus` string 商品状态，`foreignGoodsName` string 商品英文名称，`goodsSaleStatus` string 销售状态，`isNew` string 是否新品，`isStockEmpty` string 是否库存为空，`goodsBrandId` string 商品品牌 ID、`units` string 商品单位，`goodsGroupName` string 分组名称，`goodsGroupBreadcrumb` string 分组路径，`supplierList[]` 供应商列表（`goodsSupplierId` string 供应商 id、`shopName` string 供应商名称，`source` string 供应商类型 code、`goodsSupplierGoodsSkuId` string 供应商商品 sku id、`goodsSkuId` string sku id、`isDefault` string 是否默认供应商，`skuSourceUrl` string 货源链接，`gmtCreate` string 创建时间，`gmtModified` string 修改时间，`ali1688ItemSku` object 1688 配对数据（`ali1688ItemSkuId` string ID、`sourceItemId` string 1688 产品 ID、`sourceSpecId` string 1688 规格 id、`sourceSkuId` string 1688 skuID、`imgUrl` string 图片地址，`attributeDisplayName` array<string> 属性显示名称，`attributeValue` array<string> 属性值，`title` string 标题）、`purchaseRate` object 采购比例（本地商品数量：货源下单数量）（`goodsSkuNum` int 采购比例：商品数量，`sourceNum` int 采购比例：货源下单数量））、`goodsAttributeList[]` 商品属性列表（`goodsAttributeId` string ID、`goodsAttributeValueId` string 值 ID、`attributeValue` string 属性值名称，`attributeName` string 规格名称）、`platformOuterSkuIds` array<string> 关联平台 SKU、`platformSkuIds` array<string> 关联的平台 SKU Id、`goodsSkuBundleList[]` 子商品信息（`goodsSkuId` int 商品 skuID、`goodsId` int 商品 ID、`goodsName` string 商品名称，`goodsGroupId` int 分组 id、`appAccountId` int 应用账号 ID、`status` string 商品状态（1 在售、2 热销、4 新品、3 滞销、5 清仓、0 停售）、`goodsSkuOuterId` string 商品 SKU、`goodsSkuSubName` string 规格，`goodsSkuCustomCode` string 商品代码，`goodsSkuCustomBarcode` string 商品条码，`logoOssPath` string 图片地址，`purchasePrice` string 单价，`stockNum` string 库存数量，`lockStockNum` string 预占库存，`platformItemId` string 平台商品 id、`defaultGoodsSupplierId` string 默认供应商 ID、`weight` string 重量，`width` string 宽度，`height` string 高度，`length` string 长度，`lastPurchasePrice` string 最近采购价，`goodsMode` string 商品类型，`goodsSkuNote` string 商品 SKU 备注，`gmtCreate` string 创建时间，`gmtModified` string 修改时间，`quantity` string 数量）、`isExistParentGoodsSku` string 存在父商品，`customsDeclaration` object 报关信息（`productAttrs` array<string> 申报属性（带电 `with_battery`、含非液体化妆品 `aneroid_markup`、特货（敏感货）`special_product`）、`productSubAttrs` object 各申报属性的详细值（`withBattery` string 带电报关属性：`within_battery` 弱电，纯电 `only_battery`）、`productChineseName` string 申报中文名称，`productEnglishName` string 申报英文名称，`productWeight` string 申报重量（g）、`productPrice` string 目的国申报金额（USD）、`exportCountryDeclaredPrice` string 出口国申报金额（USD）、`productMaterial` string 材质，`productPurpose` string 用途，`customCode` string 海关编码）、`isHavePermissions` string 是否有权限）、`goodsGroupName` string 商品分组名称，`goodsGroupBreadcrumb` string 商品分组名称，`goodsPackagingList[]` 商品包装列表（`packagingId` int 包材 id、`packableQuantity` int 包材可包装数量）}}}；500 → `SimpleErrorResponse`。

**#170 获取商品详情** `POST /open/v1/ewm/goods/goods/fetch/get_goods_info`
通用 5 项。Body 必填 `goodsId`（int，商品 id）。
响应 200 成功：`{result, code, data: {goodsDetail` object（结构同 #169 goodsList 项；SKU 级另含 `goodsSkuPackagingList[]{packagingId` int 包材 id、`packableQuantity` int 包材可包装的商品数量}）}}；500 → `SimpleErrorResponse`。

**#171 添加商品** `POST /open/v1/ewm/goods/goods/operate/add_goods`
通用 5 项。Body 必填 `goodsName`（string，商品中文名称，maxLength 500）、`goodsStatus`（string，商品状态：0 停售、1 在售、2 热销、4 新品、3 滞销、5 清仓）、`goodsSkuList`（array<object> SKU 列表）：
- item 必填：`purchasePrice` string 采购单价（参考价格）
- item 选填：`goodsSkuId` int SKU ID（创建时为空，编辑时有值）；`goodsSkuOuterId` string 商品 SKU 编码；`platformOuterSkuIds` array<string> 平台外部 SKU ID 列表；`platformSkuIds` array<string> 平台内部 SKU ID 列表；`skuImgUrl` string SKU 图片 URL；`weight` string 重量（KG）；`width` string 宽度；`height` string 高度；`length` string 长度；`goodsSkuBundleList` array 组合品子商品列表（组合品模式）：object（`goodsSkuOuterId` string 子商品 SKU 编码，`goodsName` string 子商品名称，`goodsSkuSubName` string 子商品规格名称，`logoUrl` string 子商品图片 URL、`quantity` string 组合数量）；`customsDeclaration` object 报关/清关申报信息（`productAttrs` array<string> 申报属性（带电 `with_battery`、含非液体化妆品 `aneroid_markup`、特货（敏感货）`special_product`）、`productSubAttrs` object 各申报属性的详细值（`withBattery` string 带电报关属性：`within_battery` 弱电，纯电 `only_battery`）、`productChineseName` string 申报中文名称，`productEnglishName` string 申报英文名称，`productWeight` string 申报重量（g）、`productPrice` string 目的国申报金额（USD）、`exportCountryDeclaredPrice` string 出口国申报金额（USD）、`productMaterial` string 材质，`productPurpose` string 用途，`customCode` string 海关编码）；`goodsSkuCustomCode` string 商品代码（UPC/ISBN/SN/GTIN）；`goodsSkuNote` string SKU 备注；`goodsSkuPackagingList` array 包材列表（object：`packagingId` int 包材 ID、`packableQuantity` int 该包材可包装的商品数量）
- 选填：`goodsGroupId` int 商品分组 ID、`goodsMode` string 商品模式（single 单品）、`foreignGoodsName` string 商品外文名称，`marketName` string 采购档口，`staffName` string 采购档口，`goodsGroupName` string 商品分组名称，`invoiceNcm` string 巴西发票 NCM 编码，`icmsOrigem` string 巴西 ICMS 原产地编码，`units` string 商品单位，`goodsBrandId` string 商品品牌 ID

响应 200 成功：`{result, code, data: {goodsId` int 商品 id、`goodsSkuIds` int sku id}}；500 → `SimpleErrorResponse`。

**#172 安全库存批量设置** `POST /open/v1/ewm/goods/goods/operate/batch_save_goods_suggest_config`
通用 5 项。Body：`goodsSuggestConfigList` array<object> 商品建议配置列表（item：`goodsSkuId` int 商品 sku id [必填]、`warehouseId` int 仓库 id [必填]、`computeMode` string 计算方式，固定值 `newValue` [必填]、`safeStock` int 安全库存 [必填]、`minTriggerSuggestNum` int 库存下限）。
响应 200 成功：`{result, code, data: {successCnt` int 成功数量}}；500 → `SimpleErrorResponse`。

**#173 修改商品** `POST /open/v1/ewm/goods/goods/operate/edit_goods`
通用 5 项。Body 必填 `goodsId`（int，商品 ID）、`goodsName`（string，商品中文名称）、`goodsStatus`（string，商品状态：0 停售、1 在售、2 热销、4 新品、3 滞销、5 清仓）、`goodsSkuList`（array<object> SKU 列表，item 结构同 #171，必填 `purchasePrice`）；选填同 #171（`goodsGroupId` string 商品分组 ID、`goodsMode`、`foreignGoodsName`、`marketName`、`staffName`、`goodsGroupName`、`invoiceNcm`、`icmsOrigem`、`units`、`goodsBrandId`）。
响应 200 成功：`{result, code, data: {goodsId` int 商品 id、`goodsSkuIds` int sku id}}；500 → `SimpleErrorResponse`。

**#174 商品品牌：获取列表** `POST /open/v1/ewm/goods/goods_brand/fetch/search_goods_brand_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）。
响应 200 成功：`{result, code, data: {brandList[]{goodsBrandId` int 商品品牌 ID、`brandName` string 品牌名称}、`total` int 总计}}；500 → `SimpleErrorResponse`。

**#175 商品分组：获取商品分组列表** `POST /open/v1/ewm/goods/goods_group/fetch/get_goods_group_list`
通用 5 项；无请求 Body。
响应 200 成功：`{result, code, data: {goodsGroupTree[]{goodsGroupId` string 分组 ID、`parentGoodsGroupId` string 父分组 ID、`groupName` string 分组名称，`level` string 级别，`sort` string 排序，`subGroups` array<object> 子分组}}}；500 → `SimpleErrorResponse`。

**#176 商品 SKU：获取商品 SKU 列表** `POST /open/v1/ewm/goods/goods_sku/fetch/search_goods_sku_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）、`goodsMode`（string，商品类型）；选填 `groupId` string 分组 ID；`goodsSkuOuterIds` array<string> 商品 sku（maxItems 100）。
响应 200 成功：`{result, code, data: {goodsSkuList[]` sku 列表（SKU 字段集同 #169，无 goodsPackagingList）、`total` int 总数}}；500 → `SimpleErrorResponse`。

#### 4.2 商品包材

**#177 获取列表** `POST /open/v1/ewm/packaging/fetch/search_packaging_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）。
响应 200 成功：`{result, code, data: {packagingList[]` 包材列表（`packagingId` string ID、`packagingCode` string code、`name` string 包材名称，`price` string 价格，`length` string 长度，`width` string 宽度，`height` string 高度，`weight` string 重量，`remark` string 备注，`gmtCreate` string 创建时间，`gmtModified` string 更新时间）、`total` int 总数}}；500 → `SimpleErrorResponse`。

#### 4.3 数据统计

**#178 销售数据：获取商品销售数据列表** `POST /open/v1/ewm/stat/goods_sale_data/fetch/search_goods_sale_data_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）、`shopIds`（array<int>，店铺 ID 数组）、`gmtStart`（string，开始日期，如 2022-07-01）、`gmtEnd`（string，结束日期，如 2022-07-01）；选填：`warehouseIds` array<int> 仓库 ID 数组；`logisticsAgentWarehouseIds` array<int> 第三方仓库 id；`goodsSkuOuterIds` string 商品 SKU；`goodsSkuOuterIdsRp` string 商品 SKU 编码搜索类型：`rss` 前缀、`lss` 后缀、`ss` 模糊、`eq` 精确；`goodsName` string 商品名称；`goodsNameRp` string 商品名称搜索类型：`rss` 前缀、`lss` 后缀、`ss` 模糊、`eq` 精确、`ass` 多个关键词同时匹配；`goodsSkuCustomCodes` string 商品代码；`goodsSkuCustomCodesRp` string 商品代码搜索类型：`rss` 前缀、`lss` 后缀、`ss` 模糊、`eq` 精确；`foreignGoodsName` string 商品外文名称；`foreignGoodsNameRp` string 商品外文名称搜索类型：`rss` 前缀、`lss` 后缀、`ss` 模糊、`eq` 精确、`ass` 多个关键词同时匹配；`goodsGroupIds` array<int> 商品分组 ID 列表；`shopFilterType` string 店铺类型（`shopId` 按店铺 Id、`group` 按店铺分组拣货单）；`shopGroupIds` array<int> 店铺分组 id。
响应 200 成功：`{result, code, data: {goodsSaleList[] {goodsSkuId` string 商品 sku Id、`orderSaleCount` string 自营仓销售订单量，`goodsSaleCount` string 自营仓销量，`goodsRefundCount` string 退货数量，`goodsSaleAmount` number 销售金额，`goodsCostAmount` number 自营仓商品成本，`goodsRefundAmount` number 退款成本，`orderRefundAmount` number 退款金额，`goodsSkuInfo` object 商品信息（`goodsName` string 商品名称，`goodsMode` string 商品类型，`goodsId` string 商品 id、`goodsSkuId` string 商品 SKUid、`goodsSkuOuterId` string sku、`logoOssPath` string 图片地址，`goodsSkuSubName` string 规格，`goodsSkuCustomCode` string 商品代码，`logoUrl` string 图片 url）、`rank` string 排名，`logisticsAgentGoodsSkuAllSales` object 三方仓销售数据（`logisticsAgentGoodsSkuOrderSaleAmount` number 三方仓销售金额，`logisticsAgentGoodsSkuOrderSaleCount` int 三方仓销售订单量，`logisticsAgentGoodsSkuGoodsSaleCount` int 三方仓销量，`logisticsAgentGoodsSkuGoodsCostAmount` number 三方仓商品成本）、`logisticsAgentGoodsSkuSalesList[]` 三方仓销售数据列表（`logisticsAgentWarehouseId` string 仓库 id、`logisticsAgentGoodsSkuId` string 第三方 sku ID、`goodsSkuId` string 商品 sku ID、`orderSaleAmount` string 订单销售金额，`orderSaleCount` string 商品成本金额，`goodsSaleCount` string 商品销售数量，`goodsCostAmount` string 商品成本金额，`logisticsAgentWarehouseName` string 仓库名称）}、`total` int 总数}}；500 → `SimpleErrorResponse`。

**#179 商品周转分析：获取商品周转数据列表** `POST /open/v1/ewm/stat/goods_turnover_data/fetch/search_goods_turnover_data_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）、`gmtStart`（string，开始日期，如 2022-07-01）、`gmtEnd`（string，结束日期，如 2022-07-01）；选填：`warehouseIds` array<int> 仓库 ID 数组；`goodsSkuOuterIds` string 商品 SKU；`goodsSkuOuterIdsRp` string 商品 SKU 编码搜索类型：`rss` 前缀、`lss` 后缀、`ss` 模糊、`eq` 精确；`goodsName` string 商品名称；`goodsNameRp` string 商品名称搜索类型：`rss` 前缀、`lss` 后缀、`ss` 模糊、`eq` 精确、`ass` 多个关键词同时匹配；`goodsGroupIds` array<int> 商品分组 ID 列表。
响应 200 成功：`{result, code, data: {goodsList[] {rank` string 排名，`turnoverRate` string 周转率（%）、`turnoverDay` string 周转天数（天）、`saleRate` string 动销率（%）、`endDtStockNum` string 期末库存总量，`endDtStockCostAmount` string 期末库存成本，`startDtStockNum` string 期初库存总量，`startDtStockCostAmount` string 期初库存成本，`confirmUseGoodsSkuWarehouseCount` string 销售出库数量，`confirmUseGoodsSkuWarehouseCostAmount` string 销售出库成本，`otherOutStorageCount` string 其他出库数量，`otherOutStorageCostAmount` string 其他出库成本，`allInStorageCount` string 入库数量，`allInStorageCostAmount` string 入库成本，`goodsSkuInfo` object 商品信息（`goodsName` string 商品名称，`goodsMode` string 商品类型，`goodsId` string 商品 id、`goodsSkuId` string 商品 SKUid、`goodsSkuOuterId` string sku、`logoOssPath` string 图片地址，`goodsSkuSubName` string 规格，`goodsSkuCustomCode` string 商品代码，`logoUrl` string 图片 url）}、`total` int 总数}}；500 → `SimpleErrorResponse`。

#### 4.4 库存

**#180 三方仓 SKU 库存：获取三方仓商品库存列表** `POST /open/v1/ewm/storage/third_warehouse/fetch/search_third_goods_sku_warehouse_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）、`type`（string，类型：1 第三方仓库服务商 LogisticsAgent、2 第三方货代仓库服务商 Forwarder、3 FBA 仓库、4 FBT）、`warehouseIds`（array<int>，仓库 Ids）；选填：`thirdWarehouseProviderAgentAuthIds` array<int> 第三方仓库服务商授权主键 ID（选一个）；`thirdWarehouseForwarderProviderAuthIds` array<int> 第三方货代仓库服务商授权主键 ID（选一个）；`thirdWarehouseProviderAuthId` array<int> FBA/FBA 授权 id；`keyword` string 第三方 sku（多个用逗号分隔）；`matchSku` string 商品 sku（映射关系，多个用逗号分隔）。
响应 200 成功：`{result, code, data: {goodsSkuWarehouseList` object 商品 SKU 库存数据（`goodsSkuOuterId` string 第三方 sku、`warehouseName` string 仓库名称，`logisticsAgentWarehouseId` string 第三方仓库 id、`stockNum` string 库存，`availableStockNum` string 可用库存，`lockedStockNum` string 预占库存，`frozenStockNum` string 待上架库存，`onWayStockNum` string 在途库存，`waitSubmitStockNum` string 待提交量，`onPlanNum` string 计划库存，`faultyStockNum` int 次品库存数量，`notForSaleNum` int 不可售数量（平台仓）、`inboundNum` int 入库数量（平台仓）、`reservedNum` int 活动预留数量）、`total` int}}；500 → `SimpleErrorResponse`。

**#181 自营仓库存：获取自营仓商品库存列表** `POST /open/v1/ewm/storage/warehouse/fetch/search_goods_sku_warehouse_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）；选填：`warehouseIds` array<int> 仓库 ids（minItems 1）；`goodsSkuOuterIds` array<string> 商品 sku（minItems 1）。
响应 200 成功：`{result, code, data: {goodsSkuWarehouseList[]` 商品 SKU 库存数据（`goodsSkuWarehouseId` string 仓库 id、`goodsSkuId` string 商品 skuid、`goodsId` string 商品 id、`stockNum` string 总库存，`availableStockNum` string 可用库存，`lockedStockNum` string 预占库存，`onWayNum` string 在途库存，`onPlanNum` string 计划库存）、`total` int}}；500 → `SimpleErrorResponse`。

**#182 自营仓库存：获取商品 SKU 安全库存列表** `POST /open/v1/ewm/storage/warehouse/fetch/get_goods_sku_safe_stock_num_list`
通用 5 项。Body 必填 `goodsSkuOuterIds`（array<string>，商品 sku，minItems 1, maxItems 100）、`warehouseId`（int，仓库 id）。
响应 200 成功：`{result, code, data: {goodsSkuOuterIdAndSafeStockNumMap[]{goodsSkuOuterId` string 商品 SKU、`safeStockNum` int 库存安全数}}}；500 → `SimpleErrorResponse`。

#### 4.5 仓库

**#183 自营仓仓库：获取供应商仓库列表** `POST /open/v1/ewm/warehouse/fetch/supplier_warehouse_list`
通用 5 项；无请求 Body。
响应 200 成功：`{result, code, data: {supplierWarehouseList[]` 供应商仓库列表（`warehouseId` int 仓库 ID、`warehouseName` string 仓库名称）}}；500 → `SimpleErrorResponse`。

**#184 自营仓仓库：获取自营仓仓库列表** `POST /open/v1/ewm/warehouse/fetch/search_warehouse_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）。
响应 200 成功：`{result, code, data: {warehouseList[]{warehouseId` int 仓库 ID、`warehouseName` string 仓库名称，`address` string 地址，`fullAddress` string 详细地址，`isDefault` int 是否默认仓库}、`total` int}}；500 → `SimpleErrorResponse`。

**#185 三方仓仓库：获取三方仓授权列表** `POST /open/v1/ewm/third_warehouse/fetch/search_third_provider_auth_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）。
响应 200 成功：`{result, code, data: {providerAuthList` object 第三方授权列表（`thirdWarehouseProviderAuthId` string 授权 ID、`providerId` string 服务商 ID、`type` string 三方仓类型（`forwarder` 货代；`logisticsAgent` 三方服务商）、`appCustomerId` string 授权 id、`nickname` string 昵称，`status` string 状态，`isPlatformWarehouse` string 是否平台仓库，`providerName` string 服务商名称，`providerCode` string 服务商 Code、`authAgentWarehouseList[]` 授权三方服务商仓库列表（`logisticsAgentWarehouseAuthId` string 仓库授权 id、`logisticsAgentCustomerId` string 服务商授权 Id、`logisticsAgentWarehouseId` string 仓库 id、`isDisabled` string 是否禁用（1 禁用）、`nickname` string 昵称，`logisticsAgentId` string 服务商 id、`warehouseName` string 仓库名称，`platformWarehouseCode` string 平台仓库编码，`address` string 地址，`contactPhone` string 联系电话，`contactName` string 联系人名称）、`authForwarderWarehouseList[]` 授权货代仓库列表（`forwarderProviderWarehouseAuthId` string 货代服务商仓库授权 id、`forwarderProviderCustomerId` string 货代服务商授权 id、`forwarderProviderWarehouseId` string 货代服务商仓库 id、`isDisabled` string 是否禁用，`nickname` string 昵称，`warehouseName` string 仓库名称，`forwarderProviderId` string 货代服务商 id、`address` string 地址，`contactPhone` string 联系电话，`contactName` string 联系人名称））、`total` int 总数}}；500 → `SimpleErrorResponse`。

**#186 三方仓仓库：获取平台仓库列表** `POST /open/v1/ewm/third_warehouse/fetch/search_platform_warehouse_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）、`platformWarehouseType`（string，平台类型：FBT / FBA）。
响应 200 成功：`{result, code, data: {warehouseList[]{logisticsAgentWarehouseId` string ID、`logisticsAgentId` string 服务商 ID、`warehouseName` string 仓库名称，`platformWarehouseId` string 平台仓库 ID、`platformWarehouseCode` string 平台仓库编码，`address` string 地址，`platformWarehouseType` string 平台仓库类型，`shopName` string 店铺名称，`thirdWarehouseProviderAuthId` int 三方仓服务商授权 ID}、`total` int}}；500 → `SimpleErrorResponse`。

### 5. 货源账号（2）

**#187 获取货源账号列表** `POST /open/v1/resell_account/fetch/search_reseller_account_page`
通用 5 项。Body 必填 `page`（int，min 1）、`pageSize`（int，min 10, max 100）。
响应 200 成功：`{result, code, data: {resellerAccountList[] {resellerAccountId` string ID、`resellerId` string 账号 ID、`resellerAccount` string 1688 账号名称，`resellerNick` string 1688 昵称，`platform` string 平台，`authStatus` string 授权状态，`status` string 状态，`gmtLastAuth` string 最后认证时间，`gmtCreate` string 创建时间，`gmtModified` string 修改时间，`gmtExpire` string 过期时间}、`total` int 总计}}；500 → `SimpleErrorResponse`。

**#188 获取账号地址列表** `POST /open/v1/resell_account/fetch/get_reseller_account_address_list`
通用 5 项。Body 必填 `resellerAccountId`（int，采购账号 id）。
响应 200 成功：`{result, code, data: {resellerAccountAddressList[] {provinceId` string 省 ID、`cityId` string 市 ID、`countyId` string 区县 ID、`townId` string 镇街 ID、`province` string 省，`city` string 市，`county` string 区县，`town` string 镇街，`fullname` string 姓名，`mobile` string 手机，`telephone` string 电话，`address` string 地址}}}；500 → `SimpleErrorResponse`。

---

## 四、附带说明

1. **#1、#2、#4、#6、#20、#21、#23、#25 已补全为字段级条目**：最先抓取的 87 个接口中，剩余的 #3、#5、#7–#19、#22、#24、#26–#87 仍为清单级条目（名称、分类、原文档链接，表格形式）。如需其请求路径、参数与响应字段详情，可通过各条目中的「查看文档」链接在原文档中查看。
2. **#139（获取当前账号有效的线下物流列表）**：该接口原文档内容较长，提取时只返回了前部字符，响应示例的枚举部分未完整读取；结构级字段已完整整理在上文。
3. 文档索引列出 188 个 API + 1 个说明文档页，与本文档接口总数一致；**所有接口均为 POST 方法，无 GET / PUT / DELETE**。
4. 本文档为只读提取整理：未提交、修改或创建任何平台数据；引用字段名称与枚举均为原文表述。
