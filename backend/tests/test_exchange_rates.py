"""Manually maintained CNY rates and the recompute of finance records. Rates here are labelled fixtures, not market data."""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import select, update
from app.models.finance import ExchangeRate, FinanceRecord
from app.models.user import User
from app.services import order_sync_service
from tests.conftest import TestSessionLocal
from tests.test_order_sync import Upstream

URL = '/api/v1/finance/exchange-rates'


async def login(client, username, role=None):
    r = await client.post('/api/v1/auth/register', json={'username': username, 'password': 'securepass123', 'nickname': 'UNIT_ONLY'})
    assert r.status_code in (200, 201), r.text
    if role:
        async with TestSessionLocal() as db, db.begin():
            await db.execute(update(User).where(User.username == username).values(role=role))
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


@pytest.fixture
async def headers(client):
    return await login(client, 'rates-operator@example.com')


def record(kind, amount, currency, rate=None, cny=None, at=None):
    return FinanceRecord(type=kind, amount=Decimal(amount), currency=currency, site='MY',
                         exchange_rate=None if rate is None else Decimal(rate), cny_amount=None if cny is None else Decimal(cny),
                         created_at=at or datetime.now(timezone.utc), description='UNIT_ONLY')


async def test_list_shows_every_site_currency_without_prefilled_rates(client, headers):
    r = await client.get(URL, headers=headers)
    assert r.status_code == 200, r.text
    items = r.json()['items']
    assert [i['currency'] for i in items] == ['MYR', 'THB', 'VND', 'SGD', 'PHP', 'IDR']
    assert all(i['rate'] is None and i['updated_at'] is None and i['unconverted_records'] == 0 for i in items)


async def test_rates_require_admin_or_operator(client):
    assert (await client.get(URL)).status_code in (401, 403)
    agent = await login(client, 'rates-agent@example.com', role='cs_agent')
    assert (await client.get(URL, headers=agent)).status_code == 403
    assert (await client.put(URL + '/MYR', json={'rate': '0.65'}, headers=agent)).status_code == 403
    admin = await login(client, 'rates-admin@example.com', role='admin')
    assert (await client.put(URL + '/MYR', json={'rate': '0.65'}, headers=admin)).status_code == 200
    async with TestSessionLocal() as db:
        assert (await db.scalars(select(ExchangeRate))).all()[0].rate == Decimal('0.65')


@pytest.mark.parametrize('rate', [0, '0', -1, '-0.5', 'abc', None, '0.1234567', '12345.5'])
async def test_rate_must_be_positive_and_fit_the_finance_column(client, headers, rate):
    r = await client.put(URL + '/MYR', json={'rate': rate}, headers=headers)
    assert r.status_code == 422, r.text
    async with TestSessionLocal() as db:
        assert (await db.scalars(select(ExchangeRate))).all() == []


@pytest.mark.parametrize('currency', ['USD', 'CNY', 'XYZ'])
async def test_only_tiktok_site_currencies(client, headers, currency):
    assert (await client.put(URL + '/' + currency, json={'rate': '1.5'}, headers=headers)).status_code == 422


async def test_saving_a_rate_converts_records_and_totals(client, headers):
    async with TestSessionLocal() as db, db.begin():
        db.add_all([record('income', '20.00', 'MYR'), record('fee', '1.20', 'MYR'),
                    record('income', '13.00', 'MYR', rate='0.50', cny='26.00'),  # converted earlier at another rate
                    record('income', '100.00', 'THB')])
    summary = (await client.get('/api/v1/finance/summary', headers=headers)).json()
    assert summary['total_revenue'] == '26.00' and summary['unconverted'] == {'MYR': 2, 'THB': 1}
    assert (await client.get('/api/v1/dashboard/stats', headers=headers)).json()['unconverted_income_records'] == 2

    r = await client.put(URL + '/myr', json={'rate': '0.65'}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['currency'] == 'MYR' and body['rate'] == '0.650000' and body['source'] == 'manual'
    assert body['updated_by_name'] == 'UNIT_ONLY' and body['updated_by'] and body['updated_at']
    assert body['recomputed_records'] == 2 and body['unconverted_records'] == 0

    async with TestSessionLocal() as db:
        rows = {(r.type, r.amount): r for r in (await db.scalars(select(FinanceRecord).where(FinanceRecord.currency == 'MYR'))).all()}
        user = await db.scalar(select(User).where(User.username == 'rates-operator@example.com'))
        saved = await db.scalar(select(ExchangeRate).where(ExchangeRate.target_currency == 'MYR'))
    # 20 / 0.65 = 30.77, 1.20 / 0.65 = 1.85; the record already converted keeps its own rate.
    assert rows[('income', Decimal('20.00'))].cny_amount == Decimal('30.77')
    assert rows[('income', Decimal('20.00'))].exchange_rate == Decimal('0.65')
    assert rows[('fee', Decimal('1.20'))].cny_amount == Decimal('1.85')
    assert rows[('income', Decimal('13.00'))].cny_amount == Decimal('26.00')
    assert saved.updated_by == user.id and saved.source == 'manual'

    summary = (await client.get('/api/v1/finance/summary', headers=headers)).json()
    assert summary['total_revenue'] == '56.77' and summary['total_fee'] == '1.85' and summary['unconverted'] == {'THB': 1}
    stats = (await client.get('/api/v1/dashboard/stats', headers=headers)).json()
    assert stats['unconverted_income_records'] == 1 and Decimal(stats['today_sales']) == Decimal('56.77')
    items = {i['currency']: i for i in (await client.get(URL, headers=headers)).json()['items']}
    assert items['MYR']['rate'] == '0.650000' and items['THB']['rate'] is None and items['THB']['unconverted_records'] == 1


async def test_recompute_all_reprices_every_record_in_that_currency(client, headers):
    async with TestSessionLocal() as db, db.begin():
        db.add_all([record('income', '13.00', 'MYR', rate='0.50', cny='26.00'), record('income', '13.00', 'SGD', rate='0.50', cny='26.00')])
    r = await client.put(URL + '/MYR', json={'rate': 0.65, 'recompute_all': True}, headers=headers)
    assert r.status_code == 200 and r.json()['recomputed_records'] == 1
    async with TestSessionLocal() as db:
        rows = {r.currency: r for r in (await db.scalars(select(FinanceRecord))).all()}
    assert rows['MYR'].cny_amount == Decimal('20.00') and rows['MYR'].exchange_rate == Decimal('0.65')
    assert rows['SGD'].cny_amount == Decimal('26.00')


async def test_update_keeps_one_row_per_currency(client, headers):
    async with TestSessionLocal() as db, db.begin():
        db.add_all([ExchangeRate(base_currency='CNY', target_currency='THB', rate=Decimal('4.85')),
                    ExchangeRate(base_currency='CNY', target_currency='THB', rate=Decimal('4.90'))])
    r = await client.put(URL + '/THB', json={'rate': '4.700001'}, headers=headers)
    assert r.status_code == 200, r.text
    async with TestSessionLocal() as db:
        rows = (await db.scalars(select(ExchangeRate).where(ExchangeRate.target_currency == 'THB'))).all()
    assert [r.rate for r in rows] == [Decimal('4.700001')]
    assert (await client.put(URL + '/THB', json={'rate': '4.8'}, headers=headers)).json()['rate'] == '4.800000'


async def test_sync_fills_records_left_without_rate(client, headers, monkeypatch):
    """A rate saved while a sync was running must not leave that sync's records unconverted."""
    upstream = Upstream()
    monkeypatch.setattr('app.api.v1.orders.MiaoshouClient', lambda: upstream)
    monkeypatch.setattr('app.api.v1.orders.async_session_factory', TestSessionLocal)
    async with TestSessionLocal() as db, db.begin():
        db.add(record('income', '13.00', 'MYR'))
        db.add(ExchangeRate(base_currency='CNY', target_currency='MYR', rate=Decimal('0.65')))
    assert (await client.post('/api/v1/orders/sync', headers=headers)).status_code == 200
    summary = (await client.get('/api/v1/finance/summary', headers=headers)).json()
    # 13 / 0.65 = 20.00 (stale record) + 20 / 0.65 = 30.77 (synced package)
    assert summary['unconverted'] == {} and summary['total_revenue'] == '50.77'


async def test_fill_missing_cny_ignores_currencies_without_rate():
    async with TestSessionLocal() as db, db.begin():
        db.add_all([record('income', '10.00', 'MYR'), record('income', '10.00', 'PHP')])
    async with TestSessionLocal() as db, db.begin():
        assert await order_sync_service.fill_missing_cny(db, {'MYR': Decimal('0.5')}) == 1
    async with TestSessionLocal() as db:
        rows = {r.currency: r.cny_amount for r in (await db.scalars(select(FinanceRecord))).all()}
    assert rows == {'MYR': Decimal('20.00'), 'PHP': None}
