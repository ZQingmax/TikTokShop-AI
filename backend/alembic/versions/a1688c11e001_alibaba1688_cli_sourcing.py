"""alibaba1688_cli_sourcing: 1688 CLI 货源字段与供应商表（只新增，不修改、不删除已有数据）

Revision ID: a1688c11e001
Revises: 7c3e9a1d2f40
Create Date: 2026-10-13 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1688c11e001'
down_revision: Union[str, None] = '7c3e9a1d2f40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('sourcing_suppliers',
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('source_platform', sa.String(length=30), nullable=False),
    sa.Column('supplier_key', sa.String(length=200), nullable=False),
    sa.Column('company_name', sa.String(length=500), nullable=True),
    sa.Column('member_id', sa.String(length=100), nullable=True),
    sa.Column('login_id', sa.String(length=200), nullable=True),
    sa.Column('shop_url', sa.String(length=2000), nullable=True),
    sa.Column('location', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('is_factory', sa.Boolean(), nullable=True),
    sa.Column('platform_metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('raw_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'source_platform', 'supplier_key', name='uq_sourcing_supplier')
    )
    op.create_index(op.f('ix_sourcing_suppliers_owner_id'), 'sourcing_suppliers', ['owner_id'], unique=False)

    # 已有候选记录获得默认值 saved / ''，其余新列为空；不改动任何既有列
    op.add_column('sourcing_candidates', sa.Column('source_price_min', sa.Numeric(), nullable=True))
    op.add_column('sourcing_candidates', sa.Column('source_price_max', sa.Numeric(), nullable=True))
    op.add_column('sourcing_candidates', sa.Column('min_order_quantity', sa.Integer(), nullable=True))
    op.add_column('sourcing_candidates', sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sourcing_candidates', sa.Column('supplier_ref_id', sa.UUID(), nullable=True))
    op.add_column('sourcing_candidates', sa.Column('sourcing_status', sa.String(length=20), server_default='saved', nullable=False))
    op.add_column('sourcing_candidates', sa.Column('operator_note', sa.Text(), server_default='', nullable=False))
    op.create_foreign_key('fk_sourcing_candidates_supplier_ref', 'sourcing_candidates', 'sourcing_suppliers', ['supplier_ref_id'], ['id'])
    op.create_index(op.f('ix_sourcing_candidates_supplier_ref_id'), 'sourcing_candidates', ['supplier_ref_id'], unique=False)
    op.create_index(op.f('ix_sourcing_candidates_sourcing_status'), 'sourcing_candidates', ['sourcing_status'], unique=False)
    op.create_check_constraint('ck_sourcing_status', 'sourcing_candidates', "sourcing_status IN ('saved','to_analyze','to_review')")


def downgrade() -> None:
    op.drop_constraint('ck_sourcing_status', 'sourcing_candidates', type_='check')
    op.drop_index(op.f('ix_sourcing_candidates_sourcing_status'), table_name='sourcing_candidates')
    op.drop_index(op.f('ix_sourcing_candidates_supplier_ref_id'), table_name='sourcing_candidates')
    op.drop_constraint('fk_sourcing_candidates_supplier_ref', 'sourcing_candidates', type_='foreignkey')
    for column in ('operator_note', 'sourcing_status', 'supplier_ref_id', 'fetched_at', 'min_order_quantity',
                   'source_price_max', 'source_price_min'):
        op.drop_column('sourcing_candidates', column)
    op.drop_index(op.f('ix_sourcing_suppliers_owner_id'), table_name='sourcing_suppliers')
    op.drop_table('sourcing_suppliers')
