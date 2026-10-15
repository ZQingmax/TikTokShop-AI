"""1688 货源工具（真实数据）：全部经后端 API 调用统一的 Alibaba1688Provider（1688 CLI，只读）。

Agent 不直接执行 CLI、不写爬虫；不提供采购、付款、联系卖家、上架工具。
基础搜索不依赖大模型密钥。失败时返回结构化错误（含状态与处理提示），不自动重试。
"""

from pathlib import Path
from typing import Any

import httpx

from app.config import agent_settings

NOTICE = '数据来自 1688（批发价，人民币）；1688 销量不等于 TikTok 销量，不能据此判定 TikTok 热销'
# 仅供测试注入 httpx.MockTransport；生产为 None
TRANSPORT: httpx.AsyncBaseTransport | None = None
IMAGE_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}


async def _call(method: str, path: str, **kwargs) -> dict[str, Any]:
    headers = {}
    if agent_settings.backend_api_token:
        headers['Authorization'] = f'Bearer {agent_settings.backend_api_token}'
    async with httpx.AsyncClient(base_url=agent_settings.backend_api_url, timeout=agent_settings.sourcing_tool_timeout,
                                 headers=headers, transport=TRANSPORT) as client:
        try:
            response = await client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            return {'ok': False, 'error': {'state': 'timeout', 'message': '后端 1688 查询超时'}}
        except httpx.HTTPError as e:
            return {'ok': False, 'error': {'state': 'backend_unreachable', 'message': f'无法连接后端：{type(e).__name__}'}}
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400:
        detail = body.get('detail') if isinstance(body, dict) else None
        if not isinstance(detail, dict):
            detail = {'state': 'http_error', 'message': str(detail or response.status_code)}
        return {'ok': False, 'status_code': response.status_code, 'error': detail}
    return {'ok': True, **body} if isinstance(body, dict) else {'ok': True, 'data': body}


async def search_1688_products(keyword: str, max_results: int = 20, sort: str = 'relevance',
                               price_min: float | None = None, price_max: float | None = None,
                               factory_only: bool = False, exclude_ads: bool = True) -> dict[str, Any]:
    """按关键词搜索 1688 真实商品（最多 20 条）。"""
    params = {'keyword': keyword, 'max': max(1, min(int(max_results), 20)), 'sort': sort,
              'exclude_ads': exclude_ads, 'factory_only': factory_only}
    if price_min is not None:
        params['price_min'] = price_min
    if price_max is not None:
        params['price_max'] = price_max
    result = await _call('GET', '/sourcing/1688/search', params=params)
    return {**result, 'notice': NOTICE}


async def get_1688_product_detail(offer_id: str) -> dict[str, Any]:
    """获取 1688 商品详情：SKU、阶梯价、起批量、包装、供应商、发货地。"""
    return await _call('GET', f'/sourcing/1688/products/{offer_id}')


async def search_1688_suppliers(keyword: str, max_results: int = 20, factory_only: bool = False) -> dict[str, Any]:
    """1688 企业搜索。platform_metrics 为平台指标；cli_score 为 1688-cli 本地参考分，非平台数据。"""
    params = {'keyword': keyword, 'max': max(1, min(int(max_results), 20)), 'factory_only': factory_only}
    return await _call('GET', '/sourcing/1688/suppliers/search', params=params)


async def search_1688_by_image(image_path: str, max_results: int = 20) -> dict[str, Any]:
    """以图搜图：只接受本机 JPG/PNG/WebP 文件路径，不接受 URL（避免访问任意内网地址）。"""
    path = Path(image_path)
    content_type = IMAGE_TYPES.get(path.suffix.lower())
    if '://' in image_path or not content_type:
        return {'ok': False, 'error': {'state': 'bad_input', 'message': '只支持本机 JPG、PNG、WebP 图片文件'}}
    if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
        return {'ok': False, 'error': {'state': 'bad_input', 'message': '图片不存在或超过 5 MB'}}
    files = {'image': (path.name, path.read_bytes(), content_type)}
    result = await _call('POST', '/sourcing/1688/image-search', files=files,
                         data={'max': str(max(1, min(int(max_results), 20)))})
    return {**result, 'notice': NOTICE}


async def save_sourcing_candidate(offer_id: str, target_market: str = 'TH', use_detail: bool = True) -> dict[str, Any]:
    """把 1688 商品加入候选库（仅保存待人工审核，不采购、不上架）。按平台 + Offer ID 去重。"""
    return await _call('POST', '/sourcing/1688/candidates',
                       json={'offer_id': offer_id, 'target_market': target_market, 'use_detail': use_detail})


def to_selection_product(item: dict[str, Any]) -> dict[str, Any]:
    """把 1688 搜索结果映射为选品评分输入。1688 订单数单独存放，不当作 TikTok 月销量。"""
    price = item.get('price') or {}
    supplier = item.get('supplier') or {}
    location = item.get('location') or {}
    return {
        'product_id': item.get('offer_id'),
        'title': item.get('title'),
        'price_range': price.get('text'),
        'min_price': price.get('min'),
        'max_price': price.get('max'),
        'sales_count': None,
        'source_1688_order_count': (item.get('sales') or {}).get('count'),
        'supplier_name': supplier.get('name'),
        'supplier_location': ' '.join(x for x in (location.get('province'), location.get('city')) if x) or None,
        'rating': None,
        'min_order_qty': item.get('min_order_quantity'),
        'product_url': item.get('product_url'),
        'main_image': item.get('main_image'),
        'data_note': NOTICE,
    }


async def create_1688_purchase_order(items: list[dict]) -> dict[str, Any]:
    """采购下单不对 Agent 开放：必须由人工在 1688 确认、付款。"""
    return {'ok': False, 'error': {'state': 'human_confirmation_required',
                                   'message': 'Agent 不允许自动采购、下单或付款；请人工在 1688 完成'}}


SOURCING_1688_TOOLS = {
    'search_1688_products': search_1688_products,
    'get_1688_product_detail': get_1688_product_detail,
    'search_1688_suppliers': search_1688_suppliers,
    'search_1688_by_image': search_1688_by_image,
    'save_sourcing_candidate': save_sourcing_candidate,
}


def get_langchain_tools() -> list:
    """注册为 LangChain StructuredTool，供 LangGraph Agent 绑定。"""
    from langchain_core.tools import StructuredTool

    return [StructuredTool.from_function(coroutine=fn, name=name, description=(fn.__doc__ or name).strip())
            for name, fn in SOURCING_1688_TOOLS.items()]
