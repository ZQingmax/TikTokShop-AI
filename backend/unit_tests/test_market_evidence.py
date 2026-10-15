import base64
import io
import pytest
from fastapi import HTTPException
from openpyxl import Workbook

from app.services.market_evidence import ReportUpload, parse_report, report_fingerprint, EvidenceProvider
from app.services.sourcing_config import SourcingSettings
from app.services.sourcing_providers import AnalysisError

HEADER = 'name,source_platform,source_url,observed_on,target_market,rank,sales,period\n'
ROW = 'TEST 收纳盒,TEST榜单,https://example.com/item,2026-10-13,MY,2,,7天\n'


def test_missing_metrics_and_default_market():
    data = ReportUpload(name='TEST', format='csv', content=HEADER + ROW.replace(',MY,', ',,'))
    row = parse_report(data)[0]
    assert row['target_market'] == 'MY' and row['sales'] is None and row['rank'] == 2
    assert report_fingerprint(data, [row]) == report_fingerprint(data, [row])
    assert report_fingerprint(data.model_copy(update={'scope': 'shop'}), [row]) != report_fingerprint(data, [row])


@pytest.mark.parametrize('content', [HEADER + ROW.replace(',MY,', ',TH,'), HEADER + ROW.replace(',2,', ',-1,'),
    HEADER + ROW.replace('2026-10-13', 'yesterday'), HEADER + ROW.replace('https://example.com/item', 'javascript:bad'),
    HEADER + ROW.replace('TEST 收纳盒', '=SUM(A1)'), 'name\nx\n', HEADER + ROW * 501],
    ids=['wrong-market', 'negative-rank', 'invalid-date', 'unsafe-url', 'formula', 'missing-columns', 'too-many-rows'])
def test_invalid_import_is_rejected(content):
    with pytest.raises(HTTPException) as error:
        parse_report(ReportUpload(name='TEST', format='csv', content=content))
    assert error.value.status_code == 422


def test_xlsx_same_contract_as_csv():
    book = Workbook()
    book.active.append(HEADER.strip().split(','))
    book.active.append(ROW.strip().split(','))
    stream = io.BytesIO()
    book.save(stream)
    rows = parse_report(ReportUpload(name='TEST', format='xlsx', content=base64.b64encode(stream.getvalue()).decode()))
    assert rows == parse_report(ReportUpload(name='TEST', format='csv', content=HEADER + ROW))


async def test_ai_cannot_reference_nonexistent_evidence():
    class Fake:
        async def request(self, *args, **kwargs):
            return {'output': {'market_basis': [{'evidence_id': 'invented', 'reason': 'TEST'}],
                'matching_facts': [], 'differences': [], 'recommendation_reasons': [],
                'information_gaps': [], 'limitations': []}}
    provider = EvidenceProvider(SourcingSettings(_env_file=None))
    provider.provider = Fake()
    with pytest.raises(AnalysisError, match='不存在'):
        await provider.analyze({'market_evidence': []})
