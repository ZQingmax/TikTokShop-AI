"""DiscoveryDeduplicator: by source item ID (canonical URL is derived from it, so both keys agree)."""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models.discovery import DiscoveryResult
from app.models.sourcing import SourcingCandidate


class DiscoveryDeduplicator:
    async def insert_unique(self, db, task, normalized, discovered_at, expires_at) -> bool:
        """Within one task the DB unique key (task, platform, item) makes inserts idempotent across restarts."""
        stmt = insert(DiscoveryResult).values(
            task_id=task.id, owner_id=task.owner_id, source_platform=normalized.source_platform,
            source_item_id=normalized.source_item_id, canonical_url=normalized.canonical_url,
            provider=normalized.provider, search_keyword=normalized.keyword[:100], search_query=normalized.query[:400],
            search_position=normalized.position, discovered_at=discovered_at, snippet_title=normalized.snippet_title,
            snippet_expires_at=expires_at, status='discovered',
            source_snapshot=normalized.source_snapshot,
        ).on_conflict_do_nothing(constraint='uq_discovery_result_item').returning(DiscoveryResult.id)
        return (await db.scalar(stmt)) is not None

    async def annotate_existing(self, db, task, rows) -> dict:
        """Cross-task / candidate-pool dedupe. Existing candidates are reused, never re-created or re-collected."""
        ids = [r.source_item_id for r in rows]
        if not ids:
            return {'in_pool': 0, 'seen_before': 0}
        market = task.goal['target_market']
        pool = {c.source_product_id: c.id for c in (await db.scalars(select(SourcingCandidate).where(
            SourcingCandidate.owner_id == task.owner_id, SourcingCandidate.target_market == market,
            SourcingCandidate.source_platform == '1688', SourcingCandidate.source_product_id.in_(ids)))).all()}
        seen = {sid: tid for sid, tid in (await db.execute(select(DiscoveryResult.source_item_id, DiscoveryResult.task_id).where(
            DiscoveryResult.owner_id == task.owner_id, DiscoveryResult.task_id != task.id,
            DiscoveryResult.source_item_id.in_(ids)))).all()}
        for row in rows:
            notes = []
            if row.source_item_id in pool:
                row.prior_candidate_id = pool[row.source_item_id]
                notes.append('已在候选池（同站点），复用现有候选，不重复采集')
            if row.source_item_id in seen:
                notes.append(f'此前发现任务 {seen[row.source_item_id]} 已发现过')
            if notes:
                row.status_reason = '；'.join(notes)
        return {'in_pool': sum(r.source_item_id in pool for r in rows), 'seen_before': sum(r.source_item_id in seen for r in rows)}
