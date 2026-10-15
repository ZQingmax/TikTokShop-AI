"""把 1688-cli JSON（docs/JSON_CONTRACTS.md）标准化为系统字段。

规则：
- 数据源没有的字段一律为 None / 空列表，绝不推算或补造。
- 平台提供的指标放在 platform_metrics；1688-cli 自带的本地评分放在 cli_score，并注明非平台数据。
- 每条记录保留 raw（原始 CLI 对象），以适应 CLI 版本变化。
- 关键字段缺失（如 offers 列表、offerId）视为契约变化，抛出 contract_changed。
"""
import copy
import html
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from app.services.alibaba1688.commands import OFFER_ID
from app.services.alibaba1688.errors import Alibaba1688Error

SOURCE = '1688_cli'
CURRENCY = 'CNY'


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _str(value) -> str | None:
    """CLI 文本字段可能带 HTML 实体（如 &gt;），展示值反转义；raw 原样保留。"""
    if value is None:
        return None
    value = html.unescape(str(value)).strip()
    return value or None


# 买家（当前登录账号）自己的信息，不属于货源数据：不返回前端、不入库
BUYER_FIELDS = {'freight': ('receiveAddress',)}


def scrub_raw(data: dict) -> dict:
    data = copy.deepcopy(data)
    for parent, keys in BUYER_FIELDS.items():
        if isinstance(data.get(parent), dict):
            for key in keys:
                data[parent].pop(key, None)
    data.pop('_cached', None)
    data.pop('_fetched_at', None)
    return data


def fetched_time(data: dict) -> str:
    value = data.get('_fetched_at') if isinstance(data, dict) else None
    return value if isinstance(value, str) else now_iso()


def _positive(value):
    """重量等物理量为 0 或负数时视为数据源未提供。"""
    n = _num(value)
    return n if n is not None and n > 0 else None


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        d = Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, ValueError):
        return None
    return float(d) if d.is_finite() else None


def _int(value):
    n = _num(value)
    return int(n) if n is not None and float(n).is_integer() else None


def _url(value) -> str | None:
    value = _str(value)
    if not value:
        return None
    if value.startswith('//'):
        value = 'https:' + value
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname:
        return None
    return value


def _images(value) -> list[str]:
    """search 结果的 image 有时是逗号拼接的多个 URL。"""
    if not value:
        return []
    parts = value if isinstance(value, list) else str(value).split(',')
    return list(dict.fromkeys(u for u in (_url(x) for x in parts) if u))


def offer_url(offer_id: str) -> str:
    return f'https://detail.1688.com/offer/{offer_id}.html'


def _require(condition: bool, what: str):
    if not condition:
        raise Alibaba1688Error('contract_changed', f'CLI 输出缺少字段：{what}')


def search_item(raw: dict, fetched_at: str) -> dict:
    _require(isinstance(raw, dict), 'offers[]')
    offer_id = _str(raw.get('offerId'))
    _require(bool(offer_id and OFFER_ID.match(offer_id)), 'offers[].offerId')
    price = raw.get('price') if isinstance(raw.get('price'), dict) else {}
    supplier = raw.get('supplier') if isinstance(raw.get('supplier'), dict) else {}
    location = raw.get('location') if isinstance(raw.get('location'), dict) else {}
    verified = raw.get('verified') if isinstance(raw.get('verified'), dict) else {}
    demand = raw.get('demand') if isinstance(raw.get('demand'), dict) else {}
    images = _images(raw.get('image'))
    return {
        'offer_id': offer_id,
        'title': _str(raw.get('title')),
        'main_image': images[0] if images else None,
        'images': images,
        'product_url': offer_url(offer_id),
        'price': {'text': _str(price.get('text')), 'min': _num(price.get('min')), 'max': _num(price.get('max')),
                  'currency': CURRENCY},
        'min_order_quantity': None,  # 搜索列表不提供起批量，需查看详情
        'sales': {'text': _str(demand.get('orderCountText') or raw.get('turnover')), 'count': _int(demand.get('orderCount'))},
        'repurchase_rate': _num(demand.get('repurchaseRate')),
        'supplier': {'name': _str(supplier.get('name')), 'id': None, 'shop_url': _url(supplier.get('shopUrl')),
                     'years': _int(supplier.get('years'))},
        'location': {'province': _str(location.get('province')), 'city': _str(location.get('city'))},
        'biz_type': _str(raw.get('bizType')),
        'verified': {'factory': bool(verified.get('factory')), 'business': bool(verified.get('business')),
                     'super_factory': bool(verified.get('superFactory'))},
        'is_ad': bool(raw.get('isP4P')),
        'tags': [str(t) for t in raw.get('tags') or [] if t][:20],
        'source': SOURCE,
        'fetched_at': fetched_at,
        'raw': scrub_raw(raw),
    }


def search_result(data: dict, *, keyword: str | None = None) -> dict:
    offers = data.get('offers')
    _require(isinstance(offers, list), 'offers')
    fetched_at = fetched_time(data)
    items = [search_item(x, fetched_at) for x in offers]
    return {'keyword': keyword if keyword is not None else _str(data.get('keyword')), 'sort': data.get('sort'),
            'filters': data.get('filters') if isinstance(data.get('filters'), dict) else {},
            'total_before_filter': _int(data.get('totalBeforeFilter')), 'total': len(items), 'items': items,
            'source': SOURCE, 'fetched_at': fetched_at,
            'notice': '数据来自 1688 搜索页（1688 批发价，人民币）；1688 销量 ≠ TikTok 销量，不代表 TikTok 热销'}


def offer_detail(data: dict) -> dict:
    offer_id = _str(data.get('offerId'))
    _require(bool(offer_id and OFFER_ID.match(offer_id)), 'offerId')
    supplier = data.get('supplier') if isinstance(data.get('supplier'), dict) else {}
    freight = data.get('freight') if isinstance(data.get('freight'), dict) else {}
    images = _images(data.get('images'))
    main = _url(data.get('mainImage')) or (images[0] if images else None)
    if main and main not in images:
        images = [main, *images]
    skus = []
    for s in data.get('skus') or []:
        if not isinstance(s, dict):
            continue
        skus.append({'sku_id': _str(s.get('skuId')), 'specs': _str(s.get('specs')), 'price': _num(s.get('price')),
                     'multi_price': _num(s.get('multiPrice')), 'stock': _int(s.get('stock')),
                     'sale_count': _int(s.get('saleCount')), 'image': _url(s.get('image'))})
    tiers = [{'min_qty': _int(t.get('minQty')), 'price': _num(t.get('price'))}
             for t in data.get('priceTiers') or [] if isinstance(t, dict)]
    return {
        'offer_id': offer_id,
        'title': _str(data.get('title')),
        'product_url': offer_url(offer_id),
        'main_image': main,
        'images': images,
        'price': {'text': _str(data.get('priceRange')), 'min': _num(data.get('priceMin')),
                  'max': _num(data.get('priceMax')), 'currency': CURRENCY},
        'price_tiers': tiers,
        'unit': _str(data.get('unitName')),
        'min_order_quantity': _int(data.get('minOrderQty')),
        'mix_order_quantity': _int(data.get('mixOrderQty')),
        'attributes': [{'name': _str(a.get('name')), 'value': _str(a.get('value'))}
                       for a in data.get('attributes') or [] if isinstance(a, dict)],
        'options': [{'prop': _str(o.get('prop')), 'values': [{'name': _str(v.get('name')), 'image': _url(v.get('imageUrl'))}
                     for v in o.get('values') or [] if isinstance(v, dict)]}
                    for o in data.get('options') or [] if isinstance(o, dict)],
        'skus': skus,
        'package_info': [{'sku_id': _str(p.get('skuId')), 'spec': _str(p.get('spec')),
                          **{k: _positive(p.get(k)) for k in ('length', 'width', 'height', 'weight', 'volume')}}
                         for p in data.get('packageInfo') or [] if isinstance(p, dict)],
        'supplier': {'name': _str(supplier.get('name')), 'login_id': _str(supplier.get('loginId')),
                     'member_id': _str(supplier.get('memberId')), 'user_id': _str(supplier.get('userId'))},
        'shipping': {'send_area': _str(freight.get('sendArea')), 'province': _str(freight.get('province')),
                     'city': _str(freight.get('city')), 'unit_weight': _positive(freight.get('unitWeight'))},
        'sold_count': _int(data.get('saledCount')),
        'category_id': _str(data.get('categoryId')),
        'source': SOURCE,
        'fetched_at': fetched_time(data),
        'raw': scrub_raw(data),
    }


def _cli_score(item: dict) -> dict | None:
    if item.get('score') is None:
        return None
    return {'score': _num(item.get('score')), 'breakdown': item.get('scoreBreakdown') or [],
            'note': '1688-cli 本地规则计算的参考分，不是 1688 平台指标'}


def supplier_item(item: dict, fetched_at: str) -> dict:
    s = item.get('supplier') if isinstance(item.get('supplier'), dict) else None
    _require(s is not None, 'items[].supplier')
    loc = s.get('location') if isinstance(s.get('location'), dict) else {}
    tp = s.get('tp') if isinstance(s.get('tp'), dict) else {}
    factory = s.get('factory') if isinstance(s.get('factory'), dict) else {}
    service = s.get('service') if isinstance(s.get('service'), dict) else {}
    demand = s.get('demand') if isinstance(s.get('demand'), dict) else {}
    member_id = _str(s.get('memberId'))
    return {
        'supplier_id': member_id,
        'company_name': _str(s.get('companyName')),
        'login_id': _str(s.get('loginId')),
        'member_id': member_id,
        'shop_url': _url(s.get('shopUrl')),
        'factory_card_url': _url(s.get('factoryCardUrl')),
        'location': {'province': _str(loc.get('province')), 'city': _str(loc.get('city')), 'address': _str(loc.get('address'))},
        'business_mode': _str(s.get('businessMode')),
        'production_service': _str(s.get('productionService')),
        'service_years': _int(tp.get('serviceYears')),
        'member_level': _str(tp.get('memberLevel')),
        'factory': {'is_factory': bool(factory.get('isFactory')), 'super_factory': bool(factory.get('superFactory')),
                    'factory_tag': _str(factory.get('factoryTag')), 'factory_level': _str(factory.get('factoryLevel')),
                    'factory_inspection': bool(factory.get('factoryInspection')),
                    'business_inspection': bool(factory.get('businessInspection'))},
        # 以下为 1688 平台提供的指标，原样展示
        'platform_metrics': {'composite_score': _num(service.get('compositeScore')),
                             'response_rate': _num(service.get('wwResponseRate')),
                             'repeat_rate': _num(service.get('repeatRate')),
                             'compliance_rate': _num(service.get('complianceRate')),
                             'pay_order_count_3m': _int(demand.get('payOrderCount3m')),
                             'sale_quantity_3m': _int(demand.get('saleQuantity3m')),
                             'fuzzy_pay_amount_3m': _str(demand.get('fuzzyPayAmount3m'))},
        'cli_score': _cli_score(item),
        'tags': [str(t) for t in s.get('tags') or [] if t][:20],
        'offers_preview': [{'offer_id': _str(o.get('offerId')), 'title': _str(o.get('title')), 'url': _url(o.get('url')),
                            'price_text': _str((o.get('price') or {}).get('text')) if isinstance(o.get('price'), dict) else None,
                            'image': _url(o.get('image')), 'sale_quantity': _int(o.get('saleQuantity'))}
                           for o in s.get('offersPreview') or [] if isinstance(o, dict)][:10],
        'source': SOURCE,
        'fetched_at': fetched_at,
        'raw': scrub_raw(item),
    }


def supplier_search_result(data: dict, keyword: str) -> dict:
    items = data.get('items')
    _require(isinstance(items, list), 'items')
    fetched_at = fetched_time(data)
    return {'keyword': keyword, 'total_before_filter': _int(data.get('totalBeforeFilter')),
            'items': [supplier_item(x, fetched_at) for x in items], 'total': len(items),
            'source': SOURCE, 'fetched_at': fetched_at,
            'notice': '公司搜索来自 1688 企业搜索；platform_metrics 为平台提供的指标，cli_score 为 1688-cli 本地参考分'}


def supplier_inspect(data: dict) -> dict:
    s = data.get('supplier') if isinstance(data.get('supplier'), dict) else None
    _require(s is not None, 'supplier')
    f = data.get('factory') if isinstance(data.get('factory'), dict) else {}
    t = data.get('trust') if isinstance(data.get('trust'), dict) else {}
    target = data.get('target') if isinstance(data.get('target'), dict) else {}
    offers = data.get('offers') if isinstance(data.get('offers'), dict) else {}
    sources = data.get('sources') if isinstance(data.get('sources'), dict) else {}
    member_id = _str(s.get('memberId'))
    return {
        'supplier_id': member_id,
        'target': {'input': _str(target.get('input')), 'type': _str(target.get('type')), 'offer_id': _str(target.get('offerId'))},
        'company_name': _str(s.get('name')),
        'login_id': _str(s.get('loginId')),
        'member_id': member_id,
        'shop_url': _url(s.get('shopUrl')),
        'identity': _str(s.get('identity')),
        'factory': {'is_factory': bool(f.get('isFactory')), 'super_factory': bool(f.get('superFactory')),
                    'tp_years': _int(f.get('tpYears')), 'medal_level': _str(f.get('medalLevel')),
                    'established_at': _str(f.get('establishedAtText')), 'location': _str(f.get('location')),
                    'address': _str(f.get('address')), 'production_service': _str(f.get('productionService')),
                    'employee_scale': _str(f.get('employeeScale')), 'worker_count': _str(f.get('workerCount')),
                    'tags': [str(x) for x in f.get('tags') or [] if x][:20]},
        'platform_metrics': {'retention_rate': _num(t.get('retentionRate')), 'company_label': _str(t.get('companyLabel')),
                             'service_scores': [{'key': _str(x.get('key')), 'label': _str(x.get('label')), 'score': _num(x.get('score'))}
                                                for x in t.get('serviceScores') or [] if isinstance(x, dict)],
                             'shop_tags': [str(x) for x in t.get('shopTags') or [] if x][:20]},
        'offers_available_count': _int(offers.get('availableCount')),
        'source_offer_url': _url(sources.get('offerUrl')),
        'warnings': [str(w) for w in data.get('warnings') or []][:20],
        'source': SOURCE,
        'fetched_at': fetched_time(data),
        'raw': scrub_raw(data),
    }
