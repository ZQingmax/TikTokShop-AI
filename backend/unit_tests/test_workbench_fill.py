import json
import httpx
import pytest
from app.services.workbench_config import WorkbenchSettings
from app.services.workbench_providers import WorkbenchProvider
from app.services.workbench_service import (source_hints, initial_content, category_candidates, clean_fill, description_images, description, normalize_notes, draft_dto, platform_value_ids, managed,
                                            validate_content, sku_labels)

IMG = 'https://cbu01.alicdn.com/img/ibank/UNIT_{}.jpg'


def cli_snapshot():
    names = ['UNIT 12件套', 'UNIT 15件套+1袋胶泥']
    return {'name': 'UNIT_ONLY 电脑机械键盘清洁神器拔键器', 'currency': 'CNY', 'images': [IMG.format(0)], 'main_image': IMG.format(0),
            'skus': [{'name': n, 'specs': {'规格': n}, 'sku_id': str(500 + i), 'purchase_price': str(8.49 + i)} for i, n in enumerate(names)],
            'raw_data': {'cli_offer': {
                'freight': {'unitWeight': 0.35},
                'attributes': [{'name': '包装尺寸', 'value': '15*20'}, {'name': '类型', 'value': '清洁套装'}],
                'options': [{'prop': '颜色', 'values': [{'name': n, 'imageUrl': IMG.format(i)} for i, n in enumerate(names)]}],
                'skus': [{'skuId': 500 + i, 'specs': n, 'stock': 2000 + i, 'price': 8.49 + i} for i, n in enumerate(names)]}}}


def miaoshou_snapshot():
    keys = [';小号（15*14.5）;;', ';大号（15*18）;;']
    return {'name': 'UNIT_ONLY 收纳筐', 'currency': 'CNY', 'source_weight': '0.2',
            'skus': [{'name': '', 'specs': {'原始规格键': k}, 'sku_id': k, 'purchase_price': None} for k in keys],
            'raw_data': {'detail_response': {'data': {'editCommonCollectBoxDetail': {
                'weight': 0.2, 'colorPropName': '颜色',
                'colorMap': {'大号（15*18）': {'name': '大号（15*18）', 'imgUrl': IMG.format(1)}, '小号（15*14.5）': {'name': '小号（15*14.5）', 'imgUrl': IMG.format(2)}},
                'skuMap': {keys[0]: {'price': 18, 'stock': 99, 'weight': 0.2}, keys[1]: {'price': 25, 'stock': 99, 'weight': 0.3}}}}}}}


def test_source_hints_from_1688_cli_and_miaoshou_records():
    hints = source_hints(cli_snapshot())
    assert hints['fields']['weight'] == {'value': 0.35, 'source': '1688 运费单位重量'}
    # Two numbers only, unit unstated: longest as length, height left empty, operator must confirm.
    assert hints['fields']['packageLength']['value'] == 20 and hints['fields']['packageWidth']['value'] == 15
    assert 'packageHeight' not in hints['fields'] and '核实' in hints['fields']['packageLength']['source']
    assert hints['skus'][1] == {'names': ['UNIT 15件套+1袋胶泥'], 'item_num': '501', 'stock': 2001, 'weight': None, 'purchase_price': 9.49}
    assert hints['specs'][0]['values'][0] == {'name': 'UNIT 12件套', 'image': IMG.format(0)}
    ms = source_hints(miaoshou_snapshot())
    assert ms['fields']['weight']['source'] == '妙手货源重量'
    assert ms['skus'][1] == {'names': ['大号（15*18）'], 'item_num': '', 'stock': 99, 'weight': 0.3, 'purchase_price': 25.0}


def test_new_1688_cli_draft_gets_specs_and_valid_sku_keys():
    content = initial_content(cli_snapshot())
    assert content['weight'] == 0.35 and content['packageLength'] is None
    assert [v['attrValueId'] for v in content['skuPropertyList'][0]['attrValueList']] == ['UNIT 12件套', 'UNIT 15件套+1袋胶泥']
    assert set(content['skuMap']) == {';UNIT 12件套;', ';UNIT 15件套+1袋胶泥;'}
    assert content['skuMap'][';UNIT 12件套;']['itemNum'] == '500'
    report = validate_content(content, 99, {'isLastLevel': '1'}, {}, {})
    assert not any('key 必须' in e['message'] or '与销售规格不一致' in e['message'] for e in report['errors'])
    assert [x['label'] for x in sku_labels(content)] == ['UNIT 12件套', 'UNIT 15件套+1袋胶泥']


def test_category_candidates_are_real_enabled_leaves_ranked_by_overlap():
    tree = {'1': {'cid': 1, 'nameChinese': '电脑办公', 'isLastLevel': '0', 'children': {
                '2': {'cid': 2, 'nameChinese': '键盘清洁套装', 'isLastLevel': '1'},
                '3': {'cid': 3, 'nameChinese': '机械键盘', 'isLastLevel': '1', 'disabled': True}}},
            '4': {'cid': 4, 'nameChinese': '家居收纳', 'isLastLevel': '1'}}
    found = category_candidates(tree, '电脑机械键盘清洁神器')
    assert [c['cid'] for c in found] == ['2'] and found[0]['path'] == '电脑办公 / 键盘清洁套装'


def test_clean_fill_keeps_only_real_ids_and_plausible_units():
    context = {'categories': [{'cid': '2', 'path': 'A / B'}], 'rules': {
        'product': [{'attr_id': '10', 'name': 'Material', 'multiple': False, 'customizable': False, 'values': [{'id': '11', 'name': 'PP'}]},
                    {'attr_id': '20', 'name': 'Type', 'multiple': True, 'customizable': True, 'values': []}],
        'sale': [{'attr_id': '30', 'name': 'Specification', 'multiple': True, 'customizable': True, 'values': [{'id': '31', 'name': 'Set'}]}]}}
    content = {'skuMap': {';a;': {}}}
    output = {'category': {'cid': '999', 'reason': 'x'}, 'weight': {'value': 500, 'reason': 'grams by mistake'},
              'package': {'length': 20, 'width': 15, 'height': 5, 'reason': '估算'},
              'sku_weights': [{'sku_key': ';a;', 'weight': .1, 'reason': ''}, {'sku_key': ';ghost;', 'weight': .1, 'reason': ''}],
              'attributes': [{'attr_id': '10', 'value_ids': ['11', '404'], 'custom_values': ['Metal'], 'reason': ''},
                             {'attr_id': '20', 'value_ids': [], 'custom_values': ['Cleaning kit', ' '], 'reason': ''},
                             {'attr_id': '99', 'value_ids': ['1'], 'custom_values': [], 'reason': ''}],
              'sale_specs': [{'source_property': '颜色', 'attr_id': '30', 'values': [
                  {'source_value': '12件套', 'value_id': '31', 'custom_value': ''},
                  {'source_value': '15件套', 'value_id': '', 'custom_value': '15-piece set'}]}]}
    result = clean_fill(output, context, content)
    assert result['category'] is None and result['weight'] is None and result['package']['height'] == 5
    assert [w['sku_key'] for w in result['sku_weights']] == [';a;']
    assert [(a['attr_id'], a['value_ids'], a['custom_values']) for a in result['attributes']] == [('10', ['11'], []), ('20', [], ['Cleaning kit'])]
    assert result['sale_specs'][0]['values'] == [{'source_value': '12件套', 'value_id': '31'}, {'source_value': '15件套', 'value_id': '15-piece set'}]
    output['category']['cid'] = '2'
    assert clean_fill(output, context, content)['category']['path'] == 'A / B'


@pytest.mark.asyncio
async def test_fill_request_sends_real_candidates_and_returns_cleaned_output():
    seen = {}
    async def handler(request):
        seen.update(json.loads(request.content))
        out = {'category': {'cid': '2', 'reason': 'UNIT'}, 'weight': {'value': .35, 'reason': '来源'}, 'attributes': [{'attr_id': 'x', 'value_ids': ['y']}]}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(out)}}], 'id': 'UNIT_FILL'})
    settings = WorkbenchSettings(_env_file=None, BAILIAN_API_KEY='UNIT_KEY')
    snapshot = {'config': {**settings.public_config(), 'base_url': settings.bailian_base_url}, 'language': 'en',
                'source': cli_snapshot(), 'content': initial_content(cli_snapshot())}
    context = {'facts': source_hints(snapshot['source']), 'skus': sku_labels(snapshot['content']),
               'categories': [{'cid': '2', 'path': '电脑办公 / 键盘清洁套装'}], 'rules': {}, 'category_path': ''}
    result = await WorkbenchProvider(settings, httpx.MockTransport(handler)).fill(snapshot, context)
    user = json.loads(seen['messages'][1]['content'])
    assert user['candidates'] == context['categories'] and user['product']['specs'][0]['name'] == '颜色'
    assert result['output']['category']['path'] == '电脑办公 / 键盘清洁套装' and result['output']['attributes'] == []
    assert result['request_id'] == 'UNIT_FILL'


def test_description_images_keep_only_public_urls_in_order():
    markup = ('<div><img src="//cbu01.alicdn.com/a.jpg" usemap="#m"/><img onerror="x" src=\'https://cbu01.alicdn.com/b.jpg?x=1&amp;y=2\'>'
              '<img src="javascript:alert(1)"><img src="data:image/png;base64,AA"><IMG SRC="https://cbu01.alicdn.com/a.jpg"></div>')
    assert description_images(markup) == ['https://cbu01.alicdn.com/a.jpg', 'https://cbu01.alicdn.com/b.jpg?x=1&y=2']


def test_synced_description_is_generated_escaped_html_only_with_detail_images():
    content = {'bullet_points': ['Strong <b>', ' '], 'notes': 'Line one\n\n<script>alert(1)</script>', 'descImgUrls': []}
    assert description(content) == '• Strong <b>\nLine one\n\n<script>alert(1)</script>'  # unchanged plain text
    content['descImgUrls'] = ['https://cbu01.alicdn.com/a.jpg', 'https://example.com/b.png?x="1"']
    assert description(content) == ('<ul><li>Strong &lt;b&gt;</li></ul><p>Line one</p><p>&lt;script&gt;alert(1)&lt;/script&gt;</p>'
                                     '<img src="https://cbu01.alicdn.com/a.jpg"/><img src="https://example.com/b.png?x=&quot;1&quot;"/>')
    assert normalize_notes('<p>a</p>\n <img src="x"/>') == normalize_notes('<p>a</p> <img src="x">')
    # Images alone are a valid description; the generated HTML is what is length-checked.
    images_only = {**payload_content(), 'notes': '', 'bullet_points': [], 'descImgUrls': ['https://cbu01.alicdn.com/a.jpg']}
    assert not any(e['field'] == 'notes' for e in validate_content(images_only, 99, {'isLastLevel': '1'}, {}, {})['errors'])


def payload_content():
    return initial_content(cli_snapshot())


def test_miaoshou_draft_seeds_detail_images_source_attributes_and_source_prices():
    snapshot = miaoshou_snapshot()
    detail = snapshot['raw_data']['detail_response']['data']['editCommonCollectBoxDetail']
    detail['notes'] = '<div><img src="https://cbu01.alicdn.com/d1.jpg"/><img src="https://cbu01.alicdn.com/d2.jpg"/></div>'
    detail['sourceAttrs'] = [{'name': '材质', 'value': 'PP'}, {'name': '', 'value': 'ignored'}]
    content = initial_content(snapshot)
    assert content['descImgUrls'] == ['https://cbu01.alicdn.com/d1.jpg', 'https://cbu01.alicdn.com/d2.jpg']
    assert content['sourceAttributes'] == [{'name': '材质', 'value': 'PP'}]
    assert {k: v['originPrice'] for k, v in content['skuMap'].items()} == {';小号（15*14.5）;;': 18.0, ';大号（15*18）;;': 25.0}
    assert {v['originPrice'] for v in initial_content(cli_snapshot())['skuMap'].values()} == {8.49, 9.49}


def test_older_drafts_get_new_content_fields_with_defaults():
    from types import SimpleNamespace
    old = SimpleNamespace(id='d', collect_item_id=None, shop_id=None, market='MY', currency='MYR', language='en', source_snapshot={},
                          content={'title': 'UNIT_ONLY kept'}, version=1, checked_version=None, validation=None, synced_version=None,
                          common_detail_id=None, platform_detail_id=None, created_at=None, updated_at=None)
    dto = draft_dto(old)
    assert dto['content']['title'] == 'UNIT_ONLY kept' and dto['content']['descImgUrls'] == [] and dto['content']['sourceAttributes'] == []


def test_unmapped_source_spec_error_names_it_and_mapped_custom_spec_passes():
    content = initial_content(miaoshou_snapshot())  # Miaoshou spec「颜色」with attrId '' and ';name;;' keys
    metadata = {'categorySaleAttrList': [{'attrId': '100', 'name': 'Specification', 'isCustomized': True, 'values': []}]}
    errors = [e['message'] for e in validate_content(content, 99, {'isLastLevel': '1'}, metadata, {})['errors'] if e['field'] == 'skuPropertyList']
    assert errors == ['销售规格「颜色」还没有对应到当前类目的销售属性：在「销售属性 / SKU」中为它选择对应属性']
    # What the editor's「对应到」does: link the attribute, keep values as custom ids, re-key SKUs sorted.
    content['skuPropertyList'][0]['attrId'] = '100'
    content['skuMap'] = {f";{k.strip(';')};": v for k, v in content['skuMap'].items()}
    report = validate_content(content, 99, {'isLastLevel': '1'}, metadata, {})
    assert not any(e['field'] == 'skuPropertyList' or 'key 必须' in e['message'] or '不一致' in e['message'] for e in report['errors'])


def test_sync_payload_uses_platform_value_ids_and_keeps_miaoshou_defaults():
    content = {'skuPropertyList': [{'attrId': '100000', 'attrName': 'Warna', 'attrValueList': [
                   {'attrValueId': 'Besar (15*18)', 'attrValue': 'Besar (15*18)'}, {'attrValueId': '1004502', 'attrValue': 'Merah'},
                   {'attrValueId': '1d31851e6f', 'attrValue': 'Kecil'}]}],
               'skuMap': {';Besar (15*18);': {'price': 37.5}, ';1004502;': {'price': 1}, ';1d31851e6f;': {'price': 2}},
               'brandId': '', 'sizeChart': '', 'sizeChartType': '', 'title': 'UNIT_ONLY'}
    converted = platform_value_ids(content)
    new_id = converted['skuPropertyList'][0]['attrValueList'][0]['attrValueId']
    assert len(new_id) == 10 and new_id == platform_value_ids(content)['skuPropertyList'][0]['attrValueList'][0]['attrValueId']
    assert set(converted['skuMap']) == {f';{new_id};', ';1004502;', ';1d31851e6f;'} and converted['skuMap'][f';{new_id};'] == {'price': 37.5}
    assert content['skuMap'].get(';Besar (15*18);')  # input untouched
    sent = managed(converted)
    assert 'brandId' not in sent and 'sizeChartType' not in sent and sent['sizeChart'] == ''
    assert managed({**converted, 'brandId': '12', 'sizeChart': 'https://example.com/s.png', 'sizeChartType': 'image'})['sizeChartType'] == 'image'
