"""1688 CLI 集成的纯单元测试（不连数据库、不联网、不使用真实 1688 账号）。

上游数据均为标注 TEST_ONLY 的脱敏夹具；子进程测试使用 fixtures/fake_1688_cli.js 模拟 CLI。
"""
import asyncio
import shutil
from pathlib import Path

import pytest

from app.services.alibaba1688 import normalize
from app.services.alibaba1688.commands import READ_ONLY_COMMANDS, build
from app.services.alibaba1688.config import Alibaba1688Settings
from app.services.alibaba1688.errors import Alibaba1688Error, classify
from app.services.alibaba1688.provider import Alibaba1688Provider, sniff_image
from app.services.alibaba1688.runner import CliResult, LocalCliTransport, child_env, parse_error

FAKE_CLI = Path(__file__).parent / 'fixtures' / 'fake_1688_cli.js'
NODE = shutil.which('node')

SEARCH = {'keyword': 'TEST_ONLY', 'sort': 'relevance', 'totalBeforeFilter': 60, 'total': 2, 'offers': [
    {'offerId': '700000000001', 'title': 'TEST_ONLY 露营灯', 'price': {'text': '¥14.5', 'min': 14.5, 'max': 14.5},
     'supplier': {'name': 'TEST_ONLY 照明厂', 'shopUrl': 'http://shoptest01.1688.com', 'years': 8},
     'location': {'province': '广东', 'city': '深圳市'}, 'bizType': '生产加工',
     'verified': {'factory': True, 'business': False, 'superFactory': False}, 'tags': ['TEST_ONLY'],
     'demand': {'orderCountText': '50', 'orderCount': 50, 'repurchaseRateText': None, 'repurchaseRate': None},
     'isP4P': False, 'turnover': '50', 'url': 'https://detail.1688.com/offer/700000000001.html',
     'image': 'https://img.example.test/1.jpg,https://img.example.test/2.jpg'},
    {'offerId': '700000000002', 'title': 'TEST_ONLY 马灯', 'price': {'text': '面议', 'min': None, 'max': None},
     'supplier': {}, 'isP4P': True, 'url': 'https://detail.1688.com/offer/700000000002.html', 'image': None}]}

OFFER = {'offerId': '700000000001', 'title': 'TEST_ONLY 露营灯 详情', 'url': 'https://detail.1688.com/offer/700000000001.html',
         'priceRange': '12.5-15', 'priceMin': 12.5, 'priceMax': 15, 'unitName': '个', 'minOrderQty': 2, 'mixOrderQty': None,
         'priceTiers': [{'minQty': 2, 'price': 15}, {'minQty': 100, 'price': 12.5}],
         'attributes': [{'name': '材质', 'value': 'ABS'}],
         'packageInfo': [{'skuId': '1', 'spec': '白色', 'length': 10, 'width': 10, 'height': 20, 'weight': 300, 'volume': None}],
         'supplier': {'name': 'TEST_ONLY 照明厂', 'loginId': 'test-seller', 'memberId': 'b2b-000000000test', 'userId': None},
         'freight': {'sendArea': '广东 深圳', 'province': '广东', 'city': '深圳', 'unitWeight': 0.3},
         'saledCount': 120, 'categoryId': '123', 'options': [{'prop': '颜色', 'values': [{'name': '白色', 'imageUrl': None}]}],
         'skus': [{'skuId': '1', 'specs': '白色', 'price': 12.5, 'multiPrice': None, 'stock': 100, 'saleCount': 3, 'image': None}],
         'mainImage': '//img.example.test/main.jpg', 'images': ['https://img.example.test/1.jpg']}

SUPPLIERS = {'queries': ['TEST_ONLY'], 'totalBeforeFilter': 3, 'total': 1, 'items': [{
    'sourceKeyword': 'TEST_ONLY', 'score': 71, 'scoreBreakdown': [{'name': 'years', 'points': 10, 'reason': 'TEST_ONLY'}],
    'supplier': {'companyName': 'TEST_ONLY 工厂', 'loginId': 'test-seller', 'memberId': 'b2b-000000000test',
                 'shopUrl': 'https://shoptest01.1688.com', 'location': {'province': '浙江', 'city': '金华', 'address': None},
                 'tp': {'serviceYears': 5, 'memberLevel': None}, 'factory': {'isFactory': True, 'superFactory': False},
                 'service': {'compositeScore': 4.5, 'wwResponseRate': 0.9, 'repeatRate': None, 'complianceRate': None},
                 'demand': {}, 'tags': [], 'offersPreview': [{'offerId': '700000000001', 'title': 'TEST_ONLY', 'price': {'text': '¥1'}}]}}]}


class FakeTransport:
    def __init__(self, responses=None, error=None):
        self.responses = responses or {}
        self.error = error
        self.calls = []

    def available(self):
        return True

    async def run(self, command, params, timeout, **extra):
        self.calls.append((command, params))
        if self.error:
            raise self.error
        return CliResult(self.responses[command], 3)


def provider(transport, **settings):
    return Alibaba1688Provider(Alibaba1688Settings(_env_file=None, min_interval=0, **settings), transport)


# ---- 命令白名单与参数校验 ----

def test_only_read_only_commands_are_whitelisted():
    for forbidden in ('login', 'logout', 'cart_add', 'checkout_confirm', 'seller_inquire', 'feedback'):
        assert forbidden not in READ_ONLY_COMMANDS
        with pytest.raises(Alibaba1688Error):
            build(forbidden, {}, 20)


def test_search_args_put_keyword_after_options():
    options, positional = build('search', {'keyword': ' 露营 灯 ', 'max': 20, 'sort': 'best-selling', 'price_min': 5,
                                           'price_max': '50.50', 'exclude_ads': True}, 20)
    assert options[:2] == ['search', '--max'] and '--exclude-ads' in options and options[-1] == '--json'
    assert options[options.index('--price-max') + 1] == '50.5' and positional == ['露营 灯']


@pytest.mark.parametrize('params', [{'keyword': ''}, {'keyword': '-h'}, {'keyword': '--profile x'}, {'keyword': 'x' * 51},
                                    {'keyword': 'a', 'max': 41}, {'keyword': 'a', 'max': 0}, {'keyword': 'a', 'sort': 'rm -rf'},
                                    {'keyword': 'a', 'price_min': -1}, {'keyword': 'a', 'price_min': 9, 'price_max': 1},
                                    {'keyword': 'a', 'price_min': 'nan'}])
def test_search_rejects_bad_input(params):
    with pytest.raises(Alibaba1688Error) as e:
        build('search', {'max': 20, **params}, 40 if params.get('max') == 41 else 20)
    assert e.value.state == 'bad_input'


@pytest.mark.parametrize('value', ['abc', '12', '1' * 21, '123456; rm -rf', '../etc/passwd', '-1234567'])
def test_offer_id_validation(value):
    with pytest.raises(Alibaba1688Error):
        build('offer', {'offer_id': value}, 20)


def test_supplier_target_accepts_offer_or_member_id():
    assert build('supplier_inspect', {'target': 'b2b-2201468533233'}, 20)[1] == ['b2b-2201468533233']
    assert build('supplier_inspect', {'target': '1054735896634'}, 20)[1] == ['1054735896634']
    with pytest.raises(Alibaba1688Error):
        build('supplier_inspect', {'target': 'shop74o9r93j52260'}, 20)


# ---- 错误分类 ----

@pytest.mark.parametrize('exit_code,code,details,state', [
    (3, 'NOT_LOGGED_IN', {}, 'not_logged_in'), (3, 'SESSION_EXPIRED', {}, 'login_expired'),
    (4, 'RISK_CONTROL', {}, 'risk_control'), (5, 'LOCK_BUSY', {}, 'busy'), (6, 'CHROMIUM_MISSING', {}, 'browser_error'),
    (9, 'NETWORK', {}, 'network_error'), (2, 'BAD_INPUT', {}, 'bad_input'),
    (9, 'DAEMON_PAUSED', {'failureKind': 'not_logged_in'}, 'not_logged_in'),
    (1, 'SOMETHING', {'category': 'auth'}, 'not_logged_in'), (1, 'X', {'pageState': 'risk_control'}, 'risk_control'),
    (1, None, {}, 'cli_error')])
def test_classify(exit_code, code, details, state):
    assert classify(exit_code, code, 'msg', details).state == state


def test_parse_error_ignores_update_notice_and_never_returns_urls_to_client():
    code, message, details = parse_error('Update available: 1.2.3\n{"ok":false,"code":"NOT_LOGGED_IN","message":"x",'
                                         '"details":{"currentUrl":"https://login.example.test/?token=SECRET"}}\n')
    assert code == 'NOT_LOGGED_IN'
    error = classify(3, code, message, details).to_dict()
    assert 'SECRET' not in str(error) and error['hint'] and error['state'] == 'not_logged_in'


def test_child_env_strips_backend_secrets(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'x')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://u:p@h/db')
    monkeypatch.setenv('MIAOSHOU_APP_SECRET', 'x')
    env = child_env(Alibaba1688Settings(_env_file=None, cli_home='C:/bb1688'))
    assert not {'DEEPSEEK_API_KEY', 'DATABASE_URL', 'MIAOSHOU_APP_SECRET'} & set(env)
    assert env['BB1688_HOME'] == 'C:/bb1688'


# ---- 标准化 ----

def test_search_normalization_keeps_nulls_and_raw():
    result = normalize.search_result(SEARCH, keyword='TEST_ONLY')
    a, b = result['items']
    assert a['images'] == ['https://img.example.test/1.jpg', 'https://img.example.test/2.jpg']
    assert a['main_image'] == a['images'][0] and a['price']['currency'] == 'CNY'
    assert a['min_order_quantity'] is None and a['sales']['count'] == 50 and a['supplier']['id'] is None
    assert a['verified']['factory'] is True and a['raw'] == SEARCH['offers'][0]
    assert b['price'] == {'text': '面议', 'min': None, 'max': None, 'currency': 'CNY'}
    assert b['supplier']['name'] is None and b['main_image'] is None and b['is_ad'] is True
    assert 'TikTok' in result['notice']


def test_offer_normalization():
    d = normalize.offer_detail(OFFER)
    assert d['main_image'] == 'https://img.example.test/main.jpg' and d['images'][0] == d['main_image']
    assert d['min_order_quantity'] == 2 and d['price_tiers'][1] == {'min_qty': 100, 'price': 12.5}
    assert d['skus'][0]['sku_id'] == '1' and d['supplier']['member_id'] == 'b2b-000000000test'
    assert d['shipping']['province'] == '广东' and d['mix_order_quantity'] is None and d['raw'] == OFFER


def test_offer_normalization_scrubs_buyer_address_unescapes_and_drops_zero_weight():
    raw = {**OFFER, 'freight': {**OFFER['freight'], 'receiveAddress': 'TEST_ONLY 买家收货地址', 'unitWeight': 0},
           'skus': [{'skuId': 6092334232768, 'specs': '橙色-1200毫安&gt;10米', 'price': 13.5}],
           'packageInfo': [{'skuId': '1', 'spec': 'x', 'length': 8.5, 'width': 0, 'height': None, 'weight': 1, 'volume': None}],
           '_cached': True}
    d = normalize.offer_detail(raw)
    assert 'receiveAddress' not in d['raw']['freight'] and '_cached' not in d['raw'] and 'TEST_ONLY 买家' not in str(d)
    assert raw['freight']['receiveAddress'] == 'TEST_ONLY 买家收货地址'  # 不修改调用方数据
    assert d['skus'][0]['specs'] == '橙色-1200毫安>10米' and d['skus'][0]['sku_id'] == '6092334232768'
    assert d['shipping']['unit_weight'] is None and d['package_info'][0]['width'] is None and d['package_info'][0]['weight'] == 1


def test_supplier_normalization_separates_platform_metrics_from_cli_score():
    item = normalize.supplier_search_result(SUPPLIERS, 'TEST_ONLY')['items'][0]
    assert item['platform_metrics']['response_rate'] == 0.9 and item['platform_metrics']['repeat_rate'] is None
    assert item['cli_score']['score'] == 71 and '不是 1688 平台指标' in item['cli_score']['note']


@pytest.mark.parametrize('fn,data', [(normalize.search_result, {'results': []}),
                                     (normalize.search_result, {'offers': [{'title': 'no id'}]}),
                                     (normalize.offer_detail, {'title': 'x'}),
                                     (lambda d: normalize.supplier_search_result(d, 'k'), {'items': [{}]})])
def test_contract_changes_are_reported(fn, data):
    with pytest.raises(Alibaba1688Error) as e:
        fn(data)
    assert e.value.state == 'contract_changed'


# ---- Provider：缓存、记录、图片 ----

def test_provider_caches_repeated_search_and_remembers_offers():
    t = FakeTransport({'search': SEARCH})
    p = provider(t)
    first = asyncio.run(p.search('TEST_ONLY'))
    second = asyncio.run(p.search('TEST_ONLY'))
    assert len(t.calls) == 1 and not first['cached'] and second['cached']
    # 缓存命中沿用 CLI 实际获取时间，而不是读取缓存的时间
    assert first['fetched_at'] == second['fetched_at'] == second['items'][0]['fetched_at']
    assert '_fetched_at' not in second['items'][0]['raw']
    assert p.seen_offers.get('700000000001')['title'] == 'TEST_ONLY 露营灯'
    assert p.last_query['state'] == 'ok'
    assert len(asyncio.run(p.search('TEST_ONLY', max_results=1))['items']) == 1


def test_provider_records_failures_and_never_retries():
    t = FakeTransport(error=Alibaba1688Error('timeout', retryable=True))
    p = provider(t)
    with pytest.raises(Alibaba1688Error):
        asyncio.run(p.search('TEST_ONLY'))
    assert len(t.calls) == 1 and p.last_query['state'] == 'timeout'


def test_provider_rejects_mismatched_offer_id():
    p = provider(FakeTransport({'offer': {**OFFER, 'offerId': '700000000009'}}))
    with pytest.raises(Alibaba1688Error) as e:
        asyncio.run(p.offer('700000000001'))
    assert e.value.state == 'contract_changed'


def test_image_validation_and_temp_file_cleanup():
    seen = {}

    class ImageTransport(FakeTransport):
        async def run(self, command, params, timeout, **extra):
            seen['path'] = Path(params['path'])
            seen['exists'] = seen['path'].exists()
            return CliResult(SEARCH, 1)

    p = provider(ImageTransport())
    assert sniff_image(b'\x89PNG\r\n\x1a\n' + b'0' * 10) == 'png'
    assert sniff_image(b'RIFF0000WEBPVP8 ') == 'webp'
    assert sniff_image(b'GIF89a') is None and sniff_image(b'<svg>') is None
    for bad in (b'', b'GIF89a....', b'\xff\xd8\xff' + b'0' * (5 * 1024 * 1024)):
        with pytest.raises(Alibaba1688Error):
            asyncio.run(p.image_search(bad))
    result = asyncio.run(p.image_search(b'\xff\xd8\xff' + b'0' * 100))
    assert seen['exists'] and seen['path'].suffix == '.jpg' and not seen['path'].exists()
    assert not seen['path'].parent.exists() and result['keyword'] is None and len(result['items']) == 2
    capped = asyncio.run(p.image_search(b'\xff\xd8\xff' + b'1' * 100, max_results=1))
    assert len(capped['items']) == 1 and capped['total'] == 1 and '相关性' in capped['notice']


def test_status_reports_cli_not_installed():
    class Missing(FakeTransport):
        def available(self):
            return False
    status = asyncio.run(provider(Missing()).status(refresh=True))
    assert status['state'] == 'cli_not_installed' and status['installed'] is False and 'npm install -g 1688-cli' in status['hint']


def test_status_does_not_expose_account_identity():
    t = FakeTransport({'version': {'version': '0.1.47'},
                       'doctor': {'ok': True, 'checks': [{'name': 'session', 'status': 'ok', 'message': 'C:\\Users\\x'}]},
                       'whoami': {'loggedIn': True, 'memberId': 'b2b-SECRETMEMBER', 'nick': 'SECRETNICK', 'lastVerifiedAt': '2026-10-13'},
                       'daemon_status': {'running': True, 'stats': {'browser': {'browserAlive': True, 'loggedIn': True}, 'health': {}}}})
    status = asyncio.run(provider(t).status(refresh=True))
    assert status['state'] == 'logged_in' and status['logged_in'] is True
    assert 'SECRET' not in str(status) and 'C:\\Users' not in str(status)


def test_status_detects_expired_session_from_daemon_health():
    t = FakeTransport({'version': {'version': '0.1.47'}, 'doctor': {'checks': []},
                       'whoami': {'loggedIn': True, 'lastVerifiedAt': 'x'},
                       'daemon_status': {'running': True, 'stats': {'browser': {'browserAlive': True, 'loggedIn': False},
                                                                     'health': {'lastFailureKind': 'not_logged_in'}}}})
    assert asyncio.run(provider(t).status(refresh=True))['state'] == 'login_expired'


# ---- 真实子进程（假 CLI）：stdout / stderr / 退出码 / 超时 / 并发 ----

pytestmark_node = pytest.mark.skipif(NODE is None, reason='需要 Node.js')


def local(monkeypatch, mode, **kw):
    monkeypatch.setenv('FAKE_1688_MODE', mode)
    return LocalCliTransport(Alibaba1688Settings(_env_file=None, cli_path=str(FAKE_CLI), min_interval=0, **kw))


@pytestmark_node
def test_subprocess_success_and_argument_safety(monkeypatch):
    t = local(monkeypatch, 'echo-args')
    result = asyncio.run(t.run('search', {'keyword': '露营灯 & echo hacked | calc', 'max': 5}, 20))
    argv = result.data['argv']
    assert argv[-2:] == ['--', '露营灯 & echo hacked | calc'] and '--profile' in argv


@pytestmark_node
@pytest.mark.parametrize('mode,state', [('not-logged-in', 'not_logged_in'), ('risk', 'risk_control'),
                                        ('paused', 'not_logged_in'), ('garbage', 'contract_changed')])
def test_subprocess_errors(monkeypatch, mode, state):
    with pytest.raises(Alibaba1688Error) as e:
        asyncio.run(local(monkeypatch, mode).run('search', {'keyword': 'TEST_ONLY'}, 20))
    assert e.value.state == state and 'SECRET_TEST_TOKEN' not in str(e.value.to_dict())


@pytestmark_node
def test_subprocess_timeout_is_killed_without_retry(monkeypatch):
    t = local(monkeypatch, 'hang')
    with pytest.raises(Alibaba1688Error) as e:
        asyncio.run(t.run('search', {'keyword': 'TEST_ONLY'}, 2))
    assert e.value.state == 'timeout' and e.value.retryable


@pytestmark_node
def test_concurrent_queries_are_serialized_and_bounded(monkeypatch):
    t = local(monkeypatch, 'hang', queue_wait=1)

    async def scenario():
        first = asyncio.create_task(t.run('search', {'keyword': 'a'}, 3))
        await asyncio.sleep(0.2)
        with pytest.raises(Alibaba1688Error) as busy:
            await t.run('search', {'keyword': 'b'}, 3)
        assert busy.value.state == 'busy'
        with pytest.raises(Alibaba1688Error):
            await first
    asyncio.run(scenario())


def test_missing_cli_is_reported(monkeypatch):
    t = LocalCliTransport(Alibaba1688Settings(_env_file=None, cli_path='Z:/definitely/missing/1688.cmd'))
    with pytest.raises(Alibaba1688Error) as e:
        asyncio.run(t.run('version', {}, 5))
    assert e.value.state == 'cli_not_installed'


# ---- 宿主机 CLI Adapter（remote 模式）----

TOKEN = 'TEST_ONLY_TOKEN_0123456789abcdef'


def adapter_client(transport):
    import httpx
    from app.services.alibaba1688.adapter_server import create_adapter_app
    from app.services.alibaba1688.runner import RemoteAdapterTransport
    settings = Alibaba1688Settings(_env_file=None, min_interval=0, transport='remote', adapter_url='http://adapter',
                                   adapter_token=TOKEN)
    app = create_adapter_app(settings, transport)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://adapter')
    return app, client, RemoteAdapterTransport(settings, client)


def test_adapter_refuses_to_start_without_strong_token():
    from app.services.alibaba1688.adapter_server import create_adapter_app
    with pytest.raises(RuntimeError):
        create_adapter_app(Alibaba1688Settings(_env_file=None, adapter_token='short'), FakeTransport())


def test_adapter_requires_token_and_whitelist():
    fake = FakeTransport({'search': SEARCH})
    _, client, _ = adapter_client(fake)

    async def scenario():
        r = await client.post('/run', json={'command': 'search', 'params': {'keyword': 'x'}})
        assert r.status_code == 401
        auth = {'Authorization': f'Bearer {TOKEN}'}
        r = await client.post('/run', headers=auth, json={'command': 'login', 'params': {}})
        assert r.status_code == 400
        r = await client.post('/run', headers=auth, json={'command': 'search', 'params': {'keyword': 'x', 'path': 'C:/secret'}})
        assert r.json()['ok'] is True and 'path' not in fake.calls[-1][1]
    asyncio.run(scenario())
    assert [c[0] for c in fake.calls] == ['search']


def test_remote_transport_roundtrip_and_error_propagation():
    _, client, remote = adapter_client(FakeTransport({'search': SEARCH}))
    p = provider(remote)
    result = asyncio.run(p.search('TEST_ONLY'))
    assert result['items'][0]['offer_id'] == '700000000001'
    _, client, remote = adapter_client(FakeTransport(error=Alibaba1688Error('risk_control')))
    with pytest.raises(Alibaba1688Error) as e:
        asyncio.run(provider(remote).search('TEST_ONLY'))
    assert e.value.state == 'risk_control'
