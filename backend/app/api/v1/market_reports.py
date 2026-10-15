"""Preview before import, immutable owner-scoped market reports."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.sourcing import MarketReport
from app.models.user import User
from app.schemas.sourcing import Market
from app.services.market_evidence import ReportUpload, parse_report, report_fingerprint

router = APIRouter(prefix='/v1/sourcing/market-reports', tags=['Market evidence'])


def dto(row):
    return {k: getattr(row, k) for k in ('id', 'name', 'target_market', 'scope', 'rows', 'created_at')}


@router.post('/preview')
async def preview(data: ReportUpload, user: User = Depends(get_current_user)):
    rows = parse_report(data)
    return {'rows': rows, 'total': len(rows), 'target_market': data.target_market, 'scope': data.scope}


@router.post('', status_code=201)
async def import_report(data: ReportUpload, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = parse_report(data)
    fingerprint = report_fingerprint(data, rows)
    new_id = await db.scalar(insert(MarketReport).values(id=uuid.uuid4(), owner_id=user.id, name=data.name,
        target_market=data.target_market, scope=data.scope, rows=rows, fingerprint=fingerprint)
        .on_conflict_do_nothing(constraint='uq_market_report_import').returning(MarketReport.id))
    report = await db.scalar(select(MarketReport).where(MarketReport.owner_id == user.id,
                                                       MarketReport.fingerprint == fingerprint))
    return {**dto(report), 'reused': new_id is None}


@router.get('')
async def reports(target_market: Market = 'MY', page: int = Query(1, ge=1),
                  db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(MarketReport).where(MarketReport.owner_id == user.id, MarketReport.target_market == target_market)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(MarketReport.created_at.desc()).offset((page - 1) * 20).limit(20))).all()
    return {'items': [dto(r) for r in rows], 'total': total, 'page': page, 'page_size': 20}


@router.get('/{report_id}')
async def report_detail(report_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from fastapi import HTTPException
    report = await db.scalar(select(MarketReport).where(MarketReport.id == report_id, MarketReport.owner_id == user.id))
    if report is None:
        raise HTTPException(404, '榜单不存在')
    return dto(report)
