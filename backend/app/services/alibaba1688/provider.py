"""Alibaba1688Provider：系统内唯一的 1688 货源入口（API 路由、Agent 工具都只调用这里）。

只读：搜索、详情、以图搜图、供应商搜索/画像、状态检测。不提供登录、退出、购物车、下单、联系卖家。
"""
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from app.services.alibaba1688 import normalize
from app.services.alibaba1688.commands import check_offer_id, check_supplier_target, clean_keyword
from app.services.alibaba1688.config import Alibaba1688Settings
from app.services.alibaba1688.errors import STATES, Alibaba1688Error
from app.services.alibaba1688.runner import LocalCliTransport, RemoteAdapterTransport, resolve_cli

IMAGE_TYPES = {'jpg': (b'\xff\xd8\xff',), 'png': (b'\x89PNG\r\n\x1a\n',)}


def sniff_image(content: bytes) -> str | None:
    """按文件头判断真实类型，不信任扩展名和 Content-Type。"""
    if content.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if content.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if len(content) >= 12 and content[:4] == b'RIFF' and content[8:12] == b'WEBP':
        return 'webp'
    return None


class TTLCache:
    def __init__(self, max_items: int = 300):
        self.max_items = max_items
        self._data: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        hit = self._data.get(key)
        if not hit:
            return None
        if hit[0] < time.monotonic():
            self._data.pop(key, None)
            return None
        return hit[1]

    def set(self, key: str, value, ttl: int):
        if ttl <= 0:
            return
        if len(self._data) >= self.max_items:
            for k in sorted(self._data, key=lambda k: self._data[k][0])[: self.max_items // 5 or 1]:
                self._data.pop(k, None)
        self._data[key] = (time.monotonic() + ttl, value)

    def clear(self):
        self._data.clear()


def cache_key(command: str, params: dict) -> str:
    return command + ':' + hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def chrome_installed() -> bool:
    if sys.platform == 'win32':
        roots = [os.environ.get(k) for k in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')]
        return any(r and Path(r, 'Google', 'Chrome', 'Application', 'chrome.exe').exists() for r in roots)
    if sys.platform == 'darwin':
        return Path('/Applications/Google Chrome.app').exists()
    return any(Path(p).exists() for p in ('/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/opt/google/chrome/chrome'))


class Alibaba1688Provider:
    def __init__(self, settings: Alibaba1688Settings | None = None, transport=None):
        self.settings = settings or Alibaba1688Settings()
        if transport is None:
            transport = RemoteAdapterTransport(self.settings) if self.settings.transport == 'remote' else LocalCliTransport(self.settings)
        self.transport = transport
        self.cache = TTLCache()
        # 最近在搜索结果中见过的商品，用于“加入候选库”时以 CLI 真实数据入库（而非信任前端提交）
        self.seen_offers = TTLCache(max_items=2000)
        self.last_query: dict | None = None

    # ---- 内部 ----
    async def _run(self, command: str, params: dict, timeout: int, ttl: int = 0, **extra) -> dict:
        key = cache_key(command, params)
        if ttl:
            cached = self.cache.get(key)
            if cached is not None:
                return {**cached, '_cached': True}
        try:
            result = await self.transport.run(command, params, timeout, **extra)
        except Alibaba1688Error as e:
            if command not in ('doctor', 'whoami', 'daemon_status', 'version'):
                self.last_query = {'command': command, 'state': e.state, 'label': STATES[e.state],
                                   'at': datetime.now(timezone.utc).isoformat()}
            raise
        if command not in ('doctor', 'whoami', 'daemon_status', 'version'):
            self.last_query = {'command': command, 'state': 'ok', 'label': STATES['ok'],
                               'at': datetime.now(timezone.utc).isoformat(), 'duration_ms': result.duration_ms}
        # 记录 CLI 实际获取时间；缓存命中时沿用，避免把“读取缓存的时间”当作采集时间
        data = {**result.data, '_fetched_at': datetime.now(timezone.utc).isoformat()}
        if ttl:
            self.cache.set(key, data, ttl)
        return data

    def _remember(self, items: list[dict]):
        for item in items:
            self.seen_offers.set(item['offer_id'], item, 7200)

    # ---- 状态 ----
    async def status(self, refresh: bool = False) -> dict:
        if not refresh:
            cached = self.cache.get('status')
            if cached:
                return {**cached, 'last_query': self.last_query}
        s = self.settings
        base = {'transport': s.transport, 'profile': s.profile, 'read_only': True,
                'capabilities': ['search', 'offer', 'image_search', 'supplier_search', 'supplier_inspect'],
                'disabled': ['login', 'logout', 'cart', 'checkout', 'seller_message'],
                'limits': {'max_results': s.max_results, 'concurrency': s.max_concurrency,
                           'search_cache_seconds': s.search_cache_ttl, 'image_max_bytes': s.image_max_bytes},
                'checked_at': datetime.now(timezone.utc).isoformat()}
        if s.transport == 'local':
            base['cli_command'] = resolve_cli(s)[-1] if resolve_cli(s) else None
        if not self.transport.available():
            state = 'cli_not_installed' if s.transport == 'local' else 'adapter_error'
            result = {**base, 'state': state, 'label': STATES[state], 'installed': False, 'version': None,
                      'browser_ok': None, 'logged_in': None, 'checks': [], 'daemon': None,
                      'hint': Alibaba1688Error(state).to_dict()['hint']}
            return {**result, 'last_query': self.last_query}
        try:
            version = (await self._run('version', {}, s.status_timeout)).get('version')
            doctor, whoami, daemon = await self._doctor(), await self._whoami(), await self._daemon()
        except Alibaba1688Error as e:
            result = {**base, 'state': e.state, 'label': STATES[e.state], 'installed': e.state != 'cli_not_installed',
                      'version': None, 'browser_ok': None, 'logged_in': None, 'checks': [], 'daemon': None,
                      'hint': e.to_dict()['hint']}
            return {**result, 'last_query': self.last_query}
        checks = [{'name': c.get('name'), 'status': c.get('status'), 'fix': c.get('fix') if c.get('status') != 'ok' else None}
                  for c in doctor.get('checks') or [] if isinstance(c, dict)]
        stats = (daemon or {}).get('stats') or {}
        browser = stats.get('browser') or {}
        health = stats.get('health') or {}
        chromium_ok = all(c['status'] != 'fail' for c in checks if 'chrom' in str(c['name']).lower())
        browser_ok = browser.get('browserAlive') if daemon and daemon.get('running') else (chromium_ok or chrome_installed())
        logged_in = bool(whoami.get('loggedIn'))
        failure = str(health.get('lastFailureKind') or '').lower()
        if not browser_ok:
            state = 'browser_error'
        elif not logged_in:
            state = 'not_logged_in'
        elif failure == 'not_logged_in' or browser.get('loggedIn') is False:
            state = 'login_expired'
        elif 'risk' in failure or 'slider' in failure:
            state = 'risk_control'
        else:
            state = 'logged_in'
        label = '登录有效' if state == 'logged_in' else STATES[state]
        result = {**base, 'state': state, 'label': label, 'installed': True, 'version': version,
                  'browser_ok': bool(browser_ok), 'system_chrome': chrome_installed(), 'logged_in': logged_in,
                  # 只返回最近验证时间；不返回 memberId / 昵称等账号标识
                  'last_verified_at': whoami.get('lastVerifiedAt') if logged_in else None,
                  'checks': checks,
                  'daemon': {'running': bool(daemon and daemon.get('running')), 'version_matches': (daemon or {}).get('versionMatches'),
                             'paused_until': health.get('pausedUntil'), 'last_failure_kind': health.get('lastFailureKind'),
                             'command_count': stats.get('commandCount')} if daemon else None,
                  'hint': Alibaba1688Error(state).to_dict()['hint'] if state != 'logged_in' else None}
        self.cache.set('status', result, s.status_cache_ttl)
        return {**result, 'last_query': self.last_query}

    async def _doctor(self) -> dict:
        try:
            return await self._run('doctor', {}, self.settings.status_timeout)
        except Alibaba1688Error as e:
            if e.state in ('cli_not_installed', 'timeout', 'adapter_error'):
                raise
            return {}

    async def _whoami(self) -> dict:
        try:
            return await self._run('whoami', {}, self.settings.status_timeout)
        except Alibaba1688Error as e:
            if e.state in ('not_logged_in', 'login_expired'):
                return {'loggedIn': False}
            raise

    async def _daemon(self) -> dict | None:
        try:
            return await self._run('daemon_status', {}, self.settings.status_timeout)
        except Alibaba1688Error as e:
            if e.state in ('cli_not_installed', 'adapter_error'):
                raise
            return None

    # ---- 查询 ----
    async def search(self, keyword: str, max_results: int = 20, sort: str = 'relevance', price_min=None,
                     price_max=None, exclude_ads: bool = False, factory_only: bool = False) -> dict:
        keyword = clean_keyword(keyword)
        params = {'keyword': keyword, 'max': max_results, 'sort': sort, 'price_min': price_min, 'price_max': price_max,
                  'exclude_ads': exclude_ads, 'verified': 'factory' if factory_only else 'any'}
        data = await self._run('search', params, self.settings.search_timeout, self.settings.search_cache_ttl)
        result = normalize.search_result(data, keyword=keyword)
        result['items'] = result['items'][:max_results]  # 不依赖 CLI 是否遵守 --max
        result['total'] = len(result['items'])
        result['cached'] = bool(data.get('_cached'))
        self._remember(result['items'])
        return result

    async def offer(self, offer_id: str, refresh: bool = False) -> dict:
        offer_id = check_offer_id(offer_id)
        if refresh:
            self.cache._data.pop(cache_key('offer', {'offer_id': offer_id}), None)
        data = await self._run('offer', {'offer_id': offer_id}, self.settings.detail_timeout, self.settings.detail_cache_ttl)
        result = normalize.offer_detail(data)
        if result['offer_id'] != offer_id:
            raise Alibaba1688Error('contract_changed', 'CLI 返回的商品 ID 与请求不一致')
        result['cached'] = bool(data.get('_cached'))
        return result

    async def image_search(self, content: bytes, max_results: int = 20) -> dict:
        if not content:
            raise Alibaba1688Error('bad_input', '图片为空')
        if len(content) > self.settings.image_max_bytes:
            raise Alibaba1688Error('bad_input', f'图片不能超过 {self.settings.image_max_bytes // 1024 // 1024} MB')
        kind = sniff_image(content)
        if not kind:
            raise Alibaba1688Error('bad_input', '仅支持 JPG、PNG、WebP 图片')
        digest = hashlib.sha256(content).hexdigest()
        params = {'max': max_results, 'image_sha256': digest}
        key = cache_key('image_search', params)
        data = self.cache.get(key)
        if data is None:
            if isinstance(self.transport, RemoteAdapterTransport):
                data = await self._run('image_search', {'max': max_results}, self.settings.search_timeout,
                                       file=content, filename=f'upload.{kind}')
            else:
                data = await self.run_image_file(content, kind, max_results)
            self.cache.set(key, data, self.settings.search_cache_ttl)
        result = normalize.search_result(data, keyword=None)
        # 结果数量在本系统侧强制截断；2026-10-13 联调实测 1688 图搜结果可能与图片无关，需提示人工确认
        result['items'] = result['items'][:max_results]
        result['total'] = len(result['items'])
        result['keyword'] = None
        result['image_sha256'] = digest[:16]
        result['notice'] += '；以图搜图结果由 1688 返回，系统未校验与图片的相关性，请人工确认是否为同款或相似商品'
        self._remember(result['items'])
        return result

    async def run_image_file(self, content: bytes, kind: str, max_results: int) -> dict:
        """写入仅当前用户可访问的临时目录，调用 CLI 后立即删除。"""
        folder = tempfile.mkdtemp(prefix='bb1688-img-')
        path = Path(folder) / f'query.{kind}'
        try:
            path.write_bytes(content)
            return await self._run('image_search', {'max': max_results, 'path': str(path)}, self.settings.search_timeout)
        finally:
            try:
                path.unlink(missing_ok=True)
                os.rmdir(folder)
            except OSError:
                pass

    async def supplier_search(self, keyword: str, max_results: int = 20, factory_only: bool = False,
                              province: str | None = None) -> dict:
        keyword = clean_keyword(keyword)
        params = {'keyword': keyword, 'max': max_results, 'factory_only': factory_only, 'province': province or None}
        data = await self._run('supplier_search', params, self.settings.search_timeout, self.settings.search_cache_ttl)
        result = normalize.supplier_search_result(data, keyword)
        result['cached'] = bool(data.get('_cached'))
        return result

    async def supplier_inspect(self, target: str) -> dict:
        target = check_supplier_target(target)
        data = await self._run('supplier_inspect', {'target': target}, self.settings.detail_timeout, self.settings.detail_cache_ttl)
        result = normalize.supplier_inspect(data)
        result['cached'] = bool(data.get('_cached'))
        return result


_provider: Alibaba1688Provider | None = None


def get_provider() -> Alibaba1688Provider:
    """进程内单例：共享缓存、并发闸门和调用间隔。"""
    global _provider
    if _provider is None:
        _provider = Alibaba1688Provider()
    return _provider
