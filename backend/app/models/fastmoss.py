"""Persistent local-browser collection jobs; reports remain immutable evidence."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class FastmossTask(Base):
    __tablename__ = 'fastmoss_tasks'
    __table_args__ = (
        UniqueConstraint('owner_id', 'request_key', name='uq_fastmoss_request'),
        CheckConstraint("status IN ('queued','running','succeeded','partial','failed')", name='ck_fastmoss_status'),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    target_market: Mapped[str] = mapped_column(String(2))
    categories: Mapped[list] = mapped_column(JSONB)
    pages: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    progress: Mapped[str] = mapped_column(String(500), default='等待本机 FastMoss Worker')
    category_results: Mapped[list] = mapped_column(JSONB, default=list)
    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('sourcing_market_reports.id'))
    raw_csv: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str | None] = mapped_column(String(500))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FastmossCatalog(Base):
    __tablename__ = 'fastmoss_catalogs'
    __table_args__ = (UniqueConstraint('owner_id', 'target_market', name='uq_fastmoss_catalog'),)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    target_market: Mapped[str] = mapped_column(String(2))
    categories: Mapped[list] = mapped_column(JSONB)
