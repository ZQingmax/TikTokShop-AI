"""System settings: roles and user roles, per-scenario model choices, model usage.

Everything requires a signed-in user. Changing a user's role and changing a model are admin-only:
a model change affects every operator's AI tasks and their cost, so operators can view but not change it.
"""
from datetime import date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.system_settings import ModelSetting, ModelUsageLog
from app.models.user import Role, User, UserRole
from app.services import model_settings
from app.services.workbench_config import WorkbenchSettings

router = APIRouter(prefix='/v1/system', tags=['System Settings'])
DB = Depends(get_db)
AUTH = Depends(get_current_user)
# Usage days follow the operators' calendar.
LOCAL_TZ = ZoneInfo('Asia/Shanghai')

# What each role can do, as enforced by the API today (role checks are `role in ('admin', 'operator')`).
ROLE_INFO = {
    'admin': {'summary': '系统管理员，拥有全部权限。',
              'permissions': ['运营人员的全部操作', '在系统设置中修改用户角色', '在系统设置中选择各场景使用的 AI 模型'],
              'restrictions': ['不能修改自己的角色，系统至少保留一名启用的管理员']},
    'operator': {'summary': '日常运营人员，可执行业务写操作。',
                 'permissions': ['商品管理、订单管理的修改操作', '选品中心、1688 货源、自动发现', '采集上架、商品工作台、AI 任务与刊登',
                                 '妙手同步', '维护人民币汇率', '查看模型设置与模型用量'],
                 'restrictions': ['不能修改用户角色', '不能修改模型设置']},
    'cs_agent': {'summary': '客服人员，以查看为主。',
                 'permissions': ['客服管理（该模块未限制角色）', '查看各页面数据', '查看模型设置与模型用量'],
                 'restrictions': ['商品、订单、选品、采集上架、工作台、刊登、妙手同步、汇率等写操作会被拒绝（403）',
                                  '不能修改用户角色和模型设置']},
    'finance': {'summary': '财务人员，以查看为主。',
                'permissions': ['查看财务、订单等各页面数据', '查看模型设置与模型用量'],
                'restrictions': ['汇率维护及商品、订单、选品等写操作会被拒绝（403）', '不能修改用户角色和模型设置']},
}
ROLE_LABELS = {'admin': '管理员', 'operator': '运营人员', 'cs_agent': '客服', 'finance': '财务'}


def admin_only(user, action):
    if user.role != 'admin':
        raise HTTPException(403, f'只有管理员可以{action}')


async def known_roles(db):
    rows = (await db.scalars(select(Role))).all()
    names = [r.name for r in rows] + [r.value for r in UserRole if r.value not in {x.name for x in rows}]
    return names, {r.name: r for r in rows}


def iso(value):
    return value.isoformat() if value else None


@router.get('/roles')
async def roles(db: AsyncSession = DB, user: User = AUTH):
    names, rows = await known_roles(db)
    counts = dict((await db.execute(select(User.role, func.count()).group_by(User.role))).all())
    result = []
    for name in names:
        info = ROLE_INFO.get(name, {'summary': '未在代码中定义权限说明的角色，按非管理员 / 非运营处理（写操作会被拒绝）。',
                                    'permissions': [], 'restrictions': []})
        result.append({'name': name, 'display_name': ROLE_LABELS.get(name) or (rows[name].display_name if name in rows else name),
                       'description': rows[name].description if name in rows else None,
                       'user_count': counts.get(name, 0), **info})
    return {'roles': result, 'current_role': user.role, 'can_manage': user.role == 'admin'}


@router.get('/users')
async def users(db: AsyncSession = DB, user: User = AUTH):
    admin_only(user, '查看用户列表')
    rows = (await db.scalars(select(User).order_by(User.created_at))).all()
    return [{'id': str(u.id), 'username': u.username, 'nickname': u.nickname, 'role': u.role,
             'is_active': u.is_active, 'created_at': iso(u.created_at), 'is_self': u.id == user.id} for u in rows]


class RoleIn(BaseModel):
    role: str = Field(..., min_length=1, max_length=50)


@router.patch('/users/{user_id}/role')
async def change_role(user_id: UUID, data: RoleIn, db: AsyncSession = DB, user: User = AUTH):
    admin_only(user, '修改用户角色')
    names, _ = await known_roles(db)
    if data.role not in names:
        raise HTTPException(422, f'未知角色：{data.role}')
    if user_id == user.id:
        raise HTTPException(400, '不能修改自己的角色')
    # Serialise role changes so two admins cannot demote each other at the same moment.
    admins = (await db.scalars(select(User).where(User.role == 'admin').with_for_update())).all()
    target = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(404, '用户不存在')
    if target.role == 'admin' and data.role != 'admin' and not any(a.is_active and a.id != target.id for a in admins):
        raise HTTPException(400, '至少需要保留一名启用的管理员')
    target.role = data.role
    await db.commit()
    return {'id': str(target.id), 'username': target.username, 'nickname': target.nickname, 'role': target.role,
            'is_active': target.is_active, 'created_at': iso(target.created_at), 'is_self': False}


async def model_rows(db):
    settings = WorkbenchSettings()
    saved = await model_settings.saved_models(db)
    editors = {}
    ids = {row.updated_by for row in saved.values() if row.updated_by}
    if ids:
        editors = {u.id: u.nickname or u.username for u in (await db.scalars(select(User).where(User.id.in_(ids)))).all()}
    result = []
    for scenario in model_settings.SCENARIOS:
        row = saved.get(scenario['key'])
        default = model_settings.default_model(settings, scenario['key'])
        result.append({'key': scenario['key'], 'label': scenario['label'], 'used_in': scenario['used_in'],
                       'unit': scenario['unit'], 'candidates': scenario['candidates'], 'default_model': default,
                       'selected_model': row.model if row else None, 'effective_model': row.model if row else default,
                       'updated_by': editors.get(row.updated_by) if row else None,
                       'updated_at': iso(row.updated_at) if row else None})
    return result


@router.get('/models')
async def models(db: AsyncSession = DB, user: User = AUTH):
    return {'scenarios': await model_rows(db), 'can_edit': user.role == 'admin'}


class ModelIn(BaseModel):
    # None restores the configured default.
    model: str | None = Field(None, max_length=100)


@router.put('/models/{scenario}')
async def set_model(scenario: str, data: ModelIn, db: AsyncSession = DB, user: User = AUTH):
    admin_only(user, '修改模型设置')
    definition = model_settings.SCENARIO_BY_KEY.get(scenario)
    if definition is None:
        raise HTTPException(404, '未知的模型场景')
    row = await db.scalar(select(ModelSetting).where(ModelSetting.scenario == scenario).with_for_update())
    if data.model is None:
        if row:
            await db.delete(row)
    else:
        if data.model not in {c['id'] for c in definition['candidates']}:
            raise HTTPException(422, f'{data.model} 不是「{definition["label"]}」的候选模型')
        if row is None:
            db.add(ModelSetting(scenario=scenario, model=data.model, updated_by=user.id))
        else:
            row.model, row.updated_by = data.model, user.id
    await db.commit()
    return next(x for x in await model_rows(db) if x['key'] == scenario)


def group_values(columns):
    return [func.count().label('calls'),
            func.count().filter(ModelUsageLog.usage.is_(None) | (func.jsonb_typeof(ModelUsageLog.usage) == 'null')).label('missing_usage'),
            func.sum(ModelUsageLog.input_tokens).label('input_tokens'),
            func.sum(ModelUsageLog.output_tokens).label('output_tokens'),
            func.sum(ModelUsageLog.total_tokens).label('total_tokens'),
            func.sum(ModelUsageLog.input_images).label('input_images'),
            func.sum(ModelUsageLog.output_images).label('output_images'), *columns]


@router.get('/model-usage')
async def model_usage(start: Annotated[date | None, Query()] = None, end: Annotated[date | None, Query()] = None,
                      db: AsyncSession = DB, user: User = AUTH):
    end = end or datetime.now(LOCAL_TZ).date()
    start = start or end - timedelta(days=29)
    if start > end:
        raise HTTPException(422, '开始日期不能晚于结束日期')
    if (end - start).days > 366:
        raise HTTPException(422, '查询范围最多一年')
    since = datetime.combine(start, time.min, LOCAL_TZ)
    until = datetime.combine(end + timedelta(days=1), time.min, LOCAL_TZ)
    window = (ModelUsageLog.called_at >= since, ModelUsageLog.called_at < until)
    day = func.date(func.timezone('Asia/Shanghai', ModelUsageLog.called_at))

    async def grouped(*columns, order):
        query = select(*group_values(columns)).where(*window)
        if columns:
            query = query.group_by(*columns)
        return [dict(r._mapping) for r in (await db.execute(query.order_by(*order))).all()]

    totals = (await grouped(order=()))[0]
    by_scenario = await grouped(ModelUsageLog.scenario, order=(func.count().desc(),))
    for row in by_scenario:
        row['label'] = model_settings.USAGE_LABELS.get(row['scenario'], row['scenario'])
    by_model = await grouped(ModelUsageLog.provider, ModelUsageLog.model, order=(func.count().desc(),))
    by_date = await grouped(day.label('day'), order=(day.desc(),))
    for row in by_date:
        row['day'] = row['day'].isoformat()
    recent = (await db.execute(
        select(ModelUsageLog, User.nickname, User.username).outerjoin(User, User.id == ModelUsageLog.user_id)
        .where(*window).order_by(ModelUsageLog.called_at.desc()).limit(50))).all()
    return {'start': start.isoformat(), 'end': end.isoformat(), 'totals': totals,
            'by_scenario': by_scenario, 'by_model': by_model, 'by_date': by_date,
            'recent': [{'id': str(log.id), 'called_at': iso(log.called_at), 'provider': log.provider,
                        'scenario': log.scenario, 'label': model_settings.USAGE_LABELS.get(log.scenario, log.scenario),
                        'model': log.model, 'status': log.status, 'input_tokens': log.input_tokens,
                        'output_tokens': log.output_tokens, 'total_tokens': log.total_tokens,
                        'input_images': log.input_images, 'output_images': log.output_images,
                        'has_usage': log.usage is not None, 'user': nickname or username}
                       for log, nickname, username in recent]}
