"""Lossless source records + explicit price meanings, reusing candidate versioning."""
import copy
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select, update
from app.models.sourcing import SourcingCandidate as Candidate, SourcingEvaluation as Evaluation, SourcingTask as Task
from app.services import sourcing_service as service

UNITS = {'weight': 'kg', 'skuMap.weight': 'kg', 'packageLength': 'cm', 'packageWidth': 'cm', 'packageHeight': 'cm',
         'skuMap.packageLength': 'cm', 'skuMap.packageWidth': 'cm', 'skuMap.packageHeight': 'cm',
         'stock': '数量（原始整数）', 'currency': '接口未给出，操作人确认'}
PRICE_MEANINGS = {'price': 'SPU 货源价格', 'skuMap.price': '妙手公共采集箱 SKU price（文档标为售价）',
                  'skuMap.oriPrice': '妙手原始售价字段', 'tiktok_sale_price': '尚未设置；不从公共箱价格推导'}


def source_details(candidate):
    raw = candidate.raw_data or {}
    detail = raw.get('detail_response', {}).get('data', {}).get('editCommonCollectBoxDetail', {})
    if not detail:
        return None
    return {'price': detail.get('price'), 'skuMap': detail.get('skuMap'), 'stock': detail.get('stock'),
            'weight': detail.get('weight'), 'price_meanings': PRICE_MEANINGS, 'units': UNITS,
            'supplier_information_available': bool(detail.get('sourceSupplierInfo')),
            'supplier_qualifications_verified': False, 'tiktok_sale_price': None}


def source_version_fields(candidate):
    """Ignore fetch timestamps, but invalidate decisions when source facts change."""
    detail = (candidate.raw_data or {}).get('detail_response', {}).get('data', {}).get('editCommonCollectBoxDetail', {})
    fields = ('title', 'imgUrls', 'price', 'skuMap', 'stock', 'weight', 'packageLength',
              'packageWidth', 'packageHeight', 'sourceList', 'sourceSupplierInfo', 'sourceMataInfo')
    return {key: copy.deepcopy(detail.get(key)) for key in fields} if detail else None


def public_raw(value):
    """Raw originals remain in PostgreSQL. Do not expose authentication values in UI."""
    hidden = {'cookie', 'setcookie', 'appkey', 'appsecret', 'apikey', 'accesstoken', 'refreshtoken', 'token', 'password', 'authorization', 'headers', 'rawresponsetext'}
    if isinstance(value, dict):
        return {k: ('[redacted]' if str(k).lower().replace('_', '').replace('-', '') in hidden or str(k).lower().endswith(('token', 'secret', 'password')) else public_raw(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [public_raw(v) for v in value]
    return value


async def store_detail(db, adapter, record, detail_id, user_id, market, currency):
    detail = record['editCommonCollectBoxDetail']
    source = next((x for x in detail.get('sourceList', []) if '.1688.com/' in (x.get('sourceItemUrl') or '') or '//1688.com/' in (x.get('sourceItemUrl') or '')), None)
    if not source:
        from app.services.sourcing_providers import AnalysisError
        raise AnalysisError('source_details_missing', '详情未提供 1688 来源链接，不能生成虚构完整商品')
    normalized = adapter.normalize(record, source, market, currency)
    # Existing import_one and the database unique key provide candidate identity and deduplication.
    result = await service.import_one(db, normalized, user_id, 'miaoshou_api', {'common_collect_box_id': str(detail_id), 'source': source})
    candidate = await db.scalar(select(Candidate).where(Candidate.owner_id == user_id, Candidate.identity_key == service.identity(normalized), Candidate.target_market == market).with_for_update())
    before = {'input': service.snapshot(candidate), 'source': source_version_fields(candidate)}
    version_before = candidate.version
    if normalized.supplier is None and candidate.supplier:
        normalized.supplier = candidate.supplier
    if result['status'] == 'duplicate':
        await service.edit_candidate(db, candidate, normalized)
    envelope = record.get('_response_envelope') or {'result': 'success', 'code': 'success',
                                                   'data': {k: v for k, v in record.items() if not k.startswith('_')}}
    candidate.raw_data = {'detail_response': copy.deepcopy(envelope), 'raw_response_text': record.get('_raw_response_text'),
                          'units': UNITS, 'price_meanings': PRICE_MEANINGS}
    candidate.source_spu_price = Decimal(str(detail['price'])) if detail.get('price') is not None else None
    candidate.source_stock = detail.get('stock')
    candidate.source_weight = Decimal(str(detail['weight'])) if detail.get('weight') is not None else None
    candidate.source_supplier_info = detail.get('sourceSupplierInfo')
    candidate.source_meta_info = detail.get('sourceMataInfo')
    candidate.miaoshou_detail_id = str(detail_id)
    candidate.original_source_id = source.get('sourceItemId')
    candidate.original_url = source.get('sourceItemUrl')
    candidate.source_record = {'common_collect_box_id': str(detail_id), 'source': source,
                               'ossMd5': record.get('ossMd5'), 'retrieved_at': datetime.now(timezone.utc).isoformat()}
    candidate.sync_status = 'synced'
    candidate.synced_at = datetime.now(timezone.utc)
    candidate.data_source, candidate.trust_status = 'miaoshou_api', 'authorized_account'
    changed = before != {'input': service.snapshot(candidate), 'source': source_version_fields(candidate)}
    if result['status'] == 'duplicate' and changed and candidate.version == version_before:
        candidate.version += 1
        await db.execute(update(Evaluation).where(Evaluation.candidate_id == candidate.id).values(stale=True))
        await db.execute(update(Task).where(Task.candidate_id == candidate.id, Task.status == 'queued').values(
            status='failed', error_code='input_changed', error_message='货源同步更新了分析输入，请分析当前版本', finished_at=datetime.now(timezone.utc)))
    await db.flush()
    await db.refresh(candidate)
    return {**result, 'updated': changed and result['status'] == 'duplicate', 'input_version': candidate.version,
            'sync_status': candidate.sync_status, 'completeness': candidate.completeness}
