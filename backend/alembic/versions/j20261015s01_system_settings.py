"""System settings: token version for password changes, per-scenario model choices, model usage ledger.

The ledger is backfilled from workbench tasks that already received a Bailian response, using only the
usage those responses returned (NULL when absent). Image translation is billed only on success, so only
translate tasks with a result image are copied.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'j20261015s01'
down_revision = 'i20261015o01'
branch_labels = depends_on = None


def timestamps():
    return (sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def upgrade():
    op.add_column('users', sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'))
    op.create_table(
        'model_settings', *timestamps(),
        sa.Column('scenario', sa.String(50), nullable=False, unique=True),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True))
    op.create_table(
        'model_usage_logs', *timestamps(),
        sa.Column('provider', sa.String(30), nullable=False),
        sa.Column('scenario', sa.String(50), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('input_tokens', sa.Integer()), sa.Column('output_tokens', sa.Integer()),
        sa.Column('total_tokens', sa.Integer()), sa.Column('input_images', sa.Integer()),
        sa.Column('output_images', sa.Integer()), sa.Column('usage', postgresql.JSONB()),
        sa.Column('request_id', sa.String(200)), sa.Column('source_type', sa.String(40)),
        sa.Column('source_id', sa.String(64)),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('called_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_model_usage_logs_scenario', 'model_usage_logs', ['scenario'])
    op.create_index('ix_model_usage_logs_model', 'model_usage_logs', ['model'])
    op.create_index('ix_model_usage_logs_source_id', 'model_usage_logs', ['source_id'])
    op.create_index('ix_model_usage_logs_called_at', 'model_usage_logs', ['called_at'])
    op.create_index('uq_model_usage_request', 'model_usage_logs', ['provider', 'request_id'], unique=True,
                    postgresql_where=sa.text('request_id IS NOT NULL'))
    op.execute("""
        INSERT INTO model_usage_logs (id, provider, scenario, model, status, input_tokens, output_tokens, total_tokens,
                                      input_images, output_images, usage, request_id, source_type, source_id, user_id, called_at)
        SELECT gen_random_uuid(), 'bailian',
               CASE kind WHEN 'ocr' THEN 'workbench_ocr' WHEN 'copy' THEN 'workbench_copy' WHEN 'fill' THEN 'workbench_fill'
                         WHEN 'translate' THEN 'workbench_translate' ELSE 'workbench_image' END,
               left(result->>'model', 100),
               CASE WHEN status = 'succeeded' THEN 'succeeded' ELSE 'rejected' END,
               CASE WHEN jsonb_typeof(u->'prompt_tokens') = 'number' THEN (u->>'prompt_tokens')::int END,
               CASE WHEN jsonb_typeof(u->'completion_tokens') = 'number' THEN (u->>'completion_tokens')::int END,
               CASE WHEN jsonb_typeof(u->'total_tokens') = 'number' THEN (u->>'total_tokens')::int END,
               CASE WHEN jsonb_typeof(u->'input_image_count') = 'number' THEN (u->>'input_image_count')::int END,
               CASE WHEN jsonb_typeof(u->'output_image_count') = 'number' THEN (u->>'output_image_count')::int
                    WHEN jsonb_typeof(u->'image_count') = 'number' THEN (u->>'image_count')::int END,
               CASE WHEN jsonb_typeof(u) = 'object' THEN u END,
               left(CASE WHEN kind = 'translate' THEN coalesce(result->>'upstream_task_id', result->>'request_id')
                         ELSE result->>'request_id' END, 200), 'workbench_task', id::text, owner_id,
               coalesce(finished_at, updated_at, created_at)
        FROM (SELECT *, result->'usage' AS u FROM workbench_tasks) t
        WHERE kind IN ('ocr', 'copy', 'fill', 'generate', 'edit', 'translate')
          AND coalesce(result->>'model', '') <> ''
          AND (kind <> 'translate' OR result ? 'image_url')
        ON CONFLICT DO NOTHING
    """)


def downgrade():
    op.drop_table('model_usage_logs')
    op.drop_table('model_settings')
    op.drop_column('users', 'token_version')
