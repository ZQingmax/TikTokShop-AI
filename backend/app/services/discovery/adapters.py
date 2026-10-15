"""Source search adapters. Search is decoupled from Miaoshou detail collection.

关键词搜索通过统一的 Alibaba1688Provider（1688 CLI，用户本人登录会话，只读）完成；
本模块不再自行实现任何搜索或抓取逻辑。
"""
from app.services.alibaba1688.errors import Alibaba1688Error
from app.services.alibaba1688.provider import Alibaba1688Provider, get_provider
from app.services.discovery.base import DiscoveryError, DiscoveryProvider, SearchHit, SearchPage, SourceSearchAdapter

# Alibaba1688Error.state → DiscoveryError.category（编排器据此决定终止 / 冷却 / 跳过）
ERROR_CATEGORIES = {
    'cli_not_installed': 'configuration', 'adapter_error': 'configuration', 'browser_error': 'configuration',
    'not_logged_in': 'auth', 'login_expired': 'auth', 'risk_control': 'permission',
    'busy': 'rate_limit', 'timeout': 'timeout', 'network_error': 'network', 'bad_input': 'input',
    'contract_changed': 'response',
}


class Alibaba1688CliDiscoveryProvider(DiscoveryProvider):
    """把 1688 CLI 关键词搜索包装为 DiscoveryProvider。CLI 不分页：只有第 0 页有结果。"""
    name = '1688_cli'

    def __init__(self, provider: Alibaba1688Provider | None = None, max_results: int = 20):
        self._provider = provider
        self.max_results = max_results

    @property
    def provider(self) -> Alibaba1688Provider:
        return self._provider or get_provider()

    def status(self) -> dict:
        transport = self.provider.transport
        available = transport.available()
        return {'name': self.name, 'available': available, 'keyword_search': True,
                'reason': '1688 CLI（用户本人登录会话，只读搜索）；登录状态见“1688 货源中心”' if available
                else '未检测到 1688 CLI 或 CLI Adapter，请先安装并登录：npm install -g 1688-cli；1688 login'}

    async def search(self, query: str, page: int = 0, count: int = 20) -> SearchPage:
        if page > 0:
            return SearchPage(hits=[], more_available=False, meta={'reason': 'CLI 搜索不分页'})
        try:
            result = await self.provider.search(query, max_results=min(count, self.max_results))
        except Alibaba1688Error as e:
            raise DiscoveryError(e.state, f'{e.message}。{e.to_dict()["hint"] or ""}'.rstrip('。'),
                                 ERROR_CATEGORIES.get(e.state, 'upstream'), e.retryable) from None
        hits = [SearchHit(item['product_url'], item['title'] or '', '', index, item)
                for index, item in enumerate(result['items'], 1)]
        return SearchPage(hits=hits, more_available=False,
                          meta={'cached': result.get('cached', False), 'total_before_filter': result.get('total_before_filter')})


class Alibaba1688CliSearchAdapter(SourceSearchAdapter):
    """规划关键词 → 1688 CLI 搜索 → 提取 offer ID → 妙手 fetch_item 采集真实详情。
    CLI 不支持排除词语法，排除词由 DiscoveryResultNormalizer 按标题过滤。"""
    source_platform = '1688'

    def status(self) -> dict:
        provider = self.provider.status()
        return {'name': '1688_cli_search', 'source_platform': '1688', 'provider': provider['name'],
                'available': provider['available'], 'keyword_search': True,
                'method': '1688 CLI 关键词搜索 → 提取 offer ID → 妙手 fetch_item 采集真实详情',
                'reason': provider['reason']}

    def build_query(self, keyword: str, exclude_words: list[str]) -> str:
        keyword = ' '.join(keyword.split())
        if not keyword or len(keyword) > 50:
            raise DiscoveryError('invalid_keyword', '关键词为空或超长', 'input')
        return keyword


class Alibaba1688OfficialSearchAdapter(SourceSearchAdapter):
    """Reserved for 1688 Open Platform cross-border keyword search. Not authorized for this account yet:
    the request protocol is NOT implemented by guessing; it stays unavailable until credentials and the
    console documentation are provided."""
    source_platform = '1688'

    def __init__(self):
        super().__init__(provider=None)  # type: ignore[arg-type]

    def status(self) -> dict:
        return {'name': '1688_official_search', 'source_platform': '1688', 'provider': '1688_open_platform',
                'available': False, 'keyword_search': True,
                'reason': '需企业 1688 账号申请开放平台应用及跨境解决方案权限；当前未授权、未配置，不调用'}

    def build_query(self, keyword, exclude_words):
        raise DiscoveryError('source_unavailable', self.status()['reason'], 'configuration')

    async def search(self, query: str, page: int) -> SearchPage:
        raise DiscoveryError('source_unavailable', self.status()['reason'], 'configuration')


def default_adapter(provider: DiscoveryProvider | None = None) -> SourceSearchAdapter:
    return Alibaba1688CliSearchAdapter(provider or Alibaba1688CliDiscoveryProvider())
