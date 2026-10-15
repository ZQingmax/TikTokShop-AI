"""商品上架：TK 采集箱商品按妙手规则预检，再通过发布产品（#25）发布到已认领的店铺。

规则：
- 只能发布已认领到店铺（店铺模式）的商品；每个商品按「商品 × 店铺」检查和发布。
- 预检使用店铺模式详情，与商品编辑工作台同一套妙手/TikTok 校验（标题、描述、图片、重量尺寸、末级类目、
  必填属性与认证、SKU 售价及店铺仓库库存）。未通过预检的商品不会提交。
- 已发布的商品不再重复发布；同一「商品 × 店铺」已有未完成的发布任务时拒绝新任务。
- 发布是写操作：只提交一次，超时等不确定结果只查询发布记录和采集箱状态，不自动重发。
"""
import hashlib
import json
import re
from fastapi import HTTPException
from sqlalchemy import select
from app.models.listing import ListingTask
from app.models.user import User
from app.services import workbench_service as rules

ACTIVE = ['queued', 'running', 'waiting']
# Items that may still turn into a published product on the platform.
PENDING = ('submitting', 'submitted', 'uncertain')
CJK = re.compile(r'[一-鿿]')


def number(value):
    """Shop-mode details return numbers as strings in places (e.g. warehouse stock)."""
    if isinstance(value, str) and re.fullmatch(r'-?\d+', value.strip()):
        return int(value)
    if isinstance(value, str) and re.fullmatch(r'-?\d+\.\d+', value.strip()):
        return float(value)
    return value


def normalize(content):
    content = dict(content)
    for field in ('weight', 'packageLength', 'packageWidth', 'packageHeight'):
        content[field] = number(content.get(field))
    skus = {}
    for key, sku in (content.get('skuMap') or {}).items():
        sku = {**sku, **{f: number(sku.get(f)) for f in ('price', 'stock', 'weight') if f in sku}}
        allocations = sku.get('shopIdToWarehouseIdAndStockMap')
        if isinstance(allocations, dict):
            sku['shopIdToWarehouseIdAndStockMap'] = {
                str(shop): {str(w): number(n) for w, n in (stocks or {}).items()} if isinstance(stocks, dict) else stocks
                for shop, stocks in allocations.items()}
        skus[key] = sku
    content['skuMap'] = skus
    for field in ('imgUrls', 'skuPropertyList', 'productAttributes', 'productCertifications', 'manufacturerIds', 'responsiblePersonIds'):
        content[field] = content.get(field) or []
    content['title'] = content.get('title') or ''
    return content


def warnings_for(content, market):
    warnings = []
    if market != 'CN' and CJK.search(content.get('title') or ''):
        warnings.append({'field': 'title', 'message': '标题含中文，目标站点买家可能无法阅读，平台审核也可能拒绝；建议先翻译'})
    if CJK.search(rules.notes(content)) and market != 'CN':
        warnings.append({'field': 'notes', 'message': '描述含中文，建议先翻译'})
    return warnings


class Checker:
    """Caches per-market categories, per-shop warehouses and per-category metadata within one batch."""

    def __init__(self, client, market):
        self.client, self.market = client, market
        self.tree = self.published = None
        self.shops, self.warehouses, self.metadata = {}, {}, {}

    async def published_ids(self):
        if self.published is None:
            self.published = set()
            for page in range(1, 21):
                rows = (await self.client.get_tiktok_list(page, 100, status='published')).data['detailList']
                self.published.update(str(x.get('collectBoxDetailId')) for x in rows)
                if len(rows) < 100:
                    break
        return self.published

    async def check(self, detail_id, shop_id):
        """Returns (title, errors, warnings) for one product in one shop, using the platform's current data."""
        if str(detail_id) in await self.published_ids():
            return None, [{'field': 'status', 'message': '该商品在妙手 TikTok 采集箱中已是「已发布」，不重复发布'}], []
        if shop_id not in self.shops:
            try:
                self.shops[shop_id] = await rules.shop_for(self.client, self.market, shop_id)
            except HTTPException:
                self.shops[shop_id] = None
        if not self.shops[shop_id]:
            return None, [{'field': 'shop_id', 'message': f'店铺 {shop_id} 不在已授权的 {self.market} 站点 TikTok 店铺中'}], []
        remote = (await self.client.get_shop_detail(detail_id, shop_id)).data['shopCollectItemInfo']
        content = normalize(remote)
        if remote.get('site') and remote['site'] != self.market:
            return content['title'], [{'field': 'site', 'message': f'该商品店铺详情站点为 {remote["site"]}，与目标站点 {self.market} 不一致'}], []
        if self.tree is None:
            self.tree = (await self.client.get_categories(self.market)).data.get('cateTree') or {}
        category = rules.find_category(self.tree, content.get('cid')) if content.get('cid') else None
        metadata = {}
        if category:
            key = (str(content['cid']), shop_id)
            if key not in self.metadata:
                self.metadata[key] = (await self.client.get_category_metadata(self.market, content['cid'], shop_id)).data.get('categoryMetadata') or {}
            metadata = self.metadata[key]
        if shop_id not in self.warehouses:
            self.warehouses[shop_id] = (await self.client.get_warehouses(shop_id)).data
        result = rules.validate_content(content, shop_id, category, metadata, self.warehouses[shop_id], self.market)
        return content['title'], result['errors'], warnings_for(content, self.market)


def find_record(records, detail_id):
    """Publish records (#26) carry the collect-box detail ID; field names are matched defensively."""
    target = str(detail_id)
    for record in records:
        if not isinstance(record, dict):
            continue
        values = [v for k, v in record.items() if 'id' in k.lower() and not isinstance(v, (dict, list))]
        for nested in record.values():
            if isinstance(nested, dict):
                values += [v for k, v in nested.items() if 'id' in k.lower() and not isinstance(v, (dict, list))]
        if target in {str(v) for v in values}:
            return record
    return None


def record_failure(record):
    """Only an explicit failure status counts as failed; anything else waits for the published status."""
    if not record:
        return None
    statuses = ' '.join(str(v).lower() for k, v in record.items() if 'status' in k.lower() and not isinstance(v, (dict, list)))
    if not any(x in statuses for x in ('fail', 'error')):
        return None
    for key, value in record.items():
        if any(x in key.lower() for x in ('reason', 'msg', 'message', 'error')) and value:
            return str(value)[:1000]
    return '妙手发布记录显示发布失败'


async def create_task(db, user_id, data):
    await db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    pairs = sorted({(x.detail_id, x.shop_id) for x in data.items})
    identity = {'kind': data.kind, 'market': data.market, 'pairs': pairs}
    fingerprint = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    existing = await db.scalar(select(ListingTask).where(ListingTask.owner_id == user_id, ListingTask.request_key == data.request_key))
    if existing:
        if existing.fingerprint != fingerprint:
            raise HTTPException(409, '相同 request_key 不能用于不同请求')
        return existing, True
    if data.kind == 'publish':
        # A pair whose earlier publish might still land must not be submitted again.
        jobs = (await db.scalars(select(ListingTask).where(ListingTask.owner_id == user_id, ListingTask.kind == 'publish',
                                                          ListingTask.status.in_(ACTIVE + ['uncertain'])))).all()
        wanted = set(pairs)
        for job in jobs:
            busy = {(x['detail_id'], x['shop_id']) for x in job.items if x['state'] in ('pending', 'ready', *PENDING)}
            if wanted & busy:
                raise HTTPException(409, f'部分商品已有未完成或结果未确认的发布任务 {job.id}，请先查询该任务')
    items = [{'detail_id': d, 'shop_id': s, 'state': 'pending'} for d, s in pairs]
    task = ListingTask(owner_id=user_id, request_key=data.request_key, fingerprint=fingerprint, kind=data.kind,
                       market=data.market, items=items, status='queued', stage='queued', poll_count=0)
    db.add(task)
    await db.flush()
    return task, False


def task_dto(task):
    fields = ('id', 'kind', 'market', 'status', 'stage', 'poll_count', 'error_code', 'error_message',
              'created_at', 'updated_at', 'finished_at')
    counts = {}
    for item in task.items:
        counts[item['state']] = counts.get(item['state'], 0) + 1
    return {**{k: getattr(task, k) for k in fields}, 'items': task.items, 'counts': counts, 'total': len(task.items)}


async def owned_task(db, id, user_id, lock=False):
    query = select(ListingTask).where(ListingTask.id == id, ListingTask.owner_id == user_id)
    task = await db.scalar(query.with_for_update() if lock else query)
    if not task:
        raise HTTPException(404, '上架任务不存在')
    return task
