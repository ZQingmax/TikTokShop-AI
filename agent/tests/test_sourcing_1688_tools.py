"""1688 货源工具测试：后端由 httpx.MockTransport 代替，数据均为 TEST_ONLY 夹具。"""

import asyncio
import json

import httpx
import pytest

from app.config import agent_settings
from app.tools import alibaba_tools as tools

ITEM = {'offer_id': '700000000001', 'title': 'TEST_ONLY 露营灯', 'price': {'text': '¥10', 'min': 10, 'max': 12},
        'sales': {'text': '50', 'count': 50}, 'supplier': {'name': 'TEST_ONLY'}, 'location': {'province': '广东', 'city': None},
        'min_order_quantity': None, 'product_url': 'https://detail.1688.com/offer/700000000001.html', 'main_image': None}


@pytest.fixture
def backend(monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path.endswith('/search'):
            return httpx.Response(200, json={'items': [ITEM], 'total': 1})
        if request.url.path.endswith('/products/700000000099'):
            return httpx.Response(424, json={'detail': {'state': 'not_logged_in', 'message': '1688 未登录', 'hint': '1688 login'}})
        if request.url.path.endswith('/candidates'):
            return httpx.Response(201, json={'id': 'x', 'status': 'imported'})
        if request.url.path.endswith('/image-search'):
            return httpx.Response(200, json={'items': [ITEM]})
        return httpx.Response(404, json={'detail': '请求的资源不存在'})

    monkeypatch.setattr(tools, 'TRANSPORT', httpx.MockTransport(handler))
    monkeypatch.setattr(agent_settings, 'backend_api_token', 'TEST_ONLY_TOKEN')
    return seen


def test_search_calls_backend_provider_with_token_and_limits(backend):
    result = asyncio.run(tools.search_1688_products('露营灯', max_results=99, price_max=50))
    request = backend[0]
    assert result['ok'] and result['items'][0]['offer_id'] == '700000000001' and 'TikTok' in result['notice']
    assert request.url.path == '/api/v1/sourcing/1688/search' and request.url.params['max'] == '20'
    assert request.url.params['price_max'] == '50' and request.headers['authorization'] == 'Bearer TEST_ONLY_TOKEN'


def test_errors_are_returned_structured_without_retry(backend):
    result = asyncio.run(tools.get_1688_product_detail('700000000099'))
    assert result == {'ok': False, 'status_code': 424,
                      'error': {'state': 'not_logged_in', 'message': '1688 未登录', 'hint': '1688 login'}}
    assert len(backend) == 1


def test_save_candidate_only_saves(backend):
    result = asyncio.run(tools.save_sourcing_candidate('700000000001', 'VN'))
    assert result['status'] == 'imported' and json.loads(backend[0].content) == {
        'offer_id': '700000000001', 'target_market': 'VN', 'use_detail': True}


def test_image_search_rejects_urls_and_non_images(backend):
    assert asyncio.run(tools.search_1688_by_image('http://169.254.169.254/latest.jpg'))['error']['state'] == 'bad_input'
    assert asyncio.run(tools.search_1688_by_image('C:/Windows/win.ini'))['error']['state'] == 'bad_input'
    assert backend == []


def test_purchase_is_refused():
    result = asyncio.run(tools.create_1688_purchase_order([{'offer_id': '1', 'quantity': 1}]))
    assert result['ok'] is False and result['error']['state'] == 'human_confirmation_required'


def test_selection_mapping_does_not_treat_1688_sales_as_tiktok_sales():
    product = tools.to_selection_product(ITEM)
    assert product['sales_count'] is None and product['source_1688_order_count'] == 50
    assert product['rating'] is None and product['supplier_location'] == '广东'


def test_tools_register_as_langchain_tools():
    names = {t.name for t in tools.get_langchain_tools()}
    assert names == {'search_1688_products', 'get_1688_product_detail', 'search_1688_suppliers',
                     'search_1688_by_image', 'save_sourcing_candidate'}
    assert 'create_1688_purchase_order' not in names


def test_selection_node_searches_by_keyword(backend):
    from app.graph.nodes import selection_agent_node

    class NoLLM:
        async def rank_products(self, products, top_n, min_score):
            return []

    import app.graph.nodes as nodes
    original = nodes.selection_service
    nodes.selection_service = NoLLM()
    try:
        state = asyncio.run(selection_agent_node({'product_data': {'keyword': '露营灯'}, 'messages': []}))
    finally:
        nodes.selection_service = original
    assert state['product_data']['total_found'] == 1
    assert state['product_data']['candidates'][0]['product_id'] == '700000000001'
