"""Ownership, source snapshots, task idempotency and publishing preflight."""
import copy
import hashlib
import html
import json
import math
import re
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from app.models.workbench import WorkbenchDraft as Draft, WorkbenchTask as Task
from app.models.user import User
from app.services.miaoshou_mapping import public_raw
from app.services import model_settings
from app.schemas.workbench import EditorialContent
from app.schemas.sourcing import public_url

CURRENCIES = {'MY': 'MYR', 'TH': 'THB', 'VN': 'VND', 'SG': 'SGD', 'PH': 'PHP', 'ID': 'IDR'}
ACTIVE = ('queued', 'running', 'waiting', 'uncertain')
REMOTE_FIELDS = ('title', 'notes', 'imgUrls', 'cid', 'brandId', 'weight', 'packageLength', 'packageWidth',
                 'packageHeight', 'isCodOpen', 'deliveryOptionSetType', 'skuMap', 'skuPropertyList',
                 'productAttributes', 'productCertifications', 'manufacturerIds', 'responsiblePersonIds',
                 'sizeChartType', 'sizeChart')


def now():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def operator(user):
    if user.role not in ('admin', 'operator'):
        raise HTTPException(403, '只有管理员或运营人员可以编辑商品草稿')


async def owned(db, model, id, owner_id, lock=False):
    q = select(model).where(model.id == id, model.owner_id == owner_id)
    if model is Draft:
        q = q.where(Draft.archived_at.is_(None))  # merged drafts are kept only for recovery
    row = await db.scalar(q.with_for_update() if lock else q)
    if not row:
        raise HTTPException(404, '工作台记录不存在')
    return row


def require_version(draft, version):
    if draft.version != version:
        raise HTTPException(409, '草稿已被修改，请刷新并对比后重新保存')


def state(d):
    if d.synced_version == d.version:
        return 'synced'
    if d.checked_version == d.version:
        return 'ready'
    return 'modified' if d.synced_version else 'editing'


def draft_dto(d):
    fields = ('id', 'collect_item_id', 'shop_id', 'market', 'currency', 'language', 'source_snapshot',
              'version', 'checked_version', 'validation', 'synced_version', 'common_detail_id',
              'platform_detail_id', 'created_at', 'updated_at')
    # Drafts saved before a field existed get its default, so the editor always sees the full shape.
    content = {**EditorialContent().model_dump(mode='json'), **(d.content or {})}
    return {**{k: getattr(d, k) for k in fields}, 'content': content, 'state': state(d)}


def task_dto(t):
    operation = {} if t.kind == 'sync' else (t.snapshot or {}).get('operation') or {}
    return {**{k: getattr(t, k) for k in ('id', 'draft_id', 'kind', 'input_version', 'status', 'stage', 'result',
            'steps', 'error_code', 'error_message', 'adopted_version', 'created_at', 'finished_at')},
            # Lets operators see which images and instruction a task used, and reuse them.
            'operation': {k: operation[k] for k in ('image_urls', 'prompt', 'source_lang') if k in operation} or None}


def initial_snapshot(item, candidate):
    fields = ('id', 'version', 'source_platform', 'source_product_id', 'product_url', 'name', 'description',
              'images', 'main_image', 'purchase_price', 'currency', 'skus', 'category', 'supplier',
              'source_stock', 'source_weight', 'source_record', 'raw_data', 'source_supplier_info', 'source_meta_info')
    result = json.loads(json.dumps({k: getattr(candidate, k) for k in fields}, default=str))
    result['box_snapshot'] = {k: str(getattr(item, k)) if getattr(item, k) is not None else None
                              for k in ('name', 'product_url', 'purchase_price', 'currency', 'note')}
    return public_raw(result)


SPEC_SPLIT = re.compile(r'\s*[;；|>]\s*')


def sku_sort_key(value):
    return (0, int(value)) if value.isdecimal() else (1, value)


def sku_key(ids):
    return ';' + ';'.join(sorted(ids, key=sku_sort_key)) + ';' if ids else ';'


def bounded(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and low <= number <= high else None


IMG_SRC = re.compile(r'<img\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)["\']', re.I)


def description_images(markup):
    """Image URLs from a source detail HTML, in order. Only URLs are kept, never the markup itself."""
    urls = []
    for src in IMG_SRC.findall(markup or ''):
        src = html.unescape(src.strip())
        src = 'https:' + src if src.startswith('//') else src
        try:
            urls.append(public_url(src))
        except ValueError:
            continue
    return list(dict.fromkeys(urls))[:50]


def source_detail(snapshot):
    raw = snapshot.get('raw_data') or {}
    detail = ((raw.get('detail_response') or {}).get('data') or {}).get('editCommonCollectBoxDetail') or {}
    return detail, raw.get('cli_offer') or {}


def source_hints(snapshot):
    """Deterministic fill suggestions from the saved 1688 CLI or Miaoshou record. Never invented."""
    detail, offer = source_detail(snapshot)
    fields = {}
    def hint(field, value, source):
        if value is not None and field not in fields:
            fields[field] = {'value': value, 'source': source}
    hint('weight', bounded(detail.get('weight'), .001, 100), '妙手货源重量')
    hint('weight', bounded((offer.get('freight') or {}).get('unitWeight'), .001, 100), '1688 运费单位重量')
    hint('weight', bounded(snapshot.get('source_weight'), .001, 100), '货源重量')
    for field in ('packageLength', 'packageWidth', 'packageHeight'):
        hint(field, bounded(detail.get(field), 1, 1000), '妙手货源包装尺寸')
    attributes = [a for a in (offer.get('attributes') or detail.get('sourceAttrs') or []) if isinstance(a, dict)]
    size_text = next((str(a.get('value') or '') for a in attributes if a.get('name') == '包装尺寸'), '')
    sizes = [n for n in (bounded(x, 1, 1000) for x in re.findall(r'\d+(?:\.\d+)?', size_text)) if n]
    if len(sizes) in (2, 3):
        # Longest side as length; 1688 does not state the unit, so the operator must confirm.
        for field, value in zip(('packageLength', 'packageWidth', 'packageHeight'), sorted(sizes, reverse=True)):
            hint(field, value, f'1688「包装尺寸」{size_text}，单位未标注，请核实')
    specs = [{'name': o.get('prop') or '规格', 'values': [{'name': v['name'], 'image': v.get('imageUrl') or ''}
              for v in o.get('values') or [] if isinstance(v, dict) and v.get('name')]}
             for o in offer.get('options') or [] if isinstance(o, dict)]
    if not specs:
        for field, name in (('colorMap', detail.get('colorPropName') or '颜色'), ('sizeMap', detail.get('sizePropName') or '尺码'),
                            ('saleProp3Map', detail.get('saleProp3Name') or '规格')):
            values = detail.get(field) or {}
            if isinstance(values, dict) and values:
                specs.append({'name': name, 'values': [{'name': v.get('name') or str(k), 'image': v.get('imgUrl') or ''}
                                                       for k, v in values.items() if isinstance(v, dict)]})
    specs = [s for s in specs if s['values']]
    offer_skus = {str(s.get('skuId')): s for s in offer.get('skus') or [] if isinstance(s, dict)}
    detail_skus = detail.get('skuMap') if isinstance(detail.get('skuMap'), dict) else {}
    skus = []
    for s in snapshot.get('skus') or []:
        if not isinstance(s, dict):
            continue
        raw_id = str(s.get('sku_id') or '')
        names = [x for x in SPEC_SPLIT.split(s.get('name') or '') if x] or ([x for x in raw_id.split(';') if x] if ';' in raw_id else [])
        cli, ms = offer_skus.get(raw_id) or {}, detail_skus.get(raw_id) or {}
        price = bounded(s.get('purchase_price'), 0, 1e7) or bounded(cli.get('price'), 0, 1e7) or bounded(ms.get('price'), 0, 1e7)
        stock = cli.get('stock') if cli else ms.get('stock')
        skus.append({'names': names, 'item_num': (ms.get('itemNum') or (raw_id if cli else '') or '')[:200],
                     'stock': stock if type(stock) is int and stock >= 0 else None,
                     'weight': bounded(ms.get('weight'), .001, 100), 'purchase_price': price})
    return {'fields': fields, 'specs': specs, 'skus': skus, 'currency': snapshot.get('currency') or 'CNY',
            'attributes': [{'name': str(a.get('name'))[:100], 'value': str(a.get('value'))[:300]} for a in attributes[:60]],
            'desc_images': description_images(detail.get('notes'))}


def category_leaves(tree, parents=()):
    nodes = tree.values() if isinstance(tree, dict) else tree if isinstance(tree, list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        path = (*parents, str(node.get('nameChinese') or node.get('name') or node.get('cid')))
        if enabled_flag(node.get('isLastLevel')) and not enabled_flag(node.get('disabled')):
            yield {'cid': str(node.get('cid')), 'path': ' / '.join(path)}
        yield from category_leaves(node.get('children') or {}, path)


def text_grams(text):
    text = (text or '').lower()
    cjk = re.findall(r'[㐀-鿿]+', text)
    return {run[i:i + 2] for run in cjk for i in range(len(run) - 1)} | set(re.findall(r'[a-z]{3,}', text))


def category_candidates(tree, text, limit=40):
    """Cheap lexical prefilter so the model only chooses among real, plausible leaf categories."""
    grams = text_grams(text)
    scored = [(len(grams & text_grams(leaf['path'])), leaf) for leaf in category_leaves(tree)]
    return [leaf for score, leaf in sorted(scored, key=lambda x: -x[0]) if score > 0][:limit]


def sku_labels(content):
    names = {str(v.get('attrValueId')): v.get('attrValue') or str(v.get('attrValueId'))
             for prop in content.get('skuPropertyList') or [] for v in prop.get('attrValueList') or []}
    return [{'sku_key': key, 'label': ' / '.join(names.get(x, x) for x in key.split(';') if x) or '默认规格'}
            for key in content.get('skuMap') or {}]


def fill_rules(metadata):
    def rule(r):
        return {'attr_id': str(r.get('attrId')), 'name': r.get('name'), 'mandatory': enabled_flag(r.get('isMandatory')),
                'multiple': enabled_flag(r.get('isMultipleSelected')), 'customizable': enabled_flag(r.get('isCustomized')),
                'values': [{'id': str(v.get('id')), 'name': v.get('name')} for v in (r.get('values') or [])[:100]]}
    return {'product': [rule(r) for r in (metadata.get('categoryProductAttrList') or [])[:60]],
            'sale': [rule(r) for r in (metadata.get('categorySaleAttrList') or [])[:3]]}


def clean_fill(output, context, content):
    """Keep only suggestions that reference real ids and plausible units; drop the rest."""
    result = {'category': None, 'weight': None, 'package': None, 'sku_weights': [], 'attributes': [], 'sale_specs': []}
    paths = {c['cid']: c['path'] for c in context.get('categories') or []}
    category = output.get('category')
    if category and category['cid'] in paths:
        result['category'] = {**category, 'path': paths[category['cid']]}
    weight = output.get('weight')
    if weight and bounded(weight['value'], .001, 100):
        result['weight'] = weight
    package = output.get('package')
    if package and all(bounded(package[k], 1, 1000) for k in ('length', 'width', 'height')):
        result['package'] = package
    keys = set(content.get('skuMap') or {})
    result['sku_weights'] = [x for x in output.get('sku_weights') or [] if x['sku_key'] in keys and bounded(x['weight'], .001, 100)]
    rules = context.get('rules') or {}
    def checked(rule, value_ids, custom):
        allowed = {v['id'] for v in rule['values']}
        ids = [x for x in dict.fromkeys(value_ids) if x in allowed]
        custom = [x.strip() for x in dict.fromkeys(custom) if x.strip()] if rule['customizable'] else []
        return ids, custom
    product_rules = {r['attr_id']: r for r in rules.get('product') or []}
    for attr in output.get('attributes') or []:
        rule = product_rules.get(attr['attr_id'])
        if not rule:
            continue
        ids, custom = checked(rule, attr['value_ids'], attr['custom_values'])
        values = ids + custom
        if values and (rule['multiple'] or len(values) == 1):
            result['attributes'].append({'attr_id': rule['attr_id'], 'name': rule['name'], 'value_ids': ids,
                                         'custom_values': custom, 'reason': attr['reason']})
    sale_rules = {r['attr_id']: r for r in rules.get('sale') or []}
    for spec in output.get('sale_specs') or []:
        rule = sale_rules.get(spec['attr_id'])
        if not rule:
            continue
        values = []
        for value in spec['values']:
            ids, custom = checked(rule, [value['value_id']] if value['value_id'] else [], [value['custom_value']])
            if ids or custom:
                values.append({'source_value': value['source_value'], 'value_id': (ids or custom)[0]})
        if values:
            result['sale_specs'].append({'source_property': spec['source_property'], 'attr_id': rule['attr_id'],
                                         'name': rule['name'], 'values': values})
    return result


def initial_content(snapshot):
    detail = (snapshot.get('raw_data') or {}).get('detail_response', {}).get('data', {}).get('editCommonCollectBoxDetail', {})
    hints = source_hints(snapshot)
    content = EditorialContent(title=snapshot.get('name') or '', notes=snapshot.get('description') or '',
        imgUrls=list(dict.fromkeys(([snapshot['main_image']] if snapshot.get('main_image') else []) + (snapshot.get('images') or []))),
        descImgUrls=hints['desc_images'], sourceAttributes=[a for a in hints['attributes'] if a['name']])
    for field in ('weight', 'packageLength', 'packageWidth', 'packageHeight'):
        value = detail.get(field)
        if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
            setattr(content, field, value)
    # Keep original variant identifiers, but require an operator to set selling price and warehouse stock.
    properties = []
    for field, name in (('colorMap', detail.get('colorPropName') or 'Color'),
                        ('sizeMap', detail.get('sizePropName') or 'Size'),
                        ('saleProp3Map', detail.get('saleProp3Name') or 'Variant')):
        values = detail.get(field) or {}
        if values:
            properties.append({'attrId': '', 'attrName': name, 'attrValueList': [
                {'attrValueId': str(key), 'attrValue': val.get('name', ''), 'imgUrl': val.get('imgUrl', '')}
                for key, val in values.items()]})
    content.skuPropertyList = properties
    source_skus = detail.get('skuMap') or {x.get('sku_id', str(i)): x for i, x in enumerate(snapshot.get('skus') or [])}
    # Miaoshou's SKU price is what its editor shows as 货源价格; the sale price stays for the operator.
    content.skuMap = {str(key): {'itemNum': val.get('itemNum') or val.get('sku_id') or '',
                                'price': None, 'stock': None, 'isDelete': '0', 'weight': val.get('weight'),
                                'originPrice': bounded(val.get('price') if detail else val.get('purchase_price'), 0, 1e7),
                                'shopIdToWarehouseIdAndStockMap': {}}
                      for key, val in source_skus.items()}
    if not detail and source_detail(snapshot)[1]:
        # 1688 CLI records: build specs from options and key SKUs by value names (the Miaoshou
        # convention above), so rows line up with specs instead of raw 1688 sku ids.
        content.weight = hints['fields'].get('weight', {}).get('value')
        groups = [[v for v in spec['values'] if ';' not in v['name']] for spec in hints['specs']]
        skus = {}
        for sku in hints['skus']:
            if len(sku['names']) == len(groups) and all(sum(n in {v['name'] for v in g} for n in sku['names']) == 1 for g in groups):
                skus[sku_key([n[:100] for n in sku['names']])] = {'itemNum': sku['item_num'], 'price': None, 'stock': None,
                    'isDelete': '0', 'weight': sku['weight'], 'originPrice': sku['purchase_price'], 'shopIdToWarehouseIdAndStockMap': {}}
        content.skuPropertyList = [{'attrId': '', 'attrName': spec['name'], 'attrValueList': [
            {'attrValueId': v['name'][:100], 'attrValue': v['name'][:255], 'imgUrl': v['image']} for v in group]}
            for spec, group in zip(hints['specs'], groups)] if skus else []
        content.skuMap = skus
    if not content.skuMap:
        content.skuMap = {';': {'itemNum': '', 'price': None, 'stock': None, 'isDelete': '0',
                              'shopIdToWarehouseIdAndStockMap': {}}}
    return content.model_dump(mode='json')


async def shop_for(client, market, shop_id):
    # Do not trust caller-provided shop currencies or cross-site shop identifiers.
    for page in range(1, 101):
        result = await client.get_shops('tiktok', market, page=page, page_size=100)
        rows = result.data['shopList']
        found = next((x for x in rows if str(x.get('shopId')) == str(shop_id) and x.get('site') == market
                      and x.get('platform') == 'tiktok'), None)
        if found:
            return found
        if len(rows) < 100:
            break
    raise HTTPException(422, '店铺不在已授权的目标站点中')


def notes(content):
    bullets = [x.strip() for x in content.get('bullet_points') or [] if x.strip()]
    return '\n'.join(['• ' + x for x in bullets] + [content.get('notes') or '']).strip()


def description(content):
    """详细描述 sent as `notes`: plain text as before, or generated HTML (escaped text, then the
    detail images in order) once detail images exist. Source HTML is never passed through."""
    images = content.get('descImgUrls') or []
    if not images:
        return notes(content)
    parts = []
    bullets = [b.strip() for b in content.get('bullet_points') or [] if b.strip()]
    if bullets:
        parts.append('<ul>' + ''.join(f'<li>{html.escape(b)}</li>' for b in bullets) + '</ul>')
    parts += [f'<p>{html.escape(line.strip())}</p>' for line in (content.get('notes') or '').splitlines() if line.strip()]
    parts += [f'<img src="{html.escape(url, quote=True)}"/>' for url in images]
    return ''.join(parts)


def normalize_notes(value):
    """Readback comparison tolerant of whitespace and self-closing tag serialization."""
    return re.sub(r'\s*/?>', '>', re.sub(r'\s+', ' ', str(value or ''))).strip()


# Fields that only make sense together: if one is unfinished, the whole group keeps Miaoshou's values.
SYNC_GROUPS = {field: group for group in (('cid', 'productAttributes', 'productCertifications'),
                                          ('skuMap', 'skuPropertyList'), ('sizeChart', 'sizeChartType'))
               for field in group}


def unsynced_fields(validation):
    """Remote fields left as they are in Miaoshou because the draft has unfinished values for them."""
    fields = set()
    for error in validation['errors']:
        fields.update(SYNC_GROUPS.get(error['field'], (error['field'],)))
    return sorted(f for f in fields if f in REMOTE_FIELDS)


PLATFORM_VALUE_ID = re.compile(r'[0-9]+|[0-9a-f]{10}')


def platform_value_ids(content):
    """Miaoshou's TikTok box keys custom sale values by short opaque ids (e.g. 1d31851e6f), not names.
    Give custom values a stable id derived from attribute+value and re-key the SKUs to match."""
    content = copy.deepcopy(content)
    ids = {}
    for prop in content.get('skuPropertyList') or []:
        for value in prop.get('attrValueList') or []:
            old = str(value.get('attrValueId') or '')
            if old and not PLATFORM_VALUE_ID.fullmatch(old):
                ids[old] = hashlib.md5(f"{prop.get('attrId') or ''}:{old}".encode()).hexdigest()[:10]
                value['attrValueId'] = ids[old]
    if ids:
        content['skuMap'] = {sku_key([ids.get(x, x) for x in key.split(';') if x]): sku for key, sku in (content.get('skuMap') or {}).items()}
    return content


def managed(content, exclude=()):
    # Empty brand / size-chart type mean "not set": leave Miaoshou's own defaults ('0', 'image') alone.
    exclude = set(exclude) | ({'brandId'} if not content.get('brandId') else set()) | ({'sizeChartType'} if not content.get('sizeChart') else set())
    result = {k: (description(content) if k == 'notes' else copy.deepcopy(content[k]))
              for k in REMOTE_FIELDS if k in content and k not in exclude}
    for sku in result.get('skuMap', {}).values():
        for key in list(sku):
            if sku[key] is None:
                sku.pop(key)
    return result


def normalize_remote(value):
    """Only compare fields this editor controls; ignore platform bookkeeping."""
    result = {k: copy.deepcopy(value.get(k)) for k in REMOTE_FIELDS}
    for field in ('imgUrls', 'skuPropertyList', 'productAttributes', 'productCertifications', 'manufacturerIds', 'responsiblePersonIds'):
        result[field] = result[field] or []
    for field in ('brandId', 'sizeChart', 'sizeChartType'):
        result[field] = result[field] or ''
    result['skuMap'] = result['skuMap'] or {}
    for sku in result['skuMap'].values():
        # Extra fields returned by the platform aren't edits made by the workbench.
        for key in list(sku):
            if key not in ('price', 'priceIncludeVat', 'originPrice', 'stock', 'itemNum', 'isDelete', 'weight',
                           'shopIdToWarehouseIdAndStockMap', 'preSale'):
                sku.pop(key)
    return result


def matches_expected(remote, expected):
    """Readback must include every submitted value, while tolerating extra platform fields."""
    if isinstance(expected, dict):
        return isinstance(remote, dict) and all(k in remote and matches_expected(remote[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(remote, list) and len(remote) == len(expected) and all(matches_expected(a, b) for a, b in zip(remote, expected))
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return float(remote) == float(expected)
        except (ValueError, TypeError):
            return False
    return remote == expected


def enabled_flag(value):
    return value is True or str(value).lower() in ('1', 'true', 'yes', 'required')


def validate_content(content, shop_id, category, metadata, warehouses, market='MY'):
    errors = []
    def error(field, message):
        errors.append({'field': field, 'message': message})
    if not shop_id:
        error('shop_id', '请选择目标店铺')
    if not 25 <= len(content.get('title', '').strip()) <= 255:
        error('title', '标题须为 25–255 字符')
    if not description(content) or len(description(content)) > 10000:
        error('notes', '详细描述（卖点、文字与详情图）合计须为 1–10000 字符')
    if not 1 <= len(content.get('imgUrls', [])) <= 15:
        error('imgUrls', '商品图须为 1–15 张')
    for field, low, high in [('weight', .001, 100), ('packageLength', 1, 1000), ('packageWidth', 1, 1000), ('packageHeight', 1, 1000)]:
        value = content.get(field)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
            error(field, f'{field} 须为 {low}–{high}（重量 kg，尺寸 cm）')
    if not category or enabled_flag(category.get('disabled')) or not enabled_flag(category.get('isLastLevel')):
        error('cid', '请选择有效的末级类目')
    config = metadata.get('categoryConfig') or {}
    if enabled_flag(config.get('eprIsRequired')):
        error('productAttributes', '该类目要求 EPR 资料，当前保存接口未提供可核实字段，不能标记草稿检查通过')
    if content.get('sizeChart') and content.get('sizeChartType') != 'image':
        error('sizeChartType', '尺码表类型须为 image')
    for flags, field, message in [(['sizeChartIsRequired', 'isSizeChartMandatory'], 'sizeChart', '该类目必须提供尺码表图片'),
            (['manufacturerIsRequired'], 'manufacturerIds', '该类目必须提供制造商 ID'),
            (['responsiblePersonIsRequired'], 'responsiblePersonIds', '该类目必须提供责任人 ID')]:
        if any(enabled_flag(config.get(flag)) for flag in flags) and not content.get(field):
            error(field, message)
    if content.get('isCodOpen') == '1' and not (enabled_flag(config.get('isSuppCod')) or enabled_flag(config.get('codIsSupported'))):
        error('isCodOpen', '该类目未确认支持货到付款')
    chosen = {str(a.get('attributeId')): a.get('attributeValues') or [] for a in content.get('productAttributes', [])}
    sale_chosen = {str(a.get('attrId')): a.get('attrValueList') or [] for a in content.get('skuPropertyList', [])}
    selected_ids = {str(v.get('valueId') or v.get('attrValueId')) for values in [*chosen.values(), *sale_chosen.values()] for v in values}
    def conditions_apply(conditions):
        if not conditions:
            return False
        if not isinstance(conditions, list):
            # Unspecified condition wire format must not silently waive a requirement.
            error('productAttributes', '类目条件规则格式尚不能确认，请在妙手核实后重试')
            return True
        return any(str(c.get('attributeValueId')) in selected_ids for c in conditions)
    for rules, selections, field in [(metadata.get('categoryProductAttrList') or [], chosen, 'productAttributes'),
                                     (metadata.get('categorySaleAttrList') or [], sale_chosen, 'skuPropertyList')]:
        rules_by_id = {str(r.get('attrId')): r for r in rules}
        required = set()
        for rule in rules:
            rid = str(rule.get('attrId'))
            if enabled_flag(rule.get('isMandatory')) or market in (rule.get('requiredRegions') or []) or conditions_apply(rule.get('requirementConditions')):
                required.add(rid)
            for value_id, dependent in (rule.get('valueIdAndRequiredAttrIdsMap') or {}).items():
                if value_id in selected_ids:
                    required.update(str(x) for x in dependent)
        for rid in required:
            if not selections.get(rid):
                error(field, f'请补充必填属性：{rules_by_id.get(rid, {}).get("name", rid)}')
        names = ({str(a.get('attrId')): a.get('attrName') for a in content.get('skuPropertyList', [])} if field == 'skuPropertyList'
                 else {str(a.get('attributeId')): a.get('attributeName') for a in content.get('productAttributes', [])})
        for rid, values in selections.items():
            rule = rules_by_id.get(rid)
            if not rule:
                name = names.get(rid) or rid
                error(field, f'销售规格「{name}」还没有对应到当前类目的销售属性：在「销售属性 / SKU」中为它选择对应属性'
                      if field == 'skuPropertyList' else f'属性「{name}」不属于当前类目：请在「产品属性」中重新选择')
                continue
            if len(values) > 1 and not enabled_flag(rule.get('isMultipleSelected')) and field == 'productAttributes':
                error(field, f'{rule.get("name")} 不支持多选')
            allowed = {str(v.get('id')) for v in rule.get('values') or []}
            for v in values:
                vid = str(v.get('valueId') or v.get('attrValueId') or '')
                # Miaoshou stores a custom product attribute value by name only (valueId null).
                custom_by_name = field == 'productAttributes' and enabled_flag(rule.get('isCustomized')) and v.get('valueName')
                if (not vid and not custom_by_name) or (vid and vid not in allowed and not enabled_flag(rule.get('isCustomized'))):
                    error(field, f'{rule.get("name")} 的属性值无效')
                if not (v.get('valueName') or v.get('attrValue')):
                    error(field, '属性值名称不能为空')
    certs = {str(x.get('id')): x for x in content.get('productCertifications', [])}
    required_certs = set()
    for cert in config.get('productCertifications') or []:
        if enabled_flag(cert.get('isRequired')) or enabled_flag(cert.get('isMandatory')) or conditions_apply(cert.get('requirementConditions')):
            required_certs.add(str(cert.get('id')))
    for rule in [*(metadata.get('categorySaleAttrList') or []), *(metadata.get('categoryProductAttrList') or [])]:
        for vid, ids in (rule.get('valueIdAndRequiredCertificationIdsMap') or {}).items():
            if vid in selected_ids:
                required_certs.update(str(x) for x in ids)
    for cid in required_certs:
        if not certs.get(cid, {}).get('files'):
            error('productCertifications', f'请提供类目要求的认证文件：{cid}')
    active_warehouses = {str(w.get('warehouseId')) for s in warehouses.get('shopWarehouseList') or []
                        if str(s.get('shopId')) == str(shop_id) for w in s.get('warehouseList') or []
                        if str(w.get('warehouseEffectStatus')).lower() not in ('0', 'false', 'disabled', 'inactive')}
    value_groups = [{str(v.get('attrValueId')) for v in x.get('attrValueList') or []} for x in content.get('skuPropertyList', [])]
    sku_keys = set()
    active_skus = [x for x in (content.get('skuMap') or {}).items() if str(x[1].get('isDelete', '0')) != '1']
    if not active_skus:
        error('skuMap', '至少需要一个有效 SKU')
    for key, sku in active_skus:
        ids = key.strip(';').split(';') if key != ';' else []
        ordered = sorted(ids, key=lambda x: (0, int(x)) if x.isdecimal() else (1, x))
        if key != ';' + ';'.join(ordered) + ';' and not (not ids and key == ';'):
            error('skuMap', f'SKU {key} 的 key 必须为排序后的属性值 ID 组合')
        if len(ids) != len(value_groups) or any(len(set(ids) & group) != 1 for group in value_groups) or len(set(ids)) != len(ids):
            error('skuMap', f'SKU {key} 与销售规格不一致')
        combination = tuple(sorted(ids))
        if combination in sku_keys:
            error('skuMap', 'SKU 规格组合重复')
        sku_keys.add(combination)
        price = sku.get('price')
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            error('skuMap', f'SKU {key} 请设置正数销售价')
        if sku.get('weight') is not None and not .001 <= sku['weight'] <= 100:
            error('skuMap', f'SKU {key} 重量须为 0.001–100 kg')
        allocations = (sku.get('shopIdToWarehouseIdAndStockMap') or {}).get(str(shop_id)) or {}
        if not isinstance(allocations, dict) or not allocations:
            error('skuMap', f'SKU {key} 请设置店铺仓库库存')
        else:
            for warehouse_id, stock in allocations.items():
                if warehouse_id not in active_warehouses or type(stock) is not int or stock < 0:
                    error('skuMap', f'SKU {key} 仓库或库存无效')
            if type(sku.get('stock')) is not int or sku['stock'] != sum(v for v in allocations.values() if type(v) is int):
                error('skuMap', f'SKU {key} 总库存须与仓库库存一致')
    return {'valid': not errors, 'errors': errors, 'checked_at': now().isoformat()}


def find_category(tree, cid):
    nodes = tree.values() if isinstance(tree, dict) else tree if isinstance(tree, list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if str(node.get('cid')) == str(cid):
            return node
        found = find_category(node.get('children') or {}, cid)
        if found:
            return found
    return None


async def preflight(client, draft):
    if not draft.shop_id:
        return validate_content(draft.content, None, None, {}, {}, draft.market)
    await shop_for(client, draft.market, draft.shop_id)
    categories = await client.get_categories(draft.market)
    category = find_category(categories.data.get('cateTree') or {}, draft.content.get('cid'))
    metadata = (await client.get_category_metadata(draft.market, draft.content['cid'], draft.shop_id)).data.get('categoryMetadata') or {} if category else {}
    warehouses = (await client.get_warehouses(draft.shop_id)).data
    return validate_content(draft.content, draft.shop_id, category, metadata, warehouses, draft.market)


async def enqueue(db, draft, user, data, kind, settings):
    await db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    fingerprint = digest({'draft_id': str(draft.id), 'kind': kind, 'input': data.model_dump(mode='json')})
    old = await db.scalar(select(Task).where(Task.owner_id == user.id, Task.request_key == data.request_key))
    if old:
        if old.fingerprint != fingerprint:
            raise HTTPException(409, 'request_key 已用于不同操作')
        return old, True
    if kind == 'sync':
        active = await db.scalar(select(Task).where(Task.draft_id == draft.id, Task.kind == 'sync', Task.status.in_(ACTIVE)))
        if active:
            raise HTTPException(409, '已有同步任务，请先查询或恢复该任务')
    require_version(draft, data.version)
    snapshot = {'content': copy.deepcopy(draft.content), 'source': copy.deepcopy(draft.source_snapshot),
                'shop_id': draft.shop_id, 'market': draft.market, 'currency': draft.currency, 'language': draft.language,
                'config': {**settings.public_config(), 'base_url': settings.bailian_base_url,
                           'image_base_url': settings.workbench_image_base_url or settings.bailian_base_url,
                           'dashscope_base_url': settings.workbench_dashscope_base_url},
                'operation': data.model_dump(mode='json'), 'remote_snapshot': copy.deepcopy(draft.remote_snapshot),
                'common_detail_id': draft.common_detail_id, 'platform_detail_id': draft.platform_detail_id}
    if kind in model_settings.KIND_SCENARIO:
        # The model chosen in system settings is frozen into the snapshot, so a resumed task keeps it.
        models = await model_settings.effective_models(db, settings)
        config = snapshot['config']
        config['scenario'] = model_settings.KIND_SCENARIO[kind]
        if kind in ('ocr', 'copy', 'fill'):
            config['text_model'] = models[config['scenario']]
        config['image_model'], config['translation_model'] = models['workbench_image'], models['workbench_translate']
    task = Task(owner_id=user.id, draft_id=draft.id, request_key=data.request_key, fingerprint=fingerprint,
                kind=kind, input_version=draft.version, snapshot=snapshot, steps={}, result={})
    db.add(task)
    await db.flush()
    return task, False
