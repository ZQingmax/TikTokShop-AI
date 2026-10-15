"""My collect box items (local space, separate from Miaoshou collect boxes)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'd20261014a01'
down_revision = 'c20261014f01'
branch_labels = depends_on = None


def upgrade():
    op.create_table('my_collect_box_items',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('owner_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('candidate_id', UUID(as_uuid=True), sa.ForeignKey('sourcing_candidates.id'), nullable=False),
        sa.Column('source_product_id', sa.String(100)),
        sa.Column('product_url', sa.String(2000), nullable=False),
        sa.Column('name', sa.String(500)),
        sa.Column('main_image', sa.String(2000)),
        sa.Column('purchase_price', sa.Numeric(12, 2)),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('category', sa.String(200)),
        sa.Column('supplier', sa.String(500)),
        sa.Column('target_market', sa.String(2), nullable=False),
        sa.Column('note', sa.Text, server_default='', nullable=False),
        sa.Column('miaoshou_box', sa.String(10)),
        sa.Column('miaoshou_detail_id', sa.String(100)),
        sa.Column('sync_status', sa.String(20), server_default='not_synced', nullable=False),
        sa.Column('sync_task_id', UUID(as_uuid=True)),
        sa.Column('sync_error', sa.Text),
        sa.Column('synced_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('owner_id', 'candidate_id', name='uq_collect_box_candidate'),
        sa.CheckConstraint("sync_status IN ('not_synced','syncing','synced','failed')", name='ck_collect_box_sync_status'),
        sa.CheckConstraint("miaoshou_box IS NULL OR miaoshou_box IN ('common','tiktok')", name='ck_collect_box_target'))
    for column in ('owner_id', 'candidate_id', 'target_market', 'sync_status'):
        op.create_index(f'ix_my_collect_box_items_{column}', 'my_collect_box_items', [column])


def downgrade():
    op.drop_table('my_collect_box_items')
