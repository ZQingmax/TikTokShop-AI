"""Repair the orphan duplicate revision. Initial already owns all 23 tables.

Existing databases stamped only 002 require a schema audit before adoption.
No table is created or removed here; downgrading this marker preserves data.
"""
from alembic import op
from sqlalchemy import inspect

revision = "002"
down_revision = "f950df57a1e2"
branch_labels = None
depends_on = None


def upgrade():
    required = {"forwarders", "sku_mappings", "match_records", "alerts", "faqs"}
    if not required.issubset(inspect(op.get_bind()).get_table_names()):
        raise RuntimeError("Initial schema missing; audit legacy database before upgrading")


def downgrade():
    pass
