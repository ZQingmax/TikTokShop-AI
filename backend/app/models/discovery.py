"""Persistent discovery agent tasks and results (independent from candidates/analysis tables)."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

TASK_STATUSES = ('queued', 'planning', 'searching', 'filtering', 'awaiting_confirmation', 'collecting',
                 'analyzing', 'completed', 'partial_failed', 'failed', 'cancelled')
ACTIVE_STATUSES = ('queued', 'planning', 'searching', 'filtering', 'awaiting_confirmation', 'collecting', 'analyzing')
RESULT_STATUSES = ('discovered', 'filtered_out', 'not_selected', 'selected', 'collecting', 'collected', 'collect_failed',
                   'incomplete', 'price_filtered', 'analyzing', 'analyzed', 'analysis_failed', 'ranked', 'skipped_budget')


class DiscoveryTask(Base):
    __tablename__ = 'discovery_tasks'
    __table_args__ = (
        UniqueConstraint('owner_id', 'request_key', name='uq_discovery_request'),
        Index('uq_discovery_active_goal', 'owner_id', 'fingerprint', unique=True,
              postgresql_where=text("status IN ('queued','planning','searching','filtering','awaiting_confirmation','collecting','analyzing')")),
        CheckConstraint("status IN ('" + "','".join(TASK_STATUSES) + "')", name='ck_discovery_task_status'),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    fingerprint: Mapped[str] = mapped_column(String(64))
    goal: Mapped[dict] = mapped_column(JSONB)
    auto_collect: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default='queued', index=True)
    # Stage at which the worker resumes after a restart; status is what users see.
    resume_stage: Mapped[str] = mapped_column(String(30), default='planning')
    progress_message: Mapped[str] = mapped_column(Text, default='')
    plan: Mapped[dict | None] = mapped_column(JSONB)
    search_log: Mapped[list] = mapped_column(JSONB, default=list)
    budget: Mapped[dict] = mapped_column(JSONB)
    usage: Mapped[dict] = mapped_column(JSONB)
    stage_errors: Mapped[list] = mapped_column(JSONB, default=list)
    collect_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('sourcing_miaoshou_tasks.id'))
    collect_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wait_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscoveryResult(Base):
    __tablename__ = 'discovery_results'
    __table_args__ = (
        UniqueConstraint('task_id', 'source_platform', 'source_item_id', name='uq_discovery_result_item'),
        CheckConstraint("status IN ('" + "','".join(RESULT_STATUSES) + "')", name='ck_discovery_result_status'),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('discovery_tasks.id'), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    source_platform: Mapped[str] = mapped_column(String(20))
    source_item_id: Mapped[str] = mapped_column(String(32), index=True)
    canonical_url: Mapped[str] = mapped_column(String(300))
    provider: Mapped[str] = mapped_column(String(40))
    search_keyword: Mapped[str] = mapped_column(String(100))
    search_query: Mapped[str] = mapped_column(String(400))
    search_position: Mapped[int] = mapped_column(Integer)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Transient preview text from the search provider; purged after retention.
    snippet_title: Mapped[str | None] = mapped_column(String(300))
    source_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    snippet_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default='discovered', index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    prior_candidate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('sourcing_candidates.id'))
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('sourcing_candidates.id'), index=True)
    analysis_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('sourcing_analysis_tasks.id'))
    evaluation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('sourcing_ai_evaluations.id'))
    assessment: Mapped[dict | None] = mapped_column(JSONB)
    rank_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    rank_position: Mapped[int | None] = mapped_column(Integer)
