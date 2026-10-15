"""Pure unit tests for discovery components (no DB, no network). Upstream data are labelled fixtures."""
import asyncio
import uuid

import pytest
from pydantic import ValidationError

from app.schemas.discovery import AssessmentOutput, ConfirmCollectInput, DiscoveryTaskInput, keyword_problem
from app.services.alibaba1688.config import Alibaba1688Settings
from app.services.alibaba1688.errors import Alibaba1688Error
from app.services.alibaba1688.provider import Alibaba1688Provider
from app.services.alibaba1688.runner import CliResult
from app.services.discovery.adapters import (Alibaba1688CliDiscoveryProvider, Alibaba1688CliSearchAdapter,
                                            Alibaba1688OfficialSearchAdapter)
from app.services.discovery.base import DiscoveryError, SearchHit
from app.services.discovery.normalizer import DiscoveryResultNormalizer, NormalizedResult, Rejected
from app.services.discovery.planner import SearchQueryPlanner
from app.services.discovery.scoring import NOT_CONNECTED, rank
from app.services.sourcing_providers import AnalysisError


class FakeTransport:
    """Stands in for the 1688 CLI; returns a labelled fixture or raises a classified error."""
    def __init__(self, data=None, error=None):
        self.data, self.error, self.calls = data, error, []

    def available(self):
        return True

    async def run(self, command, params, timeout, **extra):
        self.calls.append((command, params))
        if self.error:
            raise self.error
        return CliResult(self.data, 5)


def cli_provider(transport):
    return Alibaba1688CliDiscoveryProvider(Alibaba1688Provider(Alibaba1688Settings(_env_file=None, min_interval=0), transport))


def test_cli_adapter_query_is_plain_keyword():
    adapter = Alibaba1688CliSearchAdapter(cli_provider(FakeTransport({'offers': []})))
    assert adapter.build_query('  厨房   收纳 ', ['二手']) == '厨房 收纳'
    with pytest.raises(DiscoveryError):
        adapter.build_query('', [])
    assert adapter.status()['available'] is True and adapter.status()['provider'] == '1688_cli'


def test_cli_provider_returns_offer_hits_and_does_not_page():
    transport = FakeTransport({'keyword': '收纳', 'offers': [
        {'offerId': '635021027818', 'title': 'UNIT_ONLY 收纳盒', 'price': {'text': '¥1', 'min': 1, 'max': 1}}]})
    provider = cli_provider(transport)
    page = asyncio.run(provider.search('收纳', 0, 20))
    assert [h.url for h in page.hits] == ['https://detail.1688.com/offer/635021027818.html']
    assert page.hits[0].title == 'UNIT_ONLY 收纳盒' and page.hits[0].position == 1 and page.more_available is False
    assert transport.calls[0][0] == 'search' and transport.calls[0][1]['max'] == 20
    assert asyncio.run(provider.search('收纳', 1, 20)).hits == [] and len(transport.calls) == 1


@pytest.mark.parametrize('state,category,retryable', [('not_logged_in', 'auth', False), ('risk_control', 'permission', False),
                                                       ('cli_not_installed', 'configuration', False), ('busy', 'rate_limit', True),
                                                       ('timeout', 'timeout', True)])
def test_cli_errors_are_classified(state, category, retryable):
    error = Alibaba1688Error(state, retryable=retryable)
    with pytest.raises(DiscoveryError) as e:
        asyncio.run(cli_provider(FakeTransport(error=error)).search('收纳'))
    assert e.value.category == category and e.value.retryable == retryable and e.value.code == state


def test_cli_contract_change_is_reported_not_guessed():
    with pytest.raises(DiscoveryError) as e:
        asyncio.run(cli_provider(FakeTransport({'results': []})).search('收纳'))
    assert e.value.category == 'response'


def test_official_1688_adapter_is_reported_unavailable_not_guessed():
    adapter = Alibaba1688OfficialSearchAdapter()
    assert adapter.status()['available'] is False
    with pytest.raises(DiscoveryError):
        asyncio.run(adapter.search('x', 0))


def test_normalizer_accepts_only_real_offer_urls():
    n = DiscoveryResultNormalizer()
    ok = n.normalize(SearchHit('http://m.1688.com/offer/635021027818.html?spm=x', 'UNIT 收纳', '', 3), 'k', 'q', 'p', [])
    assert isinstance(ok, NormalizedResult) and ok.canonical_url == 'https://detail.1688.com/offer/635021027818.html'
    for url, reason in [('https://s.1688.com/selloffer/offer_search.htm?keywords=x', 'not_1688_offer_url'),
                        ('https://detail.1688.com.evil.com/offer/635021027818.html', 'not_1688_offer_url'),
                        ('https://detail.1688.com/offer/12.html', 'not_1688_offer_url'),
                        ('ftp://detail.1688.com/offer/635021027818.html', 'not_1688_offer_url')]:
        assert n.normalize(SearchHit(url, 't', '', 1), 'k', 'q', 'p', []).reason == reason
    assert n.normalize(SearchHit('https://detail.1688.com/offer/635021027818.html', ' ', '', 1), 'k', 'q', 'p', []).reason == 'missing_title'
    excluded = n.normalize(SearchHit('https://detail.1688.com/offer/635021027818.html', '二手收纳', '', 1), 'k', 'q', 'p', ['二手'])
    assert isinstance(excluded, Rejected) and excluded.reason == 'excluded_word:二手'


def test_keyword_guard_rejects_ids_links_prices_and_excluded_words():
    assert keyword_problem('厨房收纳') is None
    assert keyword_problem('detail.1688.com') and keyword_problem('635021027818') and keyword_problem('收纳盒 9.9元')
    assert keyword_problem('¥10 收纳') and keyword_problem('site:1688') and keyword_problem('https://x')
    accepted, rejected = SearchQueryPlanner.screen(
        [{'keyword': '厨房收纳'}, {'keyword': '厨房收纳'}, {'keyword': '二手置物架'}, {'keyword': '635021027818'},
         {'keyword': '桌面整理'}, {'keyword': '免打孔挂架'}], ['二手'], 2)
    assert [a['keyword'] for a in accepted] == ['厨房收纳', '桌面整理']
    assert [r['rejected_reason'] for r in rejected] == ['重复', '包含排除词', '包含疑似商品 ID 的长数字', '超出关键词数量上限']


class FakePlannerProvider:
    def __init__(self, output=None, error=None):
        self.output, self.error, self.calls = output, error, 0

    async def request(self, content, schema, system=None, max_tokens=3500):
        self.calls += 1
        assert '不得' in system or '严禁' in system
        if self.error:
            raise self.error
        schema.model_validate(self.output)
        return {'output': self.output, 'provider': 'TEST_FIXTURE', 'model': 'TEST_ONLY', 'request_id': 'unit', 'usage': None}


GOAL = {'target_market': 'TH', 'category': '家居用品', 'price_min': '5.00', 'price_max': '30.00', 'currency': 'CNY',
        'keywords': ['桌面整理'], 'exclude_words': ['二手'], 'preferences': '', 'max_candidates': 30}


def test_planner_puts_user_keywords_first_and_screens_model_output():
    fake = FakePlannerProvider({'keywords': [
        {'keyword': '厨房收纳', 'angle': '场景', 'rationale': 'UNIT'}, {'keyword': '桌面整理', 'angle': '重复', 'rationale': 'UNIT'},
        {'keyword': '二手收纳盒', 'angle': '排除', 'rationale': 'UNIT'}, {'keyword': '收纳 https://x.cn', 'angle': '链接', 'rationale': 'UNIT'}],
        'notes': []})
    plan = asyncio.run(SearchQueryPlanner(provider_factory=lambda: fake).plan(GOAL, 6))
    assert [k['keyword'] for k in plan['keywords']] == ['桌面整理', '厨房收纳']
    assert plan['keywords'][0]['origin'] == 'user' and plan['evidence']['model'] == 'TEST_ONLY'
    assert len(plan['rejected']) == 3 and plan['planner_error'] is None


def test_planner_failure_falls_back_to_user_keywords_or_fails():
    fake = FakePlannerProvider(error=AnalysisError('upstream_401', 'UNIT 鉴权失败'))
    plan = asyncio.run(SearchQueryPlanner(provider_factory=lambda: fake).plan(GOAL, 6))
    assert [k['keyword'] for k in plan['keywords']] == ['桌面整理'] and plan['planner_error']['code'] == 'upstream_401'
    with pytest.raises(AnalysisError):
        asyncio.run(SearchQueryPlanner(provider_factory=lambda: fake).plan({**GOAL, 'keywords': []}, 6))


def dim(score, level='medium'):
    return {'score': score, 'level': level, 'explanation': 'UNIT', 'evidence': ['UNIT']}


def test_rank_formula_is_explicit_and_compliance_blocks():
    output = {'short_video_potential': dim(80), 'market_fit': dim(60), 'homogeneity_risk': dim(40),
              'ip_compliance_risk': dim(10, 'low')}
    r = rank(70, 100, output)
    assert r['rank_score'] == round(0.30 * 70 + 0.25 * 80 + 0.15 * 60 + 0.15 * 60 + 0.15 * 100, 1)
    assert r['recommendation'] == 'recommended'
    blocked = rank(90, 100, {**output, 'ip_compliance_risk': dim(90, 'high')})
    assert blocked['recommendation'] == 'not_recommended_compliance'
    assert set(NOT_CONNECTED) == {'tiktok_sales', 'market_heat', 'profit_margin', 'supplier_certification', 'realtime_competition'}
    assert all(v['status'] == '未接入' and v['value'] is None for v in NOT_CONNECTED.values())


def test_assessment_schema_rejects_extra_fields_and_out_of_range():
    base = {'selling_points': ['UNIT'], 'short_video_potential': dim(50), 'market_fit': dim(50), 'homogeneity_risk': dim(50),
            'ip_compliance_risk': dim(50), 'compliance_flags': [], 'summary': 'UNIT', 'limitations': ['无销量数据']}
    AssessmentOutput.model_validate(base)
    with pytest.raises(ValidationError):
        AssessmentOutput.model_validate({**base, 'monthly_sales': 1000})
    with pytest.raises(ValidationError):
        AssessmentOutput.model_validate({**base, 'market_fit': dim(101)})


def test_task_input_validation():
    data = DiscoveryTaskInput(request_key=uuid.uuid4(), target_market='TH', category='家居用品', price_min='5', price_max='30',
                              keywords=['厨房收纳', '厨房收纳 '], exclude_words=['二手'])
    assert data.keywords == ['厨房收纳'] and data.max_candidates == 30
    with pytest.raises(ValidationError):
        DiscoveryTaskInput(request_key=uuid.uuid4(), target_market='TH', category='x', price_min='30', price_max='5')
    with pytest.raises(ValidationError):
        DiscoveryTaskInput(request_key=uuid.uuid4(), target_market='TH', category='x', max_candidates=31)
    with pytest.raises(ValidationError):
        ConfirmCollectInput(source_item_ids=['1', '2'])
    with pytest.raises(ValidationError):
        ConfirmCollectInput(source_item_ids=[str(635021027810 + i) for i in range(6)])
