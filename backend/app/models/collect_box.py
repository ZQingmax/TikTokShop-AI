"""我的采集箱：本系统内的待上架商品空间，与妙手 ERP 采集箱是两个独立的数据空间。"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class CollectBoxItem(Base):
    __tablename__ = 'my_collect_box_items'
    __table_args__ = (
        UniqueConstraint('owner_id', 'candidate_id', name='uq_collect_box_candidate'),
        CheckConstraint("sync_status IN ('not_synced','syncing','synced','failed')", name='ck_collect_box_sync_status'),
        CheckConstraint("miaoshou_box IS NULL OR miaoshou_box IN ('common','tiktok')", name='ck_collect_box_target'),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('sourcing_candidates.id'), index=True)
    # 加入时的商品快照；候选库后续修改不影响已加入的记录
    source_product_id: Mapped[str | None] = mapped_column(String(100))
    product_url: Mapped[str] = mapped_column(String(2000))
    name: Mapped[str | None] = mapped_column(String(500))
    main_image: Mapped[str | None] = mapped_column(String(2000))
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    category: Mapped[str | None] = mapped_column(String(200))
    supplier: Mapped[str | None] = mapped_column(String(500))
    target_market: Mapped[str] = mapped_column(String(2), index=True)
    note: Mapped[str] = mapped_column(Text, default='', server_default='')
    # 妙手同步状态：只记录本系统发起的同步结果，不代表妙手采集箱的实时状态
    miaoshou_box: Mapped[str | None] = mapped_column(String(10))
    miaoshou_detail_id: Mapped[str | None] = mapped_column(String(100))
    sync_status: Mapped[str] = mapped_column(String(20), default='not_synced', server_default='not_synced', index=True)
    sync_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sync_error: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
