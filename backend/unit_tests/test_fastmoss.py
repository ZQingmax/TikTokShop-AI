import pytest
from fastapi import HTTPException
from app.services.fastmoss.normalize import number, currency, normalize_rows, merge_rows, encode_csv
from app.services.fastmoss.browser import categories_from_page, english_names, Browser, BrowserError
from app.services.market_evidence import ReportUpload, parse_report

URL = 'https://www.fastmoss.com/zh/e-commerce/sales'
CAT = {'id': '1', 'name': '收纳', 'path': ['家居用品', '收纳'], 'parent_id': '0', 'household': True}
RAW = dict(product_name='TEST 收纳盒', country='马来西亚', price='RM 12.50', rank='1',
           sales_period='1.2万', gmv_period='MYR 2.5K', total_sales='25,000', total_gmv='', shop='TEST', source_url=URL)


@pytest.mark.parametrize('value,expected', [('1.2万', '12000.0'), ('RM 12.50', '12.50'), ('2.5K', '2500.0'),
    ('12-20', None), ('≥100', None), ('', None), ('--', None), ('NaN', None), ('-1', None)])
def test_numeric_units_and_unknowns(value, expected):
    assert number(value) == expected


def test_dates_currency_and_raw_retained():
    row = normalize_rows([RAW], 'MY', fetched_at='2026-10-14T00:00:00Z', category=CAT)[0]
    assert row['observed_on'] is None and row['period'] is None
    assert row['sales'] == 12000 and row['total_revenue'] is None
    assert row['currency'] == 'MYR' and row['raw'] == RAW
    assert currency('$12') is None and number('1.2', integer=True) is None


def test_multiple_rankings_merge_without_global_rank():
    a = normalize_rows([{**RAW, 'product_url': 'https://www.fastmoss.com/zh/e-commerce/detail/123'}], 'MY', category=CAT)
    b = normalize_rows([{**RAW, 'product_url': 'https://www.fastmoss.com/zh/e-commerce/detail/123', 'rank': '3'}], 'MY', category={**CAT, 'id': '2', 'path': ['厨房', '收纳']})
    rows = merge_rows([*a, *a, *b])
    assert len(rows) == 1 and len(rows[0]['rankings']) == 2 and rows[0]['rank'] is None
    assert len(rows[0]['category_paths']) == 2


def test_repeated_page_does_not_create_another_ranking():
    rows = []
    for page in ('1', '2'):
        rows += normalize_rows([{**RAW, 'page': page, 'product_url': 'https://www.fastmoss.com/zh/e-commerce/detail/123'}], 'MY', category=CAT)
    merged = merge_rows(rows)
    assert len(merged) == 1 and merged[0]['rank'] == 1 and len(merged[0]['rankings']) == 1


def test_browser_status_uses_real_json_contract(monkeypatch):
    monkeypatch.setattr('app.services.fastmoss.browser.upstream', lambda s: None)
    browser = Browser()
    monkeypatch.setattr(browser, 'run', lambda *a, **k: '{"browsers":[{"id":"test"}]}')
    assert browser.status()['ready']
    monkeypatch.setattr(browser, 'run', lambda *a, **k: '{"browsers":[]}')
    assert not browser.status()['ready']


def test_native_csv_bom_and_missing_category():
    csv = encode_csv([RAW])
    rows = parse_report(ReportUpload(name='TEST', format='csv', content=csv))
    assert rows[0]['category'] == '未分类' and rows[0]['observed_on'] is None
    assert rows[0]['source_kind'] == 'ranking'


@pytest.mark.parametrize('changes', [{'country': '泰国'}, {'source_url': 'javascript:alert(1)'},
                                   {'source_url': ''}, {'product_name': '=1+1'}])
def test_reject_untrusted_csv(changes):
    with pytest.raises(HTTPException):
        parse_report(ReportUpload(name='TEST', format='csv', content=encode_csv([{**RAW, **changes}])))


# 2026-10-14 在真实新品榜页面观察到的品类单选项（value = c_code，文本 = 中文名）与分类接口英文名
PAGE_OPTIONS = [{'value': '14', 'label': '美妆个护'}, {'value': '10', 'label': '居家日用'}, {'value': '11', 'label': '厨房用品'},
                {'value': '12', 'label': '家纺布艺'}, {'value': '13', 'label': '家电'}, {'value': '20', 'label': '家具'},
                {'value': '22', 'label': '家装建材'}]
API_PAYLOAD = {'category': [{'c_code': 10, 'c_name': 'Home Supplies', 'rank': 7}, {'c_code': 13, 'c_name': 'Household Appliances'},
                            {'c_code': 20, 'c_name': 'Furniture'}]}


def test_page_catalog_uses_real_ids_chinese_names_and_household_scope():
    rows = categories_from_page(PAGE_OPTIONS, english_names(API_PAYLOAD))
    by = {r['id']: r for r in rows}
    assert by['10']['name'] == '居家日用' and by['10']['name_en'] == 'Home Supplies' and by['10']['path'] == ['居家日用']
    assert by['10']['level'] == 1 and by['10']['parent_id'] is None and by['10']['source']
    # 快捷范围：居家日用、厨房、家纺；家具、家电、家装建材不默认纳入；英文 Household 不误判
    assert {r['id'] for r in rows if r['household']} == {'10', '11', '12'}
    for bad in ([{'value': 'x', 'label': '居家日用'}], [{'value': '10', 'label': ''}], [{'value': '10', 'label': 'A'}, {'value': '10', 'label': 'B'}], []):
        with pytest.raises(BrowserError):
            categories_from_page(bad)


class FakeSections:
    SECTIONS = {'products': {'url': URL}}

    @staticmethod
    def products_parse_row(cells):
        return {'rank': cells[0], 'product_name': cells[1].split('\n')[0], 'price': 'RM12.50', 'country': cells[2],
                'shop': 'TEST', 'category': cells[4], 'sales_period': cells[6], 'gmv_period': cells[7],
                'total_sales': cells[8], 'total_gmv': cells[9]}


def fake_page(state):
    """模拟真实页面：verify 依据单选状态与 newProduct 请求参数；extract 返回前三名为奖牌图标的行。"""
    def page(operation, **args):
        state.setdefault('calls', []).append(operation)
        if operation == 'select':
            state['selected'].add(args['value'])
            return {'clicked': True}
        if operation == 'verify':
            return {'country': args['country'] in state['selected'] and state['region_applied'],
                    'category': args['category_id'] in state['selected'] and state['category_applied'],
                    'page': True, 'request': {'region': 'MY', 'l1_cid': args['category_id'], 'page': str(args['page'])}}
        if operation == 'extract':
            rows = [{'cells': ['', f'TEST 商品 {i}', '马来西亚', 'TEST', '居家日用', '-', '10', 'RM1', '20', 'RM2', ''],
                     'position': i, 'rank_icon': i <= 3, 'product_url': f'https://www.fastmoss.com/zh/e-commerce/detail/{i}',
                     'image_url': '', 'shop_url': ''} for i in range(1, 5)]
            rows[3]['cells'][0] = '4'
            rows[3]['rank_icon'] = False
            return {'rows': rows, 'source_url': URL, 'period': '三日', 'stat_start': '2026-10-11', 'stat_end': '2026-10-11', 'page_size': 10}
        if operation == 'next':
            return {'clicked': False}
        return {}
    return page


def browser_with(monkeypatch, state):
    monkeypatch.setattr('app.services.fastmoss.browser.upstream', lambda s: FakeSections())
    monkeypatch.setattr('app.services.fastmoss.browser.time.sleep', lambda s: None)
    browser = Browser()
    monkeypatch.setattr(browser, 'navigate', lambda u: None)
    monkeypatch.setattr(browser, 'page', fake_page(state))
    return browser


HOME = {'id': '10', 'name': '居家日用', 'path': ['居家日用'], 'parent_id': None, 'household': True}


def test_country_category_must_both_be_applied_to_page_request(monkeypatch):
    state = {'selected': set(), 'region_applied': True, 'category_applied': False}
    with pytest.raises(BrowserError, match='同时生效'):
        browser_with(monkeypatch, state).scrape('MY', HOME, 3)
    assert 'extract' not in state['calls']  # 未生效时不读取任何商品（不会导入综合榜）


def test_scrape_derives_icon_ranks_and_keeps_statistics_window(monkeypatch):
    state = {'selected': set(), 'region_applied': True, 'category_applied': True}
    rows = browser_with(monkeypatch, state).scrape('MY', HOME, 3)
    assert state['selected'] == {'MY', '10'}
    assert [r['rank'] for r in rows] == ['1', '2', '3', '4']
    assert rows[0]['rank_source'] == 'icon_position' and 'rank_source' not in rows[3]
    assert rows[0]['period'] == '三日' and rows[0]['observed_on'] == '2026-10-11'
    assert rows[0]['filter_region'] == 'MY' and rows[0]['filter_l1_cid'] == '10'
    converted = normalize_rows(rows, 'MY', category=HOME)
    assert converted[0]['rank'] == 1 and converted[0]['period'] == '三日' and converted[0]['observed_on'] == '2026-10-11'


@pytest.mark.parametrize('value,expected,code', [('1,711,755 ₫', '1711755', 'VND'), ('RM5396.52', '5396.52', 'MYR'),
    ('RM7.51 - 13.17', None, 'MYR'), ('Rp 12.000', None, 'IDR'), ('S$3.20', '3.20', 'SGD'), ('$12', '12', None)])
def test_real_price_formats(value, expected, code):
    assert number(value) == expected and currency(value) == code


def test_price_range_empty_values_and_unknown_period_stay_unknown():
    raw = {**RAW, 'price': 'RM10.00 - RM20.00', 'sales_period': '--', 'gmv_period': '', 'total_sales': '1.5万+',
           'total_gmv': 'MYR 3.2M', 'rank': ''}
    row = normalize_rows([raw], 'MY', category=CAT)[0]
    # 区间价格不猜成单一价格，原文保留；能确定的币种仍记录
    assert row['price'] is None and row['raw']['price'] == 'RM10.00 - RM20.00' and row['currency'] == 'MYR'
    assert row['sales'] is None and row['revenue'] is None and row['rank'] is None
    assert row['total_sales'] is None and row['raw']['total_sales'] == '1.5万+'
    assert row['total_revenue'] == '3200000.0' and row['period'] is None and row['observed_on'] is None


@pytest.mark.parametrize('header', ['name,country,price\nX,MY,1', 'product_name,price\nX,1', 'product_name,product_name,country\nX,Y,MY'])
def test_incompatible_headers_are_rejected(header):
    with pytest.raises(HTTPException):
        parse_report(ReportUpload(name='TEST', format='csv', content=header, source_url=URL))


def test_decoded_gbk_csv_is_parsed():
    # 前端按 GB18030 解码后以 UTF-8 字符串提交；后端按内容解析
    text = encode_csv([RAW]).encode('gb18030').decode('gb18030')
    assert parse_report(ReportUpload(name='TEST', format='csv', content=text))[0]['name'] == 'TEST 收纳盒'


@pytest.mark.parametrize('stdout,expected', [
    ('{"code":null,"message":"ensure daemon is running: automatic daemon startup is disabled","exit_code":2}', '守护进程未运行'),
    ('{"message":"no connected browser"}', '扩展未连接'),
    ('{"message":"session abc not found"}', '会话已失效'),
    ('{"message":"navigation failed: net::ERR_NAME_NOT_RESOLVED https://www.fastmoss.com/x?token=SECRET"}', '无法打开'),
    ('{"message":"weird https://example.com/?token=SECRET"}', '[链接]'),
    ('', '请检查扩展连接')])
def test_browserskill_failures_are_specific_and_hide_urls(stdout, expected):
    from app.services.fastmoss.browser import failure_reason
    reason = failure_reason(stdout, '')
    assert expected in reason and 'SECRET' not in reason


def test_empty_source_ranking_reports_specific_reason(monkeypatch):
    state = {'selected': set(), 'region_applied': True, 'category_applied': True}
    browser = browser_with(monkeypatch, state)
    base = browser.page

    def page(operation, **args):
        if operation == 'extract':
            return {'rows': [], 'empty': True, 'source_url': URL}
        return base(operation, **args)
    monkeypatch.setattr(browser, 'page', page)
    with pytest.raises(BrowserError, match='暂无商品'):
        browser.scrape('MY', {**HOME, 'id': '27', 'name': '虚拟商品', 'path': ['虚拟商品']}, 3)
