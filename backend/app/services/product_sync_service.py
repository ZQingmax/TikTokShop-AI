"""商品管理的数据来源：妙手 TikTok 采集箱。

- 每个 TK 采集箱商品（collectBoxDetailId）对应一个 Product；同步只读妙手，不写入妙手。
- 妙手状态（未发布 / 定时发布 / 已发布）按状态筛选列表得到，因为列表行本身不带状态。
- 列表里的 price / stock 是货源价与货源库存，不是 TikTok 售价；已认领店铺的商品读取店铺模式详情，
  售价取有效 SKU 的最低/最高价（店铺站点币种），库存取有效 SKU 库存之和，名称取发布用标题。
- 成本价优先取通过公共采集箱 ID 关联的 1688 货源候选采购价，其次取妙手 SKU 的 originPrice（货源价，CNY）；
  都没有时留空，不填占位值。
- 妙手中已不存在的商品标记为「已移出妙手」，不删除本地记录。
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy import select
from app.clients.miaoshou_client import MiaoshouError
from app.models.product import Product
from app.models.sourcing import SourcingCandidate

MARKETS = ('MY', 'TH', 'VN', 'SG', 'PH', 'ID')
CURRENCIES = {'MY': 'MYR', 'TH': 'THB', 'VN': 'VND', 'SG': 'SGD', 'PH': 'PHP', 'ID': 'IDR'}
STATUS = {'published': 'listed', 'timingPublish': 'active', 'notPublished': 'draft', 'removed': 'inactive'}
MAX_PAGES = 50


def decimal(value):
    try:
        return Decimal(str(value)) if value not in (None, '') else None
    except InvalidOperation:
        return None


def integer(value):
    try:
        return int(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


async def list_all(client, status=None):
    rows = []
    for page in range(1, MAX_PAGES + 1):
        batch = (await client.get_tiktok_list(page, 100, status=status)).data['detailList']
        rows += batch
        if len(batch) < 100:
            return rows
    raise RuntimeError('妙手 TikTok 采集箱商品超过同步上限')


async def shop_markets(client):
    markets = {}
    for market in MARKETS:
        for page in range(1, 21):
            shops = (await client.get_shops('tiktok', market, page=page, page_size=100)).data['shopList']
            for shop in shops:
                if shop.get('platform') == 'tiktok' and shop.get('site') == market:
                    markets[str(shop.get('shopId'))] = market
            if len(shops) < 100:
                break
    return markets


async def shop_detail(client, detail_id, shop_id):
    """Sale-side facts from the shop-mode detail; None when it cannot be read for this product."""
    try:
        info = (await client.get_shop_detail(detail_id, shop_id)).data['shopCollectItemInfo']
    except MiaoshouError as error:
        if error.category in ('auth', 'permission', 'rate_limit', 'configuration'):
            raise
        return None
    skus = [x for x in (info.get('skuMap') or {}).values() if str(x.get('isDelete', '0')) != '1']
    prices = [p for p in (decimal(x.get('price')) for x in skus) if p is not None and p > 0]
    origins = [p for p in (decimal(x.get('originPrice')) for x in skus) if p is not None and p > 0]
    stocks = [s for s in (integer(x.get('stock')) for x in skus) if s is not None]
    return {'title': (info.get('title') or '').strip(), 'site': info.get('site'),
            'price_min': min(prices) if prices else None, 'price_max': max(prices) if prices else None,
            'origin_min': min(origins) if origins else None, 'stock': sum(stocks) if stocks else None, 'sku_count': len(skus)}


async def sync(db, client):
    """Upserts every TikTok collect-box product. Returns counts for the UI."""
    rows = await list_all(client)
    status_of = {}
    for status in ('timingPublish', 'published'):
        for row in await list_all(client, status):
            status_of[str(row.get('collectBoxDetailId'))] = status
    markets = await shop_markets(client)
    common_ids = {str(x.get('commonCollectBoxDetailId')) for x in rows if x.get('commonCollectBoxDetailId')}
    candidates = {}
    if common_ids:
        found = (await db.scalars(select(SourcingCandidate).where(SourcingCandidate.miaoshou_detail_id.in_(common_ids))
                                  .order_by(SourcingCandidate.updated_at.desc()))).all()
        for candidate in found:
            candidates.setdefault(candidate.miaoshou_detail_id, []).append(candidate)
    existing = {p.miaoshou_detail_id: p for p in (await db.scalars(select(Product).where(Product.miaoshou_detail_id.is_not(None)))).all()}
    now = datetime.now(timezone.utc)
    counts = {'created': 0, 'updated': 0, 'removed': 0, 'detail_failed': 0, 'total': len(rows)}
    seen = set()
    for row in rows:
        detail_id = str(row.get('collectBoxDetailId') or '')
        if not detail_id.isdecimal():
            continue
        seen.add(detail_id)
        shop_ids = [str(s.get('shopId')) for s in row.get('collectBoxDetailShopList') or [] if s.get('shopId')]
        market = next((markets[s] for s in shop_ids if s in markets), None)
        facts = await shop_detail(client, detail_id, shop_ids[0]) if shop_ids else None
        if not market and facts and facts['site'] in MARKETS:
            market = facts['site']
        common_id = str(row['commonCollectBoxDetailId']) if row.get('commonCollectBoxDetailId') else None
        options = candidates.get(common_id) or []
        candidate = next((c for c in options if c.target_market == market), options[0] if options else None)
        status = status_of.get(detail_id, 'notPublished')
        product = existing.get(detail_id)
        if not product:
            product = Product(miaoshou_detail_id=detail_id)
            db.add(product)
            counts['created'] += 1
        else:
            counts['updated'] += 1
        product.name = ((facts or {}).get('title') or (row.get('title') or '').strip())[:500] or f'妙手商品 {detail_id}'
        product.common_detail_id = common_id
        product.miaoshou_status, product.status = status, STATUS[status]
        product.market, product.shop_ids = market, shop_ids
        product.thumbnail, product.item_num = row.get('thumbnail'), row.get('itemNum')
        if facts or not shop_ids:
            # No shop means no TikTok sale price yet: the list price is only the source price.
            product.sale_price = facts['price_min'] if facts else None
            product.sale_price_max = facts['price_max'] if facts else None
            product.sale_currency = CURRENCIES.get(market) if facts and facts['price_min'] is not None else None
            product.stock = facts['stock'] if facts else None
            product.sku_count = facts['sku_count'] if facts else None
        else:
            counts['detail_failed'] += 1  # keep the last known sale-side values
        product.sourcing_candidate_id = candidate.id if candidate else None
        if candidate and candidate.purchase_price is not None:
            product.cost_price, product.cost_currency, product.cost_source = candidate.purchase_price, candidate.currency, 'sourcing'
        elif facts and facts['origin_min'] is not None:
            product.cost_price, product.cost_currency, product.cost_source = facts['origin_min'], 'CNY', 'miaoshou'
        elif facts or not shop_ids:
            product.cost_price = product.cost_currency = product.cost_source = None
        product.source_url = candidate.original_url or candidate.product_url if candidate else product.source_url
        product.source_product_id = candidate.source_product_id if candidate else product.source_product_id
        product.synced_at = now
    for detail_id, product in existing.items():
        if detail_id not in seen and product.miaoshou_status != 'removed':
            product.miaoshou_status, product.status, product.synced_at = 'removed', STATUS['removed'], now
            counts['removed'] += 1
    await db.flush()
    return {**counts, 'synced_at': now.isoformat()}
