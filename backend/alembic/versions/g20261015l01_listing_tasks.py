"""Listing tasks: pre-publish checks and publishing TK collect-box products to shops."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'g20261015l01'
down_revision = 'f20261014m01'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'listing_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('request_key', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('market', sa.String(2), nullable=False),
        sa.Column('items', postgresql.JSONB, nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('stage', sa.String(40), nullable=False),
        sa.Column('poll_count', sa.Integer, nullable=False),
        sa.Column('next_poll_at', sa.DateTime(timezone=True)),
        sa.Column('lease_token', postgresql.UUID(as_uuid=True)),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('error_code', sa.String(80)),
        sa.Column('error_message', sa.Text),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('owner_id', 'request_key', name='uq_listing_request'),
        sa.CheckConstraint("kind IN ('check','publish')", name='ck_listing_kind'),
        sa.CheckConstraint("status IN ('queued','running','waiting','succeeded','partial','failed','uncertain')", name='ck_listing_status'),
    )
    op.create_index('ix_listing_tasks_owner_id', 'listing_tasks', ['owner_id'])
    op.create_index('ix_listing_tasks_status', 'listing_tasks', ['status'])


def downgrade():
    op.drop_table('listing_tasks')
