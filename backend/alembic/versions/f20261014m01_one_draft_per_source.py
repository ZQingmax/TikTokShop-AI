"""One active workbench draft per source product; duplicates are merged, never deleted.

Keeper per (owner, source): a synced draft first (it is linked to a platform product), then the
most recently edited. The keeper takes over a shop binding it lacks, plus the other drafts' tasks
and assets (task adoption is reset so their AI results can be adopted into the keeper). The other
drafts are archived: hidden from the editor but kept for recovery.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f20261014m01'
down_revision = 'e20261014w01'
branch_labels = depends_on = None


def upgrade():
    op.add_column('workbench_drafts', sa.Column('archived_at', sa.DateTime(timezone=True)))
    # Dropped first: a keeper taking over a shop shares that shop key with the draft it replaces.
    op.drop_constraint('uq_workbench_source_shop', 'workbench_drafts', type_='unique')
    op.execute("""
        CREATE TEMP TABLE workbench_draft_merge ON COMMIT DROP AS
        SELECT id, keeper FROM (
            SELECT id, first_value(id) OVER w AS keeper FROM workbench_drafts
            WINDOW w AS (PARTITION BY owner_id, source_key
                         ORDER BY (synced_version IS NOT NULL) DESC, updated_at DESC, id)
        ) ranked WHERE id <> keeper""")
    op.execute("""
        UPDATE workbench_drafts k SET shop_id = s.shop_id, shop_key = s.shop_key, version = k.version + 1,
               checked_version = NULL, validation = NULL, updated_at = now()
        FROM (SELECT DISTINCT ON (m.keeper) m.keeper, d.shop_id, d.shop_key
              FROM workbench_draft_merge m JOIN workbench_drafts d ON d.id = m.id
              WHERE d.shop_id IS NOT NULL ORDER BY m.keeper, d.updated_at DESC) s
        WHERE k.id = s.keeper AND k.shop_id IS NULL AND k.synced_version IS NULL""")
    op.execute("""UPDATE workbench_tasks t SET draft_id = m.keeper, adopted_version = NULL
                  FROM workbench_draft_merge m WHERE t.draft_id = m.id""")
    op.execute("""UPDATE workbench_assets a SET draft_id = m.keeper
                  FROM workbench_draft_merge m WHERE a.draft_id = m.id""")
    op.execute("""UPDATE workbench_drafts d SET archived_at = now()
                  FROM workbench_draft_merge m WHERE d.id = m.id""")
    op.create_index('uq_workbench_source_active', 'workbench_drafts', ['owner_id', 'source_key'], unique=True,
                    postgresql_where=sa.text('archived_at IS NULL'))


def downgrade():
    # Archived rows may share a source and shop with their keeper; restoring the old per-shop
    # constraint is only possible once such rows are resolved by hand.
    op.drop_index('uq_workbench_source_active', table_name='workbench_drafts')
    op.create_unique_constraint('uq_workbench_source_shop', 'workbench_drafts', ['owner_id', 'source_key', 'shop_key'])
    op.drop_column('workbench_drafts', 'archived_at')
