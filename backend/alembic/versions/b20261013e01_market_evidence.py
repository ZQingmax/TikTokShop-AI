"""Market evidence, score-free evaluations and candidate collection decisions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'b20261013e01'
down_revision = 'a1688c11e001'
branch_labels = depends_on = None


def upgrade():
    op.create_table('sourcing_market_reports',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('owner_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('target_market', sa.String(2), nullable=False),
        sa.Column('scope', sa.String(20), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('rows', JSONB, nullable=False),
        sa.UniqueConstraint('owner_id', 'fingerprint', name='uq_market_report_import'))
    op.create_index('ix_sourcing_market_reports_owner_id', 'sourcing_market_reports', ['owner_id'])
    op.add_column('sourcing_candidates', sa.Column('market_evidence', JSONB, nullable=False, server_default='[]'))
    op.add_column('sourcing_candidates', sa.Column('collection_task_id', UUID(as_uuid=True), nullable=True))
    op.add_column('discovery_results', sa.Column('source_snapshot', JSONB, nullable=True))
    op.add_column('sourcing_reviews', sa.Column('input_snapshot', JSONB, nullable=True))
    op.alter_column('sourcing_reviews', 'evaluation_id', nullable=True)
    op.alter_column('sourcing_ai_evaluations', 'visual_score', nullable=True)
    op.alter_column('sourcing_ai_evaluations', 'vision', nullable=True)
    # New workers must never resume the old collect-before-selection workflow.
    op.execute("UPDATE discovery_tasks SET status='cancelled', next_run_at=NULL, lease_token=NULL, lease_until=NULL, "
               "finished_at=now(), progress_message='流程已升级，请重新创建证据选品任务；已提交妙手任务仍可查询' "
               "WHERE status IN ('queued','planning','searching','filtering','awaiting_confirmation','collecting','analyzing')")
    op.execute("UPDATE sourcing_analysis_tasks SET status='failed', error_code='workflow_upgraded', "
               "error_message='已移除视觉评分，请重新提交文字证据分析', lease_token=NULL, lease_until=NULL, finished_at=now() "
               "WHERE status IN ('queued','running')")


def downgrade():
    # Downgrading would require inventing scores for new records. Preserve data instead.
    raise RuntimeError('This migration cannot be reversed without losing score-free evaluations; restore a backup instead')
