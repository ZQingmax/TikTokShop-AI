"""Product editing workbench; preserves drafts when source box entries are removed."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = 'e20261014w01'
down_revision = 'd20261014a01'
branch_labels = depends_on = None


def common():
    return [sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('owner_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False)]


def upgrade():
    op.create_table('workbench_drafts', *common(),
        sa.Column('collect_item_id', UUID(as_uuid=True), sa.ForeignKey('my_collect_box_items.id', ondelete='SET NULL')),
        sa.Column('source_key', sa.String(100), nullable=False), sa.Column('shop_key', sa.String(100), nullable=False),
        sa.Column('shop_id', sa.BigInteger()), sa.Column('market', sa.String(2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False), sa.Column('language', sa.String(12), nullable=False),
        sa.Column('source_snapshot', JSONB(), nullable=False), sa.Column('content', JSONB(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('checked_version', sa.Integer()),
        sa.Column('validation', JSONB()), sa.Column('synced_version', sa.Integer()),
        sa.Column('common_detail_id', sa.String(100)), sa.Column('platform_detail_id', sa.String(100)),
        sa.Column('remote_snapshot', JSONB()), sa.Column('remote_md5', sa.String(200)),
        sa.UniqueConstraint('owner_id', 'source_key', 'shop_key', name='uq_workbench_source_shop'),
        sa.CheckConstraint('version > 0', name='ck_workbench_version'))
    op.create_table('workbench_assets', *common(),
        sa.Column('draft_id', UUID(as_uuid=True), sa.ForeignKey('workbench_drafts.id'), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False), sa.Column('public_url', sa.Text()),
        sa.Column('local_name', sa.String(100)), sa.Column('sha256', sa.String(64)),
        sa.Column('width', sa.Integer()), sa.Column('height', sa.Integer()), sa.Column('mime', sa.String(50)),
        sa.Column('bytes', sa.Integer()), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('evidence', JSONB(), nullable=False))
    op.create_table('workbench_tasks', *common(),
        sa.Column('draft_id', UUID(as_uuid=True), sa.ForeignKey('workbench_drafts.id'), nullable=False),
        sa.Column('request_key', UUID(as_uuid=True), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False), sa.Column('input_version', sa.Integer(), nullable=False),
        sa.Column('snapshot', JSONB(), nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('stage', sa.String(50), nullable=False), sa.Column('result', JSONB(), nullable=False),
        sa.Column('steps', JSONB(), nullable=False), sa.Column('error_code', sa.String(100)), sa.Column('error_message', sa.Text()),
        sa.Column('lease_token', UUID(as_uuid=True)), sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('next_poll_at', sa.DateTime(timezone=True)), sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('adopted_version', sa.Integer()),
        sa.UniqueConstraint('owner_id', 'request_key', name='uq_workbench_request'),
        sa.CheckConstraint("status IN ('queued','running','waiting','succeeded','failed','uncertain')", name='ck_workbench_task_status'))
    for table, fields in [('workbench_drafts', ['owner_id', 'market']),
                          ('workbench_assets', ['owner_id', 'draft_id']),
                          ('workbench_tasks', ['owner_id', 'draft_id', 'status'])]:
        for field in fields:
            op.create_index(f'ix_{table}_{field}', table, [field])


def downgrade():
    for table in ('workbench_tasks', 'workbench_assets', 'workbench_drafts'):
        op.drop_table(table)
