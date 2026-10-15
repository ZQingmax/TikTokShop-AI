"""Orders, purchase orders, shipments and finance records synced from Miaoshou instead of seeded rows.

A TikTok order can be split into several Miaoshou packages, so orders are keyed by package ID and
tiktok_order_id is no longer unique. Finance amounts without a known CNY rate keep cny_amount NULL.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'i20261015o01'
down_revision = 'h20261015p01'
branch_labels = depends_on = None

MONEY = sa.Numeric(14, 2)
ORDER_COLUMNS = (
    ('miaoshou_package_id', sa.String(32)), ('app_package_status', sa.String(40)), ('status_text', sa.String(100)),
    ('platform_status', sa.String(60)), ('shop_id', sa.String(32)), ('shop_name', sa.String(200)), ('site', sa.String(8)),
    ('product_amount', MONEY), ('commission_fee', MONEY), ('escrow_amount', MONEY), ('shipping_fee', MONEY),
    ('ordered_at', sa.DateTime(timezone=True)), ('paid_at', sa.DateTime(timezone=True)),
    ('ship_by_at', sa.DateTime(timezone=True)), ('shipped_at', sa.DateTime(timezone=True)),
    ('fulfillment_type', sa.String(40)), ('logistics', postgresql.JSONB), ('raw', postgresql.JSONB),
    ('synced_at', sa.DateTime(timezone=True)),
)
PO_COLUMNS = (
    ('miaoshou_po_id', sa.String(32)), ('po_sn', sa.String(64)), ('supplier_name', sa.String(200)),
    ('items', postgresql.JSONB), ('ordered_at', sa.DateTime(timezone=True)), ('raw', postgresql.JSONB),
    ('synced_at', sa.DateTime(timezone=True)),
)


def upgrade():
    op.drop_index('ix_orders_tiktok_order_id', 'orders')
    op.create_index('ix_orders_tiktok_order_id', 'orders', ['tiktok_order_id'])
    for name, column_type in ORDER_COLUMNS:
        op.add_column('orders', sa.Column(name, column_type))
    op.create_index('uq_orders_miaoshou_package', 'orders', ['miaoshou_package_id'], unique=True)
    op.create_index('ix_orders_ordered_at', 'orders', ['ordered_at'])
    op.add_column('order_items', sa.Column('image_url', sa.String(2000)))
    op.add_column('order_items', sa.Column('platform_sku_id', sa.String(100)))

    for name, column_type in PO_COLUMNS:
        op.add_column('purchase_orders', sa.Column(name, column_type))
    op.create_index('uq_purchase_orders_miaoshou', 'purchase_orders', ['miaoshou_po_id'], unique=True)
    op.add_column('shipments', sa.Column('miaoshou_package_id', sa.String(32)))
    op.create_index('uq_shipments_miaoshou_package', 'shipments', ['miaoshou_package_id'], unique=True)

    op.add_column('finance_records', sa.Column('miaoshou_package_id', sa.String(32)))
    op.create_index('uq_finance_package_type', 'finance_records', ['miaoshou_package_id', 'type'], unique=True)
    op.alter_column('finance_records', 'exchange_rate', existing_type=sa.Numeric(), nullable=True)
    op.alter_column('finance_records', 'cny_amount', existing_type=sa.Numeric(), nullable=True)

    op.create_table(
        'miaoshou_sync_state',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False, unique=True),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('succeeded_at', sa.DateTime(timezone=True)),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('counts', postgresql.JSONB, server_default='{}', nullable=False),
        sa.Column('error', sa.Text),
    )


def downgrade():
    op.drop_table('miaoshou_sync_state')
    # The old schema required a CNY amount; records without a known rate cannot be kept.
    op.execute('DELETE FROM finance_records WHERE cny_amount IS NULL OR exchange_rate IS NULL')
    op.alter_column('finance_records', 'cny_amount', existing_type=sa.Numeric(), nullable=False)
    op.alter_column('finance_records', 'exchange_rate', existing_type=sa.Numeric(), nullable=False)
    op.drop_index('uq_finance_package_type', 'finance_records')
    op.drop_column('finance_records', 'miaoshou_package_id')
    op.drop_index('uq_shipments_miaoshou_package', 'shipments')
    op.drop_column('shipments', 'miaoshou_package_id')
    op.drop_index('uq_purchase_orders_miaoshou', 'purchase_orders')
    for name, _ in PO_COLUMNS:
        op.drop_column('purchase_orders', name)
    op.drop_column('order_items', 'platform_sku_id')
    op.drop_column('order_items', 'image_url')
    op.drop_index('ix_orders_ordered_at', 'orders')
    op.drop_index('uq_orders_miaoshou_package', 'orders')
    for name, _ in ORDER_COLUMNS:
        op.drop_column('orders', name)
    op.drop_index('ix_orders_tiktok_order_id', 'orders')
    op.create_index('ix_orders_tiktok_order_id', 'orders', ['tiktok_order_id'], unique=True)
