"""Versioned editorial drafts, durable assets and fenced workbench jobs."""
import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, String, Text, Integer, BigInteger, DateTime, UniqueConstraint, CheckConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class WorkbenchDraft(Base):
    __tablename__ = 'workbench_drafts'
    __mapper_args__ = {'eager_defaults': True}
    __table_args__ = (
        # One active draft per source product; the target shop is an editable property of it.
        Index('uq_workbench_source_active', 'owner_id', 'source_key', unique=True, postgresql_where=text('archived_at IS NULL')),
        CheckConstraint('version > 0', name='ck_workbench_version'),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    collect_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('my_collect_box_items.id', ondelete='SET NULL'))
    source_key: Mapped[str] = mapped_column(String(100))
    shop_key: Mapped[str] = mapped_column(String(100), default='unassigned')
    shop_id: Mapped[int | None] = mapped_column(BigInteger)
    market: Mapped[str] = mapped_column(String(2), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    language: Mapped[str] = mapped_column(String(12), default='en')
    source_snapshot: Mapped[dict] = mapped_column(JSONB)
    content: Mapped[dict] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    checked_version: Mapped[int | None] = mapped_column(Integer)
    validation: Mapped[dict | None] = mapped_column(JSONB)
    synced_version: Mapped[int | None] = mapped_column(Integer)
    common_detail_id: Mapped[str | None] = mapped_column(String(100))
    platform_detail_id: Mapped[str | None] = mapped_column(String(100))
    remote_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    remote_md5: Mapped[str | None] = mapped_column(String(200))
    # Set when merged into another draft of the same source; kept for recovery, hidden everywhere.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkbenchAsset(Base):
    __tablename__ = 'workbench_assets'
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('workbench_drafts.id'), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    public_url: Mapped[str | None] = mapped_column(Text)
    local_name: Mapped[str | None] = mapped_column(String(100))
    sha256: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    mime: Mapped[str | None] = mapped_column(String(50))
    bytes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)


class WorkbenchTask(Base):
    __tablename__ = 'workbench_tasks'
    __table_args__ = (
        UniqueConstraint('owner_id', 'request_key', name='uq_workbench_request'),
        CheckConstraint("status IN ('queued','running','waiting','succeeded','failed','uncertain')", name='ck_workbench_task_status'),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('workbench_drafts.id'), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    fingerprint: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    input_version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    stage: Mapped[str] = mapped_column(String(50), default='queued')
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    steps: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adopted_version: Mapped[int | None] = mapped_column(Integer)
