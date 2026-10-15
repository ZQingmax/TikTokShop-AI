"""Conservative conversion: keep source strings and never invent observation dates."""
import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from app.schemas.sourcing import public_url
from .config import MARKETS


def number(value, integer=False):
    raw = str(value or '').strip().replace(',', '')
    # 货币符号可能在前（RM12.5、Rp 9000、S$3）或在后（1711755 ₫）；区间、≥ 等不解析
    match = re.fullmatch(r'(?:[A-Z]{3}\s*|RM\s*|Rp\s*|S\$\s*|[¥￥$฿₱₫]\s*)?(\d+(?:\.\d+)?)\s*([kKmMbB万亿]?)\s*(?:[A-Z]{3}|[¥￥฿₱₫])?', raw)
    if not match:
        return None
    # 印尼盾、越南盾习惯用“.”作千分位：Rp 12.000 可能是一万二，无法确定时保留原文、数值未知
    if re.search(r'Rp|IDR|VND|₫', raw) and re.fullmatch(r'\d+(?:\.\d{3})+', match[1]):
        return None
    try:
        factor = {'k': 1000, 'm': 1000000, 'b': 1000000000, '万': 10000, '亿': 100000000}.get(match[2].lower(), 1)
        value = Decimal(match[1]) * factor
        if not value.is_finite() or value > Decimal('1e18'):
            return None
        if integer:
            return int(value) if value == value.to_integral_value() else None
        return format(value, 'f')
    except InvalidOperation:
        return None


def currency(value):
    raw = str(value or '').strip()
    for prefix, code in [('RM', 'MYR'), ('MYR', 'MYR'), ('USD', 'USD'), ('SGD', 'SGD'), ('S$', 'SGD'), ('THB', 'THB'),
                         ('VND', 'VND'), ('PHP', 'PHP'), ('IDR', 'IDR'), ('Rp', 'IDR'), ('CNY', 'CNY'),
                         ('฿', 'THB'), ('₱', 'PHP'), ('₫', 'VND')]:
        if raw.startswith(prefix):
            return code
    for suffix, code in [('₫', 'VND'), ('VND', 'VND'), ('฿', 'THB'), ('THB', 'THB'), ('₱', 'PHP'), ('MYR', 'MYR')]:
        if raw.endswith(suffix):
            return code
    return None  # '$' alone does not identify a currency.


def source_url(value):
    url = public_url(value)
    host = urlsplit(url).hostname
    if not (host == 'fastmoss.com' or host.endswith('.fastmoss.com')):
        raise ValueError('FastMoss 来源链接必须属于 fastmoss.com')
    return url


def normalize_rows(raw_rows, market, fallback_url='', fetched_at=None, category=None):
    result = []
    for index, raw in enumerate(raw_rows, 2):
        name = str(raw.get('product_name') or '').strip()
        if not name or len(name) > 500:
            raise ValueError(f'第 {index} 行商品名称为空或过长')
        country = str(raw.get('country') or '').strip()
        if country and country not in (market, MARKETS[market]):
            raise ValueError(f'第 {index} 行国家与本次导入地区不一致')
        product_url = raw.get('product_url') or ''
        url = source_url(product_url or raw.get('source_url') or fallback_url)
        observed = raw.get('observed_on') or None
        if observed:
            observed = date.fromisoformat(observed).isoformat()
        image = raw.get('image_url') or None
        if image:
            image = public_url(image)
        rank = number(raw.get('rank'), True)
        if rank == 0:
            rank = None
        cat_name = raw.get('category') or '未分类'
        row = dict(row_number=index, name=name, source_platform='FastMoss', source_url=url,
                   source_kind='product' if product_url else 'ranking', target_market=market,
                   observed_on=observed, fetched_at=fetched_at, category=cat_name, image_url=image,
                   rank=rank, sales=number(raw.get('sales_period'), True), revenue=number(raw.get('gmv_period')),
                   price=number(raw.get('price')), currency=currency(raw.get('price')),
                   period=raw.get('period') or None, shop=raw.get('shop') or None,
                   total_sales=number(raw.get('total_sales'), True), total_revenue=number(raw.get('total_gmv')),
                   raw=dict(raw), category_paths=[category['path']] if category else [],
                   rankings=[{'category_id': category['id'] if category else None,
                              'category': ' / '.join(category['path']) if category else cat_name,
                              'rank': rank, 'observed_on': observed, 'period': raw.get('period') or None,
                              'source_url': source_url(raw.get('source_url') or fallback_url or url), 'raw': dict(raw)}])
        result.append(row)
    return result


def merge_rows(rows):
    merged = {}
    for row in rows:
        # Without a source product identity do not conflate similarly named products.
        key = (row['target_market'], row['source_url']) if row['source_kind'] == 'product' else (
            row['target_market'], row['name'], row['shop'], row['category'], row['raw'].get('price'),
            tuple(row['category_paths'][0]) if row['category_paths'] else ())
        if key not in merged:
            merged[key] = {**row, 'rankings': list(row['rankings']), 'category_paths': list(row['category_paths'])}
        else:
            existing = merged[key]
            def evidence_key(evidence):
                return {**evidence, 'raw': {k: v for k, v in evidence.get('raw', {}).items() if k != 'page'}}
            for evidence in row['rankings']:
                if not any(evidence_key(evidence) == evidence_key(old) for old in existing['rankings']):
                    existing['rankings'].append(evidence)
            for path in row['category_paths']:
                if path not in existing['category_paths']:
                    existing['category_paths'].append(path)
            if len(existing['rankings']) > 1:
                existing['rank'] = None
    return [{**r, 'row_number': i} for i, r in enumerate(merged.values(), 2)]


def encode_csv(rows):
    buffer = io.StringIO(newline='')
    fields = list(dict.fromkeys(k for row in rows for k in row))
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return '\ufeff' + buffer.getvalue()


def parse_fastmoss_csv(content, market, fallback_url):
    reader = csv.DictReader(io.StringIO(content.lstrip('\ufeff')))
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError('FastMoss CSV 表头重复或为空')
    if not {'product_name', 'country'} <= set(reader.fieldnames):
        raise ValueError('缺少 FastMoss 商品名称或国家字段')
    raw_rows = list(reader)
    if not 1 <= len(raw_rows) <= 500:
        raise ValueError('请提供 1–500 条记录')
    if any(None in r for r in raw_rows):
        raise ValueError('CSV 列数超过表头')
    if any(str(v or '').lstrip().startswith(('=', '+', '@')) for r in raw_rows for v in r.values()):
        raise ValueError('不接受公式，请粘贴为值后导入')
    return merge_rows(normalize_rows(raw_rows, market, fallback_url))
