"""FastMoss browser tasks and observed category catalogs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'c20261014f01'
down_revision = 'b20261013e01'
branch_labels = depends_on = None


def common():
    return [sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('owner_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('target_market', sa.String(2), nullable=False),
            sa.Column('categories', JSONB, nullable=False)]


def upgrade():
    op.create_table('fastmoss_catalogs', *common(),
                    sa.UniqueConstraint('owner_id', 'target_market', name='uq_fastmoss_catalog'))
    op.create_index('ix_fastmoss_catalogs_owner_id', 'fastmoss_catalogs', ['owner_id'])
    op.create_table('fastmoss_tasks', *common(),
        sa.Column('request_key', UUID(as_uuid=True), nullable=False),
        sa.Column('pages', sa.Integer, nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('progress', sa.String(500), nullable=False),
        sa.Column('category_results', JSONB, nullable=False),
        sa.Column('report_id', UUID(as_uuid=True), sa.ForeignKey('sourcing_market_reports.id')),
        sa.Column('raw_csv', sa.Text), sa.Column('row_count', sa.Integer, nullable=False),
        sa.Column('truncated', sa.Boolean, nullable=False), sa.Column('error', sa.String(500)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('owner_id', 'request_key', name='uq_fastmoss_request'),
        sa.CheckConstraint("status IN ('queued','running','succeeded','partial','failed')", name='ck_fastmoss_status'))
    op.create_index('ix_fastmoss_tasks_owner_id', 'fastmoss_tasks', ['owner_id'])
    op.create_index('ix_fastmoss_tasks_status', 'fastmoss_tasks', ['status'])


def downgrade():
    op.drop_table('fastmoss_tasks')
    op.drop_table('fastmoss_catalogs')
