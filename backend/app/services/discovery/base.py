"""Discovery interfaces.

DiscoveryProvider   — a search backend (1688 CLI keyword search, future 1688 official search ...).
SourceSearchAdapter — turns a planned keyword into provider queries for ONE source platform and
                      decides which hits belong to that platform. It never fetches product details;
                      details are collected later through the existing Miaoshou integration.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class DiscoveryError(Exception):
    """category: configuration | auth | permission | rate_limit | budget | input | upstream | network | timeout | response"""

    def __init__(self, code: str, message: str, category: str = 'upstream', retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.category, self.retryable = code, message, category, retryable


@dataclass
class SearchHit:
    url: str
    title: str
    description: str
    position: int
    source_snapshot: dict = field(default_factory=dict)


@dataclass
class SearchPage:
    hits: list[SearchHit]
    more_available: bool | None
    meta: dict = field(default_factory=dict)


class DiscoveryProvider(ABC):
    name: str = 'abstract'

    @abstractmethod
    def status(self) -> dict: ...

    @abstractmethod
    async def search(self, query: str, page: int = 0, count: int = 20) -> SearchPage: ...


class SourceSearchAdapter(ABC):
    source_platform: str = 'abstract'

    def __init__(self, provider: DiscoveryProvider):
        self.provider = provider

    @abstractmethod
    def status(self) -> dict: ...

    @abstractmethod
    def build_query(self, keyword: str, exclude_words: list[str]) -> str: ...

    async def search(self, query: str, page: int) -> SearchPage:
        return await self.provider.search(query, page)
