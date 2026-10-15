"""Pure unit tests; fixture keys/responses never validate real API access."""
import hashlib
import hmac
import json
import httpx
import pytest
from app.clients.miaoshou_client import MiaoshouClient, MiaoshouError, RequestLimiter, FETCH, LIST, DETAIL, SHOPS, sign_body, serialize_body
from app.services.sourcing_config import SourcingSettings


class NoWait(RequestLimiter):
    async def wait(self, interval): pass


def client(handler):
    return MiaoshouClient(SourcingSettings(_env_file=None, miaoshou_app_key='UNIT_KEY', miaoshou_app_secret='UNIT_SECRET'), httpx.MockTransport(handler), NoWait())


def test_known_utf8_signature():
    body = b'{"collectLinks":["https://detail.1688.com/offer/635021027818.html"]}'
    expected = hmac.new(b'UNIT_SECRET', b'UNIT_SECRET' + FETCH.encode() + b'1700000000UNIT_KEY' + body + b'UNIT_SECRET', hashlib.sha256).hexdigest()
    assert sign_body('UNIT_SECRET', 'UNIT_KEY', FETCH, 1700000000, body) == expected
    encoded = serialize_body({'title': '中文软毛刷', 'price': 1.7})
    assert encoded == '{"title":"中文软毛刷","price":1.7}'.encode('utf-8')
    assert sign_body('UNIT_SECRET', 'UNIT_KEY', DETAIL, 1700000000, encoded) != sign_body('UNIT_SECRET', 'UNIT_KEY', DETAIL, 1700000000, encoded + b' ')


@pytest.mark.asyncio
async def test_four_wire_contracts_and_exact_signed_bytes():
    seen = []
    async def handle(request):
        seen.append(request.url.path)
        expected = sign_body('UNIT_SECRET', 'UNIT_KEY', request.url.path, request.headers['x-timestamp'], request.content)
        assert request.headers['x-sign'] == expected
        assert request.method == 'POST' and not request.url.query
        payload = json.loads(request.content)
        if request.url.path == SHOPS:
            assert payload == {'platform': 'tiktok', 'site': 'TH', 'pageNo': 1, 'pageSize': 20}
            data = {'shopList': []}
        elif request.url.path == FETCH:
            assert set(payload) == {'collectLinks'}
            data = {'sourceItemIdAndDetailIdMap': {'635021027818': 42}}
        elif request.url.path == LIST:
            assert payload['filter'] == {'tabPaneName': 'all', 'sourceItemIdKeyword': '635021027818'}
            data = {'detailList': [{'commonCollectBoxDetailId': 42}], 'total': 1}
        else:
            assert payload == {'commonCollectBoxDetailId': 42}
            data = {'editCommonCollectBoxDetail': {'title': 'UNIT_ONLY', 'price': None, 'stock': 0, 'weight': 0.025, 'skuMap': {'k': {'price': 2.3, 'oriPrice': 1.8}}}}
        return httpx.Response(200, json={'result': 'success', 'code': 'success', 'data': data})
    c = client(handle)
    await c.get_shops('tiktok', 'TH')
    assert (await c.fetch_items(['https://detail.1688.com/offer/635021027818.html'])).data['sourceItemIdAndDetailIdMap']['635021027818'] == 42
    await c.get_common_list(source_id='635021027818')
    d = await c.get_common_detail('42')
    assert d.data['editCommonCollectBoxDetail']['price'] is None
    assert d.data['editCommonCollectBoxDetail']['skuMap']['k']['price'] == 2.3
    assert seen == [SHOPS, FETCH, LIST, DETAIL]


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 500])
@pytest.mark.parametrize('code,category', [('signInvalid','auth'), ('appNoPermission','permission'), ('ipNotInWhitelist','permission'), ('accountApiQpsRateLimit','rate_limit'), ('upstreamReadTimeout','upstream')])
async def test_error_classification_and_redaction(code, category, status, caplog):
    async def handle(request):
        return httpx.Response(status, json={'result': 'fail', 'code': code, 'reason': 'MUST_NOT_LOG UNIT_SECRET UNIT_KEY', 'data': None})
    with pytest.raises(MiaoshouError) as exc:
        await client(handle).get_common_list()
    assert exc.value.category == category
    assert 'UNIT_SECRET' not in str(exc.value) + caplog.text and 'UNIT_KEY' not in caplog.text


@pytest.mark.asyncio
async def test_http_500_auth_error_is_classified_without_write_retry():
    calls = 0
    async def handle(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={'result': 'error', 'code': 'signInvalid', 'reason': 'UNIT_SECRET'})
    with pytest.raises(MiaoshouError) as exc:
        await client(handle).fetch_items(['https://detail.1688.com/offer/635021027818.html'])
    assert calls == 1 and exc.value.category == 'auth' and not exc.value.uncertain


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['timeout', 'broken_json', 'server_error', 'broken_map'])
async def test_write_never_retries_and_marks_unknown(failure):
    calls = 0
    async def handle(request):
        nonlocal calls
        calls += 1
        if failure == 'timeout': raise httpx.ReadTimeout('UNIT_SECRET', request=request)
        if failure == 'broken_json': return httpx.Response(200, text='not json')
        if failure == 'server_error': return httpx.Response(503)
        return httpx.Response(200, json={'result': 'success', 'code': 'success', 'data': {'sourceItemIdAndDetailIdMap': {'a': '42'}}})
    with pytest.raises(MiaoshouError) as exc:
        await client(handle).fetch_items(['https://detail.1688.com/offer/635021027818.html'])
    assert calls == 1 and exc.value.uncertain
    assert 'UNIT_SECRET' not in str(exc.value)


@pytest.mark.asyncio
async def test_invalid_limits_and_no_publish_operation():
    async def handle(request): raise AssertionError('Must not request upstream')
    c = client(handle)
    with pytest.raises(MiaoshouError): await c.fetch_items(['url'] * 51)
    with pytest.raises(MiaoshouError): await c.get_common_detail('-1')
    with pytest.raises(MiaoshouError): await c.get_common_list(page_size=501)
    # Unlisted operations (e.g. deleting collect-box products) stay blocked.
    with pytest.raises(MiaoshouError): await c.post_json('/open/v1/product/collect_box/tiktok/collect_box/batch_delete_collect_box_detail', {}, dict)
    with pytest.raises(MiaoshouError): await c.publish([], ['1'])
    with pytest.raises(MiaoshouError): await c.publish(['1'] * 201, ['1'])
    with pytest.raises(MiaoshouError): await c.publish(['-1'], ['1'])
    with pytest.raises(MiaoshouError): await c.get_publish_records(page_size=101)


@pytest.mark.asyncio
async def test_publish_sends_once_and_timeout_is_uncertain():
    calls = []
    async def handle(request):
        calls.append(json.loads(request.content))
        raise httpx.ReadTimeout('UNIT')
    with pytest.raises(MiaoshouError) as exc:
        await client(handle).publish(['3454529857'], ['19282337'])
    assert calls == [{'shopIds': [19282337], 'detailIds': [3454529857]}] and exc.value.uncertain


@pytest.mark.asyncio
async def test_rate_gate_orders_calls():
    import time
    limiter = RequestLimiter()
    await limiter.wait(0.02)
    before = time.monotonic()
    await limiter.wait(0.02)
    # Windows' coarse monotonic clock may yield 0.014999999999 from float subtraction.
    assert time.monotonic() - before + 1e-9 >= 0.015


@pytest.mark.asyncio
async def test_business_rejection_of_a_write_shows_scrubbed_reason_and_is_definite(caplog):
    async def handle(request):
        return httpx.Response(200, json={'result': 'fail', 'code': 'fail', 'message': 'SKU 规格值不合法 UNIT_KEY\nUNIT_SECRET', 'data': None})
    with pytest.raises(MiaoshouError) as exc:
        await client(handle).save_shop_detail(77, 99, 'UNIT_MD5', {'title': 'UNIT_ONLY'})
    assert 'SKU 规格值不合法' in exc.value.message and '[redacted]' in exc.value.message
    assert 'UNIT_KEY' not in exc.value.message and 'UNIT_SECRET' not in exc.value.message + caplog.text
    assert exc.value.category == 'platform' and not exc.value.uncertain
