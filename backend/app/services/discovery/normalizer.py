"""Turn raw search hits into a unified result structure, or a recorded rejection reason."""
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.services.discovery.base import SearchHit

OFFER_HOSTS = {'detail.1688.com', 'm.1688.com', 'detail.m.1688.com'}
OFFER_PATH = re.compile(r'^/offer/(\d{6,20})\.html/?$')


@dataclass
class NormalizedResult:
    source_platform: str
    source_item_id: str
    canonical_url: str
    snippet_title: str
    keyword: str
    query: str
    position: int
    provider: str
    source_snapshot: dict = field(default_factory=dict)


@dataclass
class Rejected:
    url: str
    reason: str


class DiscoveryResultNormalizer:
    """Only real offer URLs returned by the provider are accepted; nothing is inferred or completed."""

    def offer_id(self, url: str) -> str | None:
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        if parts.scheme not in ('http', 'https') or (parts.hostname or '').lower() not in OFFER_HOSTS:
            return None
        match = OFFER_PATH.match(parts.path)
        return match[1] if match else None

    def normalize(self, hit: SearchHit, keyword: str, query: str, provider: str,
                  exclude_words: list[str]) -> NormalizedResult | Rejected:
        item_id = self.offer_id(hit.url)
        if not item_id:
            return Rejected(hit.url, 'not_1688_offer_url')
        title = hit.title.strip()
        if not title:
            return Rejected(hit.url, 'missing_title')
        lowered = title.lower()
        for word in exclude_words:
            if word and word.lower() in lowered:
                return Rejected(hit.url, f'excluded_word:{word}')
        return NormalizedResult('1688', item_id, f'https://detail.1688.com/offer/{item_id}.html', title[:300],
                                keyword, query, hit.position, provider, hit.source_snapshot)
