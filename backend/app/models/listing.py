"""Publishing TikTok collect-box products to shops through Miaoshou (#25), one task per batch."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class ListingTask(Base):
    __tablename__ = 'listing_tasks'
    __table_args__ = (
        UniqueConstraint('owner_id', 'request_key', name='uq_listing_request'),
        CheckConstraint("kind IN ('check','publish')", name='ck_listing_kind'),
        CheckConstraint("status IN ('queued','running','waiting','succeeded','partial','failed','uncertain')", name='ck_listing_status'),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    fingerprint: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    market: Mapped[str] = mapped_column(String(2))
    # [{detail_id, shop_id, title, state, errors, warnings, error, record}]
    items: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    stage: Mapped[str] = mapped_column(String(40), default='queued')
    poll_count: Mapped[int] = mapped_column(Integer, default=0)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
