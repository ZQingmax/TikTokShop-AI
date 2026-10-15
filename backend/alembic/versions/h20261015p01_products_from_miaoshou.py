"""Products are synced from the Miaoshou TikTok collect box instead of seeded mock rows."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'h20261015p01'
down_revision = 'g20261015l01'
branch_labels = depends_on = None


def upgrade():
    op.alter_column('products', 'cost_price', existing_type=sa.Numeric(12, 2), nullable=True)
    op.add_column('products', sa.Column('miaoshou_detail_id', sa.String(32)))
    op.add_column('products', sa.Column('common_detail_id', sa.String(32)))
    op.add_column('products', sa.Column('miaoshou_status', sa.String(20)))
    op.add_column('products', sa.Column('market', sa.String(2)))
    op.add_column('products', sa.Column('shop_ids', postgresql.JSONB, server_default='[]', nullable=False))
    op.add_column('products', sa.Column('thumbnail', sa.String(2000)))
    op.add_column('products', sa.Column('item_num', sa.String(100)))
    op.add_column('products', sa.Column('stock', sa.Integer))
    op.add_column('products', sa.Column('sale_price_max', sa.Numeric(12, 2)))
    op.add_column('products', sa.Column('sku_count', sa.Integer))
    op.add_column('products', sa.Column('cost_source', sa.String(20)))
    op.add_column('products', sa.Column('sale_currency', sa.String(3)))
    op.add_column('products', sa.Column('cost_currency', sa.String(3)))
    op.add_column('products', sa.Column('sourcing_candidate_id', postgresql.UUID(as_uuid=True),
                                        sa.ForeignKey('sourcing_candidates.id', ondelete='SET NULL')))
    op.add_column('products', sa.Column('synced_at', sa.DateTime(timezone=True)))
    op.create_index('uq_products_miaoshou_detail', 'products', ['miaoshou_detail_id'], unique=True)
    op.create_index('ix_products_miaoshou_status', 'products', ['miaoshou_status'])


def downgrade():
    op.drop_index('ix_products_miaoshou_status', 'products')
    op.drop_index('uq_products_miaoshou_detail', 'products')
    for column in ('synced_at', 'sourcing_candidate_id', 'cost_currency', 'sale_currency', 'cost_source', 'sku_count', 'sale_price_max', 'stock', 'item_num', 'thumbnail',
                   'shop_ids', 'market', 'miaoshou_status', 'common_detail_id', 'miaoshou_detail_id'):
        op.drop_column('products', column)
    # The old schema had no "unknown" cost; it used 0.00.
    op.execute('UPDATE products SET cost_price = 0 WHERE cost_price IS NULL')
    op.alter_column('products', 'cost_price', existing_type=sa.Numeric(12, 2), nullable=False)
