"""把 1688 CLI 商品保存到现有候选库（sourcing_candidates），复用其身份键去重与 AI 分析流程。

- 入库数据只来自 CLI（详情或近期搜索结果），不接受前端提交的商品字段，避免伪造。
- 按 来源平台 + Offer ID 去重（同一用户同站点只保留一条）。
- 重复保存只刷新平台字段（价格区间、起批量、采集时间、原始数据、供应商关联），
  不改名称/采购价/SKU/备注/状态/收藏等人工维护信息，也不改变 version（不让已有 AI 评估失效）。
"""
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models.sourcing import SourcingCandidate as Candidate, SourcingSupplier as Supplier
from app.schemas.sourcing import CandidateInput, public_url
from app.services.alibaba1688.errors import Alibaba1688Error
from app.services.alibaba1688.provider import Alibaba1688Provider
from app.services.sourcing_service import completeness, identity

logger = logging.getLogger(__name__)

DATA_SOURCE = '1688_cli'
TRUST = 'platform_session'  # 平台页面数据，经用户本人登录会话只读获取
NOTE = ('1688 CLI 只读采集（用户本人登录会话）。价格为 1688 批发价（人民币）；'
        '1688 销量不代表 TikTok 销量；未经人工确认不采购、不上架。')


def _money(value) -> Decimal | None:
    """CandidateInput 只接受两位小数；超出精度时不取整，保留到 source_price_min/max。"""
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return None
    if not d.is_finite() or d < 0 or d.as_tuple().exponent < -2 or d >= 10 ** 10:
        return None
    return d


def _raw_decimal(value) -> Decimal | None:
    try:
        d = Decimal(str(value)) if value is not None else None
    except InvalidOperation:
        return None
    return d if d is not None and d.is_finite() and d >= 0 else None


def _public(urls) -> list[str]:
    result = []
    for u in urls or []:
        try:
            result.append(public_url(u))
        except ValueError:
            continue
    return list(dict.fromkeys(result))


def to_candidate_input(record: dict, detail: bool, target_market: str) -> CandidateInput:
    images = _public(record.get('images'))
    main = images[0] if images else None
    supplier = record.get('supplier') or {}
    skus = []
    if detail:
        for s in (record.get('skus') or [])[:200]:
            if not s.get('sku_id'):
                continue
            specs = (s.get('specs') or '')[:500]
            skus.append({'sku_id': s['sku_id'][:100], 'name': specs, 'specs': {'规格': specs} if specs else {},
                         'purchase_price': _money(s.get('price'))})
    note = NOTE if detail else NOTE + '仅含搜索列表字段，未获取详情（SKU/起批量待补充）。'
    return CandidateInput(source_platform='1688', source_product_id=record['offer_id'], product_url=record['product_url'],
                          name=(record.get('title') or None) and record['title'][:500], description='',
                          main_image=main, images=images[1:11], purchase_price=_money((record.get('price') or {}).get('min')),
                          currency='CNY', skus=skus, category=None, supplier=(supplier.get('name') or None),
                          target_market=target_market, source_note=note[:2000])


def supplier_key(record: dict) -> str | None:
    s = record.get('supplier') or {}
    if s.get('member_id'):
        return 'member:' + s['member_id']
    if s.get('login_id'):
        return 'login:' + s['login_id']
    host = urlsplit(s.get('shop_url') or '').hostname
    if host and (host == '1688.com' or host.endswith('.1688.com')):
        return 'shop:' + host.lower()
    return None


async def upsert_supplier(db, owner_id, record: dict, fetched_at: datetime) -> uuid.UUID | None:
    key = supplier_key(record)
    if not key:
        return None
    s = record.get('supplier') or {}
    verified = record.get('verified') or {}
    platform = {k: v for k, v in {'service_years': s.get('years'), 'verified': verified or None,
                                  'repurchase_rate': record.get('repurchase_rate')}.items() if v is not None}
    values = dict(company_name=s.get('name'), member_id=s.get('member_id'), login_id=s.get('login_id'),
                  shop_url=s.get('shop_url'), location=record.get('location') or record.get('shipping'),
                  is_factory=verified.get('factory') if verified else None,
                  platform_metrics=platform or None, fetched_at=fetched_at)
    # 只用非空值更新，避免详情缺字段时把已有平台信息清空
    updates = {k: v for k, v in values.items() if v is not None}
    stmt = insert(Supplier).values(id=uuid.uuid4(), owner_id=owner_id, source_platform='1688', supplier_key=key, **values)
    stmt = stmt.on_conflict_do_update(constraint='uq_sourcing_supplier', set_={**updates, 'updated_at': datetime.now(timezone.utc)})
    return await db.scalar(stmt.returning(Supplier.id))


async def resolve_record(provider: Alibaba1688Provider, offer_id: str, use_detail: bool) -> tuple[dict, bool, str | None]:
    """返回 (标准化记录, 是否为详情, 详情失败原因)。没有任何 CLI 数据时抛错，不用前端数据兜底。"""
    detail_error = None
    if use_detail:
        try:
            return await provider.offer(offer_id), True, None
        except Alibaba1688Error as e:
            if e.state in ('bad_input', 'not_found'):
                raise
            detail_error = e
    seen = provider.seen_offers.get(offer_id)
    if seen:
        return seen, False, detail_error.message if detail_error else None
    if detail_error:
        raise detail_error
    raise Alibaba1688Error('bad_input', '该商品不在近期 1688 搜索结果中，请先搜索或打开详情后再加入候选库')


async def save_candidate(db, provider: Alibaba1688Provider, owner_id, offer_id: str, target_market: str = 'MY',
                         use_detail: bool = True) -> dict:
    record, is_detail, detail_error = await resolve_record(provider, offer_id, use_detail)
    try:
        data = to_candidate_input(record, is_detail, target_market)
    except ValidationError:
        raise Alibaba1688Error('contract_changed', '1688 商品字段未通过候选库校验') from None
    fetched_at = datetime.fromisoformat(record['fetched_at'])
    supplier_id = await upsert_supplier(db, owner_id, record, fetched_at)
    price = record.get('price') or {}
    platform = dict(source_price_min=_raw_decimal(price.get('min')), source_price_max=_raw_decimal(price.get('max')),
                    min_order_quantity=record.get('min_order_quantity'), fetched_at=fetched_at, supplier_ref_id=supplier_id,
                    source_record={'provider': DATA_SOURCE, 'detail_fetched': is_detail, 'fetched_at': record['fetched_at'],
                                   'detail_error': detail_error},
                    raw_data={'cli_offer' if is_detail else 'cli_search_item': record.get('raw')})
    key = identity(data)
    existing = await db.scalar(select(Candidate).where(Candidate.owner_id == owner_id, Candidate.identity_key == key, Candidate.target_market == target_market)
                               .order_by(Candidate.created_at).limit(1).with_for_update())
    if existing:
        if existing.data_source == DATA_SOURCE:
            # 不让“搜索列表”数据覆盖已保存的“详情”数据
            had_detail = bool((existing.source_record or {}).get('detail_fetched'))
            if is_detail or not had_detail:
                for k, v in platform.items():
                    if k == 'raw_data':
                        v = {**(existing.raw_data or {}), **v}
                    if v is not None or k in ('source_record',):
                        setattr(existing, k, v)
        elif supplier_id and not existing.supplier_ref_id:
            existing.supplier_ref_id = supplier_id
        await db.flush()
        return {'id': str(existing.id), 'status': 'duplicate', 'detail_fetched': is_detail, 'detail_error': detail_error}
    values = data.model_dump(mode='json')
    values.update(id=uuid.uuid4(), owner_id=owner_id, identity_key=key, data_source=DATA_SOURCE, trust_status=TRUST,
                  completeness=completeness(data), version=1, review_status='pending', favorite=False,
                  original_source_id=data.source_product_id, original_url=data.product_url,
                  sourcing_status='saved', operator_note='', **platform)
    new_id = await db.scalar(insert(Candidate).values(**values).on_conflict_do_nothing(constraint='uq_sourcing_identity')
                             .returning(Candidate.id))
    if not new_id:  # 并发保存同一商品
        new_id = await db.scalar(select(Candidate.id).where(Candidate.owner_id == owner_id, Candidate.identity_key == key, Candidate.target_market == target_market).limit(1))
        return {'id': str(new_id), 'status': 'duplicate', 'detail_fetched': is_detail, 'detail_error': detail_error}
    logger.info('1688 candidate saved offer=%s detail=%s', offer_id, is_detail)
    return {'id': str(new_id), 'status': 'imported', 'detail_fetched': is_detail, 'detail_error': detail_error}
