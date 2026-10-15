"""System settings: per-scenario model choices and the model usage ledger."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ModelSetting(Base):
    """The model chosen for one AI scenario. No row means the scenario keeps its configured default."""

    __tablename__ = 'model_settings'

    scenario: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)


class ModelUsageLog(Base):
    """One billable model call. Token / image counts come only from the provider's usage; NULL means not returned."""

    __tablename__ = 'model_usage_logs'

    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    scenario: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='succeeded')
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    input_images: Mapped[int | None] = mapped_column(Integer)
    output_images: Mapped[int | None] = mapped_column(Integer)
    # none_as_null: a missing usage is SQL NULL, never JSON null, so 'not returned' is countable.
    usage: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    request_id: Mapped[str | None] = mapped_column(String(200))
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[str | None] = mapped_column(String(64), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'))
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # request_id is the provider's id for the billed call (for async image translation: its task id),
    # so a call is never logged twice even if a resumed worker reports it again.
    __table_args__ = (Index('uq_model_usage_request', 'provider', 'request_id', unique=True,
                            postgresql_where=text('request_id IS NOT NULL')),)
