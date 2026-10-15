import copy
import hashlib
import io
import json
import socket
from types import SimpleNamespace
import pytest
import httpx
from PIL import Image
from pydantic import ValidationError
from app.schemas.workbench import EditorialContent
from app.services.workbench_config import WorkbenchSettings
from app.services.workbench_providers import WorkbenchProvider, fetch_workbench_image, edit_size
from app.services.workbench_worker import read_cached
from app.services import sourcing_providers
from app.services.sourcing_providers import AnalysisError, image_result, fetch_image
from app.services.workbench_service import validate_content, matches_expected
from app.clients.miaoshou_client import (MiaoshouClient, RequestLimiter, CATEGORY, METADATA, WAREHOUSES,
                                        CLAIM_SHOP, SHOP_DETAIL, SAVE_SHOP, PICTURE_UPLOAD)


def payload():
    return EditorialContent(title='UNIT_ONLY Useful household storage rack', notes='UNIT_ONLY facts', imgUrls=['https://example.com/a.png'],
        weight=.2, packageLength=10, packageWidth=10, packageHeight=10, cid='7',
        skuMap={';': {'price': 5, 'stock': 1, 'shopIdToWarehouseIdAndStockMap': {'99': {'8': 1}}}}).model_dump(mode='json')


def rules_check(content, metadata=None):
    return validate_content(content, 99, {'isLastLevel': '1', 'disabled': False}, metadata or {},
        {'shopWarehouseList': [{'shopId': 99, 'warehouseList': [{'warehouseId': '8', 'warehouseEffectStatus': '1'}]}]})


def test_required_and_conditional_rules_and_units():
    c = payload()
    assert rules_check(c)['valid']
    c['packageLength'] = .5
    c['skuMap'][';']['shopIdToWarehouseIdAndStockMap']['99']['8'] = 2
    report = rules_check(c, {'categoryConfig': {'manufacturerIsRequired': '1', 'sizeChartIsRequired': '1'}})
    assert {e['field'] for e in report['errors']} >= {'packageLength', 'skuMap', 'manufacturerIds', 'sizeChart'}
    c = payload()
    metadata = {'categoryProductAttrList': [{'attrId': '12', 'name': 'Material', 'isMandatory': True, 'values': [{'id': '13', 'name': 'Metal'}], 'valueIdAndRequiredCertificationIdsMap': {'13': ['15']}}],
                'categoryConfig': {'productCertifications': [{'id': '15', 'requirementConditions': [{'attributeValueId': '13'}]}]}}
    assert not rules_check(c, metadata)['valid']
    c['productAttributes'] = [{'attributeId': '12', 'attributeValues': [{'valueId': '13', 'valueName': 'Metal'}]}]
    assert any(x['field'] == 'productCertifications' for x in rules_check(c, metadata)['errors'])
    c['productCertifications'] = [{'id': '15', 'files': [{'fileUrl': 'https://example.com/cert.pdf'}]}]
    assert rules_check(c, metadata)['valid']


def test_numeric_sku_order_and_invalid_saved_structures():
    c = payload()
    c['skuPropertyList'] = [{'attrId': 'a', 'attrValueList': [{'attrValueId': '2'}]}, {'attrId': 'b', 'attrValueList': [{'attrValueId': '10'}]}]
    c['skuMap'] = {';2;10;': c['skuMap'][';']}
    metadata = {'categorySaleAttrList': [{'attrId': 'a', 'values': [{'id': '2'}]}, {'attrId': 'b', 'values': [{'id': '10'}]}]}
    report = rules_check(c, metadata)
    assert not any('key 必须' in e['message'] for e in report['errors'])
    for invalid in [{'skuMap': {';': {'stock': True}}}, {'skuPropertyList': [{'attrValueList': 'bad'}]}, {'weight': float('nan')}]:
        with pytest.raises(ValidationError):
            EditorialContent.model_validate(invalid)


def test_readback_checks_all_submitted_fields_and_tolerates_platform_extras():
    expected = {'title': 'UNIT_ONLY', 'skuMap': {';': {'price': 5, 'stock': 1}}, 'imgUrls': ['a', 'b']}
    remote = {**copy.deepcopy(expected), 'detailId': 99}
    remote['skuMap'][';']['price'] = '5.00'
    assert matches_expected(remote, expected)
    remote['imgUrls'].reverse()
    assert not matches_expected(remote, expected)


class NoWait(RequestLimiter):
    async def wait(self, interval): pass


@pytest.mark.asyncio
async def test_miaoshou_editor_wire_contracts_and_acks():
    seen = []
    async def handler(request):
        path, data = request.url.path, json.loads(request.content)
        seen.append(path)
        if path == CATEGORY: out = {'cateTree': {}}
        elif path == METADATA:
            assert data == {'site': 'MY', 'cid': 7, 'shopIds': [99]}
            out = {'categoryMetadata': {}}
        elif path == WAREHOUSES: out = {'shopWarehouseList': []}
        elif path == CLAIM_SHOP:
            assert data == {'detailIds': [77], 'shopIds': [99]}
            return httpx.Response(200, json={'result': 'success', 'code': 'success'})
        elif path == SHOP_DETAIL: out = {'ossMd5': 'UNIT_MD5', 'shopCollectItemInfo': {}}
        elif path == SAVE_SHOP:
            assert data == {'detailId': 77, 'shopId': 99, 'ossMd5': 'UNIT_MD5', 'shopCollectItemInfo': {'title': 'UNIT_ONLY'}}
            out = {'ossMd5': 'UNIT_NEW_MD5'}
        else:
            assert path == PICTURE_UPLOAD and data['scene'] == 'product'
            out = {'picturePath': 'https://example.com/stored.png', 'width': 32, 'height': 32}
        return httpx.Response(200, json={'result': 'success', 'code': 'success', 'data': out})
    client = MiaoshouClient(WorkbenchSettings(_env_file=None, miaoshou_app_key='UNIT_KEY', miaoshou_app_secret='UNIT_SECRET'), httpx.MockTransport(handler), NoWait())
    await client.get_categories('MY'); await client.get_category_metadata('MY', '7', 99)
    await client.get_warehouses(99); await client.claim_to_shop(77, 99)
    await client.get_shop_detail(77, 99); await client.save_shop_detail(77, 99, 'UNIT_MD5', {'title': 'UNIT_ONLY'})
    await client.upload_picture('https://example.com/a.png')
    assert set(seen) == {CATEGORY, METADATA, WAREHOUSES, CLAIM_SHOP, SHOP_DETAIL, SAVE_SHOP, PICTURE_UPLOAD}


@pytest.mark.asyncio
async def test_bailian_text_image_and_translation_protocols(monkeypatch):
    buffer = io.BytesIO(); Image.new('RGB', (32, 32)).save(buffer, 'PNG')
    monkeypatch.setattr('app.services.workbench_providers.fetch_image', lambda url, **_: image_result(url, 'image/png', buffer.getvalue()))
    seen = []
    async def handler(request):
        data = json.loads(request.content) if request.content else {}
        seen.append(request.url.path)
        if request.url.path.endswith('/chat/completions'):
            assert data['model'] == 'qwen3.5-plus' and data['enable_thinking'] is False
            out = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'blocks': [{'image_index': 0, 'text': 'UNIT_ONLY'}]})}}], 'id': 'UNIT_REQUEST'}
        elif request.url.path.endswith('/images/generations'):
            # Edit keeps the 32x32 fixture's square ratio, raised to the model's 512x512 minimum.
            assert data['model'] == 'qwen-image-3.0' and data['size'] == '512x512'
            assert data['image'][0].startswith('data:image/png;base64,')
            out = {'data': [{'url': 'https://example.com/result.png'}]}
        elif request.method == 'POST':
            assert data['model'] == 'qwen-mt-image-2.0' and data['input']['target_lang'] == 'en'
            assert request.headers['X-DashScope-Async'] == 'enable'
            out = {'output': {'task_id': 'UNIT_TASK'}}
        else: out = {'output': {'task_status': 'SUCCEEDED', 'image_url': 'https://example.com/translated.png'}}
        return httpx.Response(200, json=out)
    settings = WorkbenchSettings(_env_file=None, BAILIAN_API_KEY='UNIT_KEY')
    p = WorkbenchProvider(settings, httpx.MockTransport(handler))
    snapshot = {'config': {**settings.public_config(), 'base_url': settings.bailian_base_url, 'dashscope_base_url': settings.workbench_dashscope_base_url},
                'content': {}, 'source': {}, 'language': 'en', 'operation': {'kind': 'edit', 'image_urls': ['https://example.com/a.png'], 'prompt': 'UNIT_ONLY', 'source_lang': 'auto'}}
    assert (await p.text('ocr', snapshot))['output']['blocks'][0]['image_url'] == 'https://example.com/a.png'
    assert (await p.image(snapshot))['image_url']
    submitted = await p.translate_submit(snapshot)
    assert (await p.translate_poll(snapshot, submitted))['image_url']
    assert len(seen) == 4


@pytest.mark.asyncio
async def test_bad_model_output_does_not_create_copy():
    async def handler(request):
        return httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]})
    settings = WorkbenchSettings(_env_file=None, BAILIAN_API_KEY='UNIT_KEY')
    snapshot = {'config': {**settings.public_config(), 'base_url': settings.bailian_base_url}, 'content': {}, 'source': {}, 'language': 'en', 'operation': {}}
    with pytest.raises(AnalysisError, match='结构化'):
        await WorkbenchProvider(settings, httpx.MockTransport(handler)).text('copy', snapshot)


@pytest.mark.asyncio
async def test_english_copy_rejects_mixed_language():
    async def handler(request):
        content = {'title': 'UNIT_ONLY woven household storage basket', 'bullet_points': ['Organize small 杂物'], 'notes': 'UNIT_ONLY facts'}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(content)}}]})
    settings = WorkbenchSettings(_env_file=None, BAILIAN_API_KEY='UNIT_KEY')
    snapshot = {'config': {**settings.public_config(), 'base_url': settings.bailian_base_url}, 'content': {}, 'source': {}, 'language': 'en', 'operation': {}}
    with pytest.raises(AnalysisError, match='英文文案'):
        await WorkbenchProvider(settings, httpx.MockTransport(handler)).text('copy', snapshot)


def test_fake_ip_dns_errors_and_exact_trusted_hosts(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('198.18.1.7', 443))])
    monkeypatch.delenv('HTTPS_PROXY', raising=False)
    monkeypatch.delenv('https_proxy', raising=False)
    with pytest.raises(AnalysisError) as error:
        fetch_image('https://unit-only.example.com/a.png')
    assert error.value.code == 'image_untrusted_host' and 'unit-only.example.com' in error.value.message
    with pytest.raises(AnalysisError) as error:
        fetch_workbench_image('https://earth-rt.chengji-inc.com/a.png')
    assert error.value.code == 'image_proxy_required'
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:1')
    proxied = []
    monkeypatch.setattr(sourcing_providers, 'fetch_trusted_cdn_via_proxy', lambda url, proxy, hosts: proxied.append(url) or 'UNIT_FIXTURE')
    settings = WorkbenchSettings(_env_file=None, workbench_trusted_image_hosts=' IMG.alicdn.com ,img.alicdn.com')
    assert settings.trusted_image_hosts == {'img.alicdn.com'}
    assert fetch_workbench_image('https://img.alicdn.com/a.png', settings.trusted_image_hosts) == 'UNIT_FIXTURE'
    assert fetch_workbench_image('https://earth-rt.chengji-inc.com/a.png') == 'UNIT_FIXTURE'
    with pytest.raises(AnalysisError, match='Fake-IP'):
        fetch_workbench_image('https://img.alicdn.com/a.png')
    # Rotating DashScope result buckets are accepted by exact vendor naming only.
    assert fetch_workbench_image('https://dashscope-66f3.oss-accelerate.aliyuncs.com/r.png') == 'UNIT_FIXTURE'
    for host in ['dashscope-66f3.oss-accelerate.aliyuncs.com.evil.example', 'evil-dashscope-1.oss-cn-beijing.aliyuncs.com',
                 'dashscope-1.evil.aliyuncs.com']:
        with pytest.raises(AnalysisError):
            fetch_workbench_image(f'https://{host}/r.png')
    with pytest.raises(AnalysisError):
        fetch_image('https://dashscope-66f3.oss-accelerate.aliyuncs.com/r.png')
    assert len(proxied) == 3
    for bad in ['*.alicdn.com', '127.0.0.1', 'https://img.alicdn.com', 'img.alicdn.com/a']:
        with pytest.raises(ValidationError):
            WorkbenchSettings(_env_file=None, workbench_trusted_image_hosts=bad)


def test_cached_asset_requires_matching_digest_inside_root(tmp_path):
    buffer = io.BytesIO(); Image.new('RGB', (8, 8)).save(buffer, 'PNG')
    data = buffer.getvalue()
    (tmp_path / 'a.png').write_bytes(data)
    settings = WorkbenchSettings(_env_file=None, workbench_asset_directory=str(tmp_path))
    asset = SimpleNamespace(local_name='a.png', mime='image/png', sha256=hashlib.sha256(data).hexdigest())
    assert read_cached(settings, asset, 'https://example.com/a.png')['data_url'].startswith('data:image/png;base64,')
    for changed in [{'sha256': '0' * 64}, {'local_name': '../a.png'}, {'local_name': 'missing.png'}]:
        assert read_cached(settings, SimpleNamespace(**{**vars(asset), **changed}), 'https://example.com/a.png') is None


def test_edit_size_keeps_aspect_ratio_within_configured_area():
    def image(width, height):
        buffer = io.BytesIO(); Image.new('RGB', (width, height)).save(buffer, 'PNG')
        return image_result('https://example.com/a.png', 'image/png', buffer.getvalue())
    assert edit_size(image(800, 800), '1024x1024') == '800x800'
    assert edit_size(image(750, 1000), '1024x1024') == '752x992'
    width, height = map(int, edit_size(image(1600, 2400), '1024x1024').split('x'))
    assert width % 16 == 0 and height % 16 == 0 and width * height <= 1024 * 1024 and abs(width / height - 2 / 3) < .02
    width, height = map(int, edit_size(image(100, 150), '1024x1024').split('x'))
    assert width * height >= 512 * 512 and abs(width / height - 2 / 3) < .02
    assert edit_size(image(900, 100), '1024x1024') == '1024x1024'
    assert edit_size({'data_url': 'data:image/png;base64,bad'}, '1024x1024') == '1024x1024'
