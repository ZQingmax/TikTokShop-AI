"""CNY exchange rates for the TikTok site currencies, entered manually by operators.

A rate means 1 CNY = rate × target currency (the convention of to_cny). Nothing is prefilled: a currency
without a row stays unconverted. Saving a rate fills cny_amount for that currency's finance records that
have none yet, or re-derives all of them when asked.
"""
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.finance import ExchangeRate, FinanceRecord
from app.models.user import User
from app.services.order_sync_service import recompute_cny

router = APIRouter(prefix='/v1/finance/exchange-rates', tags=['Finance'])
DB = Depends(get_db)
AUTH = Depends(get_current_user)
# TikTok Shop sites: MY, TH, VN, SG, PH, ID.
SITE_CURRENCIES = ('MYR', 'THB', 'VND', 'SGD', 'PHP', 'IDR')


class RateIn(BaseModel):
    # finance_records.exchange_rate is NUMERIC(10, 6), so a rate must fit there too.
    rate: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=6)]
    recompute_all: bool = False


def operator(user):
    if user.role not in ('admin', 'operator'):
        raise HTTPException(403, '只有管理员或运营人员可以维护汇率')


def currency_code(currency):
    code = currency.upper()
    if code not in SITE_CURRENCIES:
        raise HTTPException(422, f'不支持的币种：{currency}，可选 {"、".join(SITE_CURRENCIES)}')
    return code


async def rate_rows(db):
    rows = (await db.execute(
        select(ExchangeRate, User.nickname, User.username).outerjoin(User, User.id == ExchangeRate.updated_by)
        .where(ExchangeRate.base_currency == 'CNY', ExchangeRate.target_currency.in_(SITE_CURRENCIES))
        .order_by(ExchangeRate.updated_at)
    )).all()
    return {rate.target_currency: (rate, nickname or username) for rate, nickname, username in rows}


async def unconverted_counts(db):
    rows = (await db.execute(
        select(FinanceRecord.currency, func.count()).where(FinanceRecord.cny_amount.is_(None))
        .group_by(FinanceRecord.currency)
    )).all()
    return dict(rows)


def dto(currency, entry, unconverted):
    rate, updater = entry or (None, None)
    return {
        'currency': currency,
        'base_currency': 'CNY',
        'rate': str(rate.rate) if rate else None,
        'source': rate.source if rate else None,
        'updated_by': str(rate.updated_by) if rate and rate.updated_by else None,
        'updated_by_name': updater,
        'updated_at': rate.updated_at.isoformat() if rate else None,
        'unconverted_records': unconverted.get(currency, 0),
    }


@router.get('')
async def list_rates(user: User = AUTH, db: AsyncSession = DB):
    operator(user)
    rows, unconverted = await rate_rows(db), await unconverted_counts(db)
    return {'items': [dto(c, rows.get(c), unconverted) for c in SITE_CURRENCIES]}


@router.put('/{currency}')
async def save_rate(currency: str, payload: RateIn, user: User = AUTH, db: AsyncSession = DB):
    operator(user)
    code = currency_code(currency)
    rows = (await db.scalars(
        select(ExchangeRate).where(ExchangeRate.base_currency == 'CNY', ExchangeRate.target_currency == code)
        .order_by(ExchangeRate.updated_at.desc()).with_for_update()
    )).all()
    # Keep a single row per currency so the sync never has to pick between conflicting rates.
    for extra in rows[1:]:
        await db.delete(extra)
    rate = rows[0] if rows else ExchangeRate(base_currency='CNY', target_currency=code)
    if not rows:
        db.add(rate)
    rate.rate, rate.source, rate.updated_by = payload.rate, 'manual', user.id
    rate.updated_at = func.now()
    recomputed = await recompute_cny(db, code, payload.rate, only_missing=not payload.recompute_all)
    await db.flush()
    await db.refresh(rate)
    entry = (rate, user.nickname or user.username)
    return {**dto(code, entry, await unconverted_counts(db)), 'recomputed_records': recomputed}
