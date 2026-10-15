# FastMoss 家居日用品选品

## 页面使用

打开选品中心，默认地区为马来西亚，采购方向为家居日用品。

1. 点击「检查连接」，再点击「连接并刷新分类」。分类读取自 FastMoss 新品榜页面本身的品类筛选项（标识 = 页面单选值，如 `10` = 居家日用），英文名来自分类接口仅作辅助显示，不由 AI 生成。该榜单来源页只提供一级品类，没有子品类筛选。
2. 点击「家居日用品快捷范围」（当前匹配：居家日用、厨房用品、家纺布艺），检查后可删改或添加。家具、家电、家装建材不默认纳入。国家与分类必须在来源页面同时生效才会保存数据：单选框已选中，且页面自身的数据请求带有 `region=MY&l1_cid=<分类>&page=<页码>`。
3. 设置每类页数（默认 3 页），点击「开始抓取」。当前版本沿用上游 **新品榜**，不是销量榜。
4. 完成后自动保存并显示商品表格；搜索、按品类过滤、分页、多选最多 20 条。展开行可查看各来源榜单排名、原始指标和抓取时间。
5. 填写采购价格等条件，点击「依据榜单寻找货源」，结果进入候选库。不会直接采购、发布或采集到妙手。

分类选择按登录用户和国家保存在浏览器。刷新分类后失效的选择会提示重新选择。历史抓取任务和榜单保存在数据库；刷新页面会恢复最近任务和结果。部分分类失败时可使用成功结果，查看错误后重新抓取。

快捷范围是对实际分类名称（家居、日用、收纳、清洁、厨房等）进行匹配的便利选择，不保证平台把所有家用商品归为同一个类。分类接口与商品榜 UI 不兼容时会明确失败，不退回综合榜。

## 本机安装与启动

在项目根目录执行：

```powershell
./scripts/install-fastmoss.ps1
```

安装到 `.runtime`，不改全局 PATH：

- 上游解析器：[fastmoss-rpa-skills](https://github.com/liangdabiao/fastmoss-rpa-skills)，固定提交 `dcd45e7f2b088867551fb10772e32b21f4219193`，SHA-256 校验后加载商品解析器。页面筛选、链接提取和任务管理使用本项目适配层。
- [BrowserSkill](https://github.com/Tencent/BrowserSkill) CLI `0.3.2`，校验官方发布清单中的校验和。

在实际登录 FastMoss 的浏览器安装 [Chrome 扩展](https://chromewebstore.google.com/detail/browserskill/hhcmgoofomhgciiibhipgmgkgnoenaoi) 或 [Edge 扩展](https://microsoftedge.microsoft.com/addons/detail/browserskill/emacgiaaaiojkkpkddmmdfhmokgmnikg)，打开扩展并启用本地连接，然后登录 FastMoss。扩展连接和账号权限必须由真实环境提供；不会绕过验证码或平台访问权限。

数据库迁移新增 `fastmoss_tasks` 与 `fastmoss_catalogs` 两张表，无业务表删除或数据回写。先备份数据库，再在 backend 工作目录、使用正确 DATABASE_URL 执行：

```powershell
../.venv/Scripts/python.exe -m alembic upgrade head
```

重启本项目后端，使新增路由生效（现有本机脚本为 `scripts/start-sourcing-local.ps1`），随后：

```powershell
./scripts/start-fastmoss-local.ps1
```

脚本以隐藏窗口启动本地守护进程和独立 worker，日志在 `.runtime/logs/fastmoss-worker.*.log`。它与浏览器必须位于同一 Windows 用户会话；Docker 内运行的后端不能直接调用宿主浏览器的命名管道。工作进程可在浏览器未连接时启动，连接后再从页面提交任务。

可选配置（backend/.env，或启动进程的环境变量）：

```dotenv
FASTMOSS_BSK_BIN=D:/path/to/bsk.exe
FASTMOSS_UPSTREAM_DIR=D:/path/to/fastmoss-upstream
FASTMOSS_CATEGORY_TIMEOUT=600
```

默认自动查找项目 `.runtime` 目录。每个品类有执行时限，所有 worker 与分类刷新共享 PostgreSQL 浏览器锁。异常中断标记失败，不自动重放浏览器操作。

## CSV 与统计口径

支持原有固定英文模板 CSV/XLSX，以及上游原始商品 CSV（`product_name,country,price,rank,sales_period,gmv_period,...`）。原始 CSV 没有来源链接时，导入前在页面补充实际 FastMoss 榜单 URL。无分类标记「未分类」。

- 抓取时间与统计日期分开；页面未提供的统计日期、周期、金额和销量显示未知。
- `1.2万`、`2.5K` 等明确单位转换成数值，同时保存原文；区间或不确定货币不会被猜成单一价格/币种。
- 多品类中的相同商品链接合并为一个商品行，各榜单依据保留在详情中，不生成跨榜单综合排名。
- 缺少商品链接时保存实际榜单链接，明确标为榜单来源；图片缺失允许空白。
- 同一任务最多保存 500 个商品；原始 CSV 保留成功分类抓取到的原始行，可能包含重复行或超出展示上限的行，页面会提示截断。
- 任务与原始 CSV 按系统登录用户隔离。

## API

接口前缀 `/api/v1/sourcing/fastmoss`，全部需要现有 Bearer 登录：

| 接口 | 行为 |
|---|---|
| GET `/status` | 检查依赖与 BrowserSkill 连接，不等同于 FastMoss 账号授权成功 |
| GET `/categories?target_market=MY` | 读取当前用户保存的真实分类 |
| POST `/categories/refresh?target_market=MY` | 通过浏览器重新读取分类 |
| POST `/tasks` | 接收 `request_key`、`target_market`、`category_ids`、`pages` |
| GET `/tasks?target_market=MY&page=1` | 分页任务记录 |
| GET `/tasks/{id}` | 进度、每类结果、错误、`report_id` |
| GET `/tasks/{id}/csv` | 下载成功结果的原始 CSV |

任务状态：`queued / running / succeeded / partial / failed`。相同请求标识和参数返回同一任务；参数不同返回 409。选品仍使用 `report_id + report_rows` 接口。

## 真实环境验收（2026-10-14，Chrome + BrowserSkill 0.3.2，已登录 FastMoss）

| 项目 | 结果 |
|---|---|
| 读取分类 | 30 个真实一级品类（中文名 + 标识 + 英文名）；快捷范围 = 居家日用 / 厨房用品 / 家纺布艺 |
| 马来西亚 + 居家日用 + 厨房用品，每类 3 页 | 42 秒完成，60 条；每类排名 1→30 连续，各自榜单内排名不混排 |
| 筛选生效 | 每行原始数据记录 `filter_region=MY`、`filter_l1_cid=10/11`；商品“国家/地区”列均为马来西亚 |
| 字段 | 统计日期 `2026-10-11`、统计周期“三日”（来自表头“三日销量”）、抓取时间分开保存；60 条均有商品详情链接和图片；18 条区间价保留原文、价格未知 |
| 原始 CSV | 60 行，与列表逐条核对 0 差异 |
| 部分失败 | 居家日用 + 虚拟商品：前者成功 10 条，后者“来源榜单在马来西亚「虚拟商品」下暂无商品（页面显示无数据）”，任务为“部分完成”，成功数据可用 |
| 找货源 | 勾选居家日用 2 条（#3 木质衣物夹、#6 衣物收纳盒），采购品类自动带入“居家日用”；DeepSeek 依据规划 6 个关键词，1 次 1688 搜索得到 5 个真实货源进入候选库，均引用本榜单第 4、7 行依据 |

验收中修正的真实页面问题：分类改为读取榜单页面单选项（原接口只返回英文名，按名称找不到筛选项）；按分类标识选择；
跳过 Ant Design 隐藏测量行；前三名奖牌图标按页面顺序得到排名（原始数据标注 `rank_source=icon_position`）；
页面埋点请求会写满浏览器默认 250 条资源计时缓冲，改为观察器单独记录榜单数据请求；分页按钮使用完整鼠标事件；
空榜单与页面结构变化分开报告；支持 `₫` 等后缀币种，`Rp 12.000` 这类千分位不明确的金额保留原文。

## 验证与限制

自动化测试覆盖转换、未知字段、去重、国家与品类双重验证、分类失效、数据库任务、部分成功、权限隔离、请求幂等、浏览器锁、中断恢复与选品依据衔接。集成测试必须使用独立 `*_test` 数据库并先迁移。

真实网页结构可能变化。当前适配器无法确认筛选选中状态、页面数据请求参数或表格结构时会停止并给出具体原因；新品榜每页 10 条，每类最多 10 页。模拟数据测试不证明实时网页抓取成功，页面改版后需重新做真实验收。
