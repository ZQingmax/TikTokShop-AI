"""discovery_agent: persistent auto-discovery tasks and results (new tables only)

Revision ID: 7c3e9a1d2f40
Revises: 554b31562dd4
Create Date: 2026-10-13 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '7c3e9a1d2f40'
down_revision: Union[str, None] = '554b31562dd4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TASK_STATUSES = ('queued', 'planning', 'searching', 'filtering', 'awaiting_confirmation', 'collecting',
                 'analyzing', 'completed', 'partial_failed', 'failed', 'cancelled')
RESULT_STATUSES = ('discovered', 'filtered_out', 'not_selected', 'selected', 'collecting', 'collected', 'collect_failed',
                   'incomplete', 'price_filtered', 'analyzing', 'analyzed', 'analysis_failed', 'ranked', 'skipped_budget')
ACTIVE = "status IN ('queued','planning','searching','filtering','awaiting_confirmation','collecting','analyzing')"


def upgrade() -> None:
    op.create_table('discovery_tasks',
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('request_key', sa.UUID(), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('goal', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('auto_collect', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('resume_stage', sa.String(length=30), nullable=False),
    sa.Column('progress_message', sa.Text(), nullable=False),
    sa.Column('plan', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('search_log', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('budget', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('usage', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('stage_errors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('collect_task_id', sa.UUID(), nullable=True),
    sa.Column('collect_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('wait_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lease_token', sa.UUID(), nullable=True),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('" + "','".join(TASK_STATUSES) + "')", name='ck_discovery_task_status'),
    sa.ForeignKeyConstraint(['collect_task_id'], ['sourcing_miaoshou_tasks.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'request_key', name='uq_discovery_request')
    )
    op.create_index(op.f('ix_discovery_tasks_owner_id'), 'discovery_tasks', ['owner_id'], unique=False)
    op.create_index(op.f('ix_discovery_tasks_status'), 'discovery_tasks', ['status'], unique=False)
    op.create_index('uq_discovery_active_goal', 'discovery_tasks', ['owner_id', 'fingerprint'], unique=True,
                    postgresql_where=sa.text(ACTIVE))
    op.create_table('discovery_results',
    sa.Column('task_id', sa.UUID(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('source_platform', sa.String(length=20), nullable=False),
    sa.Column('source_item_id', sa.String(length=32), nullable=False),
    sa.Column('canonical_url', sa.String(length=300), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('search_keyword', sa.String(length=100), nullable=False),
    sa.Column('search_query', sa.String(length=400), nullable=False),
    sa.Column('search_position', sa.Integer(), nullable=False),
    sa.Column('discovered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('snippet_title', sa.String(length=300), nullable=True),
    sa.Column('snippet_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('status_reason', sa.Text(), nullable=True),
    sa.Column('prior_candidate_id', sa.UUID(), nullable=True),
    sa.Column('candidate_id', sa.UUID(), nullable=True),
    sa.Column('analysis_task_id', sa.UUID(), nullable=True),
    sa.Column('evaluation_id', sa.UUID(), nullable=True),
    sa.Column('assessment', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('rank_score', sa.Numeric(precision=5, scale=1), nullable=True),
    sa.Column('rank_position', sa.Integer(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('" + "','".join(RESULT_STATUSES) + "')", name='ck_discovery_result_status'),
    sa.ForeignKeyConstraint(['analysis_task_id'], ['sourcing_analysis_tasks.id'], ),
    sa.ForeignKeyConstraint(['candidate_id'], ['sourcing_candidates.id'], ),
    sa.ForeignKeyConstraint(['evaluation_id'], ['sourcing_ai_evaluations.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['prior_candidate_id'], ['sourcing_candidates.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['discovery_tasks.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_id', 'source_platform', 'source_item_id', name='uq_discovery_result_item')
    )
    op.create_index(op.f('ix_discovery_results_candidate_id'), 'discovery_results', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_discovery_results_owner_id'), 'discovery_results', ['owner_id'], unique=False)
    op.create_index(op.f('ix_discovery_results_source_item_id'), 'discovery_results', ['source_item_id'], unique=False)
    op.create_index(op.f('ix_discovery_results_status'), 'discovery_results', ['status'], unique=False)
    op.create_index(op.f('ix_discovery_results_task_id'), 'discovery_results', ['task_id'], unique=False)


def downgrade() -> None:
    # Only drops the two tables created above; candidates, analyses and Miaoshou tasks are untouched.
    op.drop_table('discovery_results')
    op.drop_index('uq_discovery_active_goal', table_name='discovery_tasks', postgresql_where=sa.text(ACTIVE))
    op.drop_index(op.f('ix_discovery_tasks_status'), table_name='discovery_tasks')
    op.drop_index(op.f('ix_discovery_tasks_owner_id'), table_name='discovery_tasks')
    op.drop_table('discovery_tasks')
