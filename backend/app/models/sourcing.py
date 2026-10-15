"""Independent sourcing records; no platform publishing side effects."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class SourcingCandidate(Base):
    __tablename__ = 'sourcing_candidates'
    __table_args__ = (
        UniqueConstraint('owner_id', 'identity_key', 'target_market', name='uq_sourcing_identity'),
        CheckConstraint('purchase_price IS NULL OR purchase_price >= 0', name='ck_sourcing_price'),
        CheckConstraint("sourcing_status IN ('saved','to_analyze','to_review')", name='ck_sourcing_status'),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    identity_key: Mapped[str] = mapped_column(String(64))
    source_platform: Mapped[str] = mapped_column(String(30))
    source_product_id: Mapped[str | None] = mapped_column(String(100))
    miaoshou_detail_id: Mapped[str | None] = mapped_column(String(100), index=True)
    original_source_id: Mapped[str | None] = mapped_column(String(100))
    original_url: Mapped[str | None] = mapped_column(String(2000))
    product_url: Mapped[str] = mapped_column(String(2000))
    name: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default='')
    main_image: Mapped[str | None] = mapped_column(String(2000))
    images: Mapped[list] = mapped_column(JSONB, default=list)
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    skus: Mapped[list] = mapped_column(JSONB, default=list)
    category: Mapped[str | None] = mapped_column(String(200), index=True)
    supplier: Mapped[str | None] = mapped_column(String(500))
    target_market: Mapped[str] = mapped_column(String(2), index=True)
    data_source: Mapped[str] = mapped_column(String(30), default='manual')
    trust_status: Mapped[str] = mapped_column(String(30), default='user_provided')
    source_note: Mapped[str] = mapped_column(Text, default='')
    source_record: Mapped[dict | None] = mapped_column(JSONB)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    source_spu_price: Mapped[Decimal | None] = mapped_column(Numeric())
    source_stock: Mapped[int | None] = mapped_column(Integer)
    source_weight: Mapped[Decimal | None] = mapped_column(Numeric())
    source_supplier_info: Mapped[dict | None] = mapped_column(JSONB)
    source_meta_info: Mapped[dict | None] = mapped_column(JSONB)
    sync_status: Mapped[str] = mapped_column(String(30), default='not_synced', server_default='not_synced')
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completeness: Mapped[str] = mapped_column(String(30))
    version: Mapped[int] = mapped_column(Integer, default=1)
    review_status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    # 1688 CLI 货源字段：平台原始价格区间 / 起批量 / 采集时间，均为平台数据，不含人工维护信息
    source_price_min: Mapped[Decimal | None] = mapped_column(Numeric())
    source_price_max: Mapped[Decimal | None] = mapped_column(Numeric())
    min_order_quantity: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supplier_ref_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('sourcing_suppliers.id'), index=True)
    # 运营人员维护：再次采集同一商品时不会覆盖
    sourcing_status: Mapped[str] = mapped_column(String(20), default='saved', server_default='saved', index=True)
    operator_note: Mapped[str] = mapped_column(Text, default='', server_default='')
    market_evidence: Mapped[list] = mapped_column(JSONB, default=list, server_default='[]')
    collection_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class SourcingSupplier(Base):
    """货源供应商（平台公开信息）。platform_metrics 只存平台提供的指标，不存系统推算评分。"""
    __tablename__ = 'sourcing_suppliers'
    __table_args__ = (UniqueConstraint('owner_id', 'source_platform', 'supplier_key', name='uq_sourcing_supplier'),)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    source_platform: Mapped[str] = mapped_column(String(30))
    supplier_key: Mapped[str] = mapped_column(String(200))
    company_name: Mapped[str | None] = mapped_column(String(500))
    member_id: Mapped[str | None] = mapped_column(String(100))
    login_id: Mapped[str | None] = mapped_column(String(200))
    shop_url: Mapped[str | None] = mapped_column(String(2000))
    location: Mapped[dict | None] = mapped_column(JSONB)
    is_factory: Mapped[bool | None] = mapped_column(Boolean)
    platform_metrics: Mapped[dict | None] = mapped_column(JSONB)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourcingTask(Base):
    __tablename__ = 'sourcing_analysis_tasks'
    __table_args__ = (
        Index('uq_sourcing_active_analysis', 'candidate_id', 'input_version', 'signature', unique=True,
              postgresql_where=text("status IN ('queued', 'running', 'succeeded')")),
        CheckConstraint("status IN ('queued','running','succeeded','failed')", name='ck_sourcing_task_status'),
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('sourcing_candidates.id'), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('sourcing_analysis_tasks.id'))
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    input_version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    signature: Mapped[str] = mapped_column(String(64))
    model_config: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    stage: Mapped[str] = mapped_column(String(20), default='queued')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    vision_checkpoint: Mapped[dict | None] = mapped_column(JSONB)


class SourcingEvaluation(Base):
    __tablename__ = 'sourcing_ai_evaluations'
    __table_args__ = (CheckConstraint('visual_score BETWEEN 0 AND 100', name='ck_sourcing_visual_score'),)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('sourcing_candidates.id'), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('sourcing_analysis_tasks.id'), unique=True)
    input_version: Mapped[int] = mapped_column(Integer)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    visual_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    vision: Mapped[dict | None] = mapped_column(JSONB)
    text_analysis: Mapped[dict | None] = mapped_column(JSONB)
    text_status: Mapped[str] = mapped_column(String(30))
    rule_score: Mapped[int] = mapped_column(Integer)
    rule_basis: Mapped[list] = mapped_column(JSONB)
    evidence: Mapped[dict] = mapped_column(JSONB)


class SourcingReview(Base):
    __tablename__ = 'sourcing_reviews'
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('sourcing_candidates.id'), index=True)
    evaluation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('sourcing_ai_evaluations.id'))
    input_version: Mapped[int] = mapped_column(Integer)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text, default='')
    input_snapshot: Mapped[dict | None] = mapped_column(JSONB)


class MarketReport(Base):
    __tablename__ = 'sourcing_market_reports'
    __table_args__ = (UniqueConstraint('owner_id', 'fingerprint', name='uq_market_report_import'),)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(200))
    target_market: Mapped[str] = mapped_column(String(2))
    scope: Mapped[str] = mapped_column(String(20))
    fingerprint: Mapped[str] = mapped_column(String(64))
    rows: Mapped[list] = mapped_column(JSONB)


class MiaoshouSyncTask(Base):
    __tablename__ = 'sourcing_miaoshou_tasks'
    __table_args__ = (
        UniqueConstraint('owner_id', 'request_key', name='uq_miaoshou_request'),
        Index('uq_miaoshou_active_request', 'owner_id', 'fingerprint', unique=True,
              postgresql_where=text("status IN ('queued','running','waiting','uncertain')")),
        CheckConstraint("status IN ('queued','running','waiting','succeeded','failed','uncertain')", name='ck_miaoshou_status'),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    fingerprint: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    target_market: Mapped[str] = mapped_column(String(2))
    currency: Mapped[str] = mapped_column(String(3))
    items: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    stage: Mapped[str] = mapped_column(String(40), default='queued')
    external_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_response: Mapped[dict | None] = mapped_column(JSONB)
    poll_count: Mapped[int] = mapped_column(Integer, default=0)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
