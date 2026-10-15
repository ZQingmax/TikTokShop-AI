"""Bounded BrowserSkill subprocess transport and fail-closed product filtering."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from .config import FastmossSettings, MARKETS, UPSTREAM_REVISION, UPSTREAM_SHA256, ROOT


class BrowserError(Exception):
    pass


# BrowserSkill 失败时输出 {"code","message","hint","exit_code"}；按其文字归类成具体原因
FAILURES = [
    (r'daemon|named pipe|ipc', '本机 BrowserSkill 守护进程未运行，请执行 scripts/start-fastmoss-local.ps1'),
    (r'no (connected )?browser|browser.*(not connected|disconnected|unavailable)|extension', '浏览器扩展未连接或已断开，请在浏览器中打开 BrowserSkill 扩展并启用本地连接'),
    (r'session', 'BrowserSkill 会话已失效或被关闭，请重新抓取'),
    (r'timeout|timed out', '浏览器页面响应超时，请检查网络或 FastMoss 页面是否可正常打开'),
    (r'navigat|net::|ERR_', '无法打开 FastMoss 页面，请检查网络连接'),
]


def failure_reason(stdout, stderr):
    detail = ''
    for text in (stdout, stderr):
        for line in reversed((text or '').strip().splitlines()):
            try:
                value = json.loads(line) if line.strip().startswith('{') else None
            except ValueError:
                value = None
            if isinstance(value, dict) and value.get('message'):
                detail = str(value['message'])
                break
        if detail:
            break
    if not detail:
        try:
            value = json.loads(stdout or '{}')
            detail = str(value.get('message') or '') if isinstance(value, dict) else ''
        except ValueError:
            detail = ''
    for pattern, reason in FAILURES:
        if re.search(pattern, detail, re.I):
            return reason
    # 页面 URL 可能带查询参数或令牌：替换后再截断回显
    detail = re.sub(r'https?://\S+', '[链接]', detail)
    return 'BrowserSkill 执行失败' + (f'：{detail[:120]}' if detail else '，请检查扩展连接和 FastMoss 登录状态')


# 家居日用品快捷范围：按页面真实品类名匹配（中文显示名或英文名）；家具、家电、家装建材不默认纳入
HOUSEHOLD = re.compile(r'居家|日用|收纳|清洁|厨房|厨具|家纺|Home Supplies|Kitchen|Textiles|Storage|Cleaning', re.I)
NOT_HOUSEHOLD = re.compile(r'家具|家电|家装|建材|Furniture|Appliance|Home Improvement', re.I)
CATALOG_SOURCE = 'FastMoss 新品榜页面筛选项'


def english_names(payload):
    """分类接口（market-category）只返回英文名；仅作为辅助显示，标识以榜单页面为准。"""
    names = {}
    for item in (payload or {}).get('category') or []:
        if isinstance(item, dict) and item.get('c_code') is not None and isinstance(item.get('c_name'), str):
            names[str(item['c_code'])] = item['c_name'].strip()
    return names


def categories_from_page(options, english=None):
    """榜单页面的品类单选项即该榜单可用的真实分类（value = 分类标识，文本 = 显示名）。当前只有一级品类。"""
    english = english or {}
    result, seen = [], set()
    for option in options or []:
        if not isinstance(option, dict):
            raise BrowserError('FastMoss 分类记录格式不兼容')
        ident, name = str(option.get('value') or '').strip(), str(option.get('label') or '').strip()
        if not re.fullmatch(r'\d{1,12}', ident) or not name or len(name) > 100:
            raise BrowserError('FastMoss 分类缺少真实标识或名称')
        if ident in seen:
            raise BrowserError('FastMoss 分类标识重复，页面结构可能已变化')
        seen.add(ident)
        name_en = english.get(ident)
        labels = [name, name_en or '']
        household = any(HOUSEHOLD.search(x) for x in labels) and not any(NOT_HOUSEHOLD.search(x) for x in labels)
        result.append(dict(id=ident, name=name, name_en=name_en, parent_id=None, path=[name], level=1,
                           household=household, source=CATALOG_SOURCE))
    if not result:
        raise BrowserError('未获得可用分类，请检查 FastMoss 登录和账号权限')
    return result


def upstream(settings):
    directory = Path(settings.upstream_dir)
    try:
        manifest = json.loads((directory / 'manifest.json').read_text('utf-8-sig'))
        script = directory / 'sections.py'
        if manifest['revision'] != UPSTREAM_REVISION or hashlib.sha256(script.read_bytes()).hexdigest() != UPSTREAM_SHA256:
            raise ValueError()
        spec = importlib.util.spec_from_file_location('fastmoss_pinned_sections', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except (OSError, KeyError, ValueError) as exc:
        raise BrowserError('FastMoss 固定版本依赖未安装或已变化，请运行安装脚本') from exc


class Browser:
    def __init__(self, settings=None):
        self.settings = settings or FastmossSettings()
        local_binary = ROOT / '.runtime' / 'browserskill' / 'bsk.exe'
        self.binary = self.settings.bsk_bin or shutil.which('bsk') or (str(local_binary) if local_binary.is_file() else '')
        self.session = None
        self.deadline = None
        self.last_miss = ''

    def run(self, *args, timeout=45):
        if not self.binary or not Path(self.binary).is_file():
            raise BrowserError('未安装 BrowserSkill：请安装 bsk 并配置 FASTMOSS_BSK_BIN')
        if Path(self.binary).suffix.lower() in ('.cmd', '.bat', '.ps1'):
            raise BrowserError('请配置 BrowserSkill 可执行文件 bsk.exe 的路径')
        if self.deadline:
            timeout = min(timeout, self.deadline - time.monotonic())
            if timeout <= 0:
                raise BrowserError('当前品类抓取超过 10 分钟，请重新抓取')
        env = {k: v for k, v in os.environ.items() if not re.search(r'KEY|SECRET|TOKEN|PASSWORD|PASSWD|DATABASE_URL|DSN|CREDENTIAL', k, re.I)}
        env['BSK_AUTO_START'] = '0'
        try:
            proc = subprocess.run([self.binary, *args], capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', timeout=timeout, shell=False, env=env,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            raise BrowserError('BrowserSkill 操作超时，请检查浏览器连接') from exc
        except OSError as exc:
            raise BrowserError('无法启动 BrowserSkill') from exc
        if proc.returncode:
            raise BrowserError(failure_reason(proc.stdout, proc.stderr))
        return proc.stdout.strip()

    def status(self):
        try:
            upstream(self.settings)
            value = json.loads(self.run('status', '--json', timeout=15))
            connected = bool(value.get('browsers'))
            return {'ready': connected, 'message': '浏览器已连接；请刷新分类验证登录和权限' if connected else '未检测到连接的浏览器，请启用 BrowserSkill 扩展'}
        except (BrowserError, ValueError, AttributeError) as exc:
            return {'ready': False, 'message': str(exc)}

    def __enter__(self):
        try:
            value = json.loads(self.run('session', 'start', '--json', timeout=60))
            self.session = value['session_id']
            if not isinstance(self.session, str) or not re.fullmatch(r'[\w-]{1,100}', self.session):
                raise ValueError()
        except (ValueError, KeyError, TypeError) as exc:
            raise BrowserError('BrowserSkill 会话响应不兼容') from exc
        return self

    def __exit__(self, *args):
        self.deadline = None
        if self.session:
            try:
                self.run('session', 'stop', self.session, timeout=15)
            except BrowserError:
                pass

    def navigate(self, url):
        self.run('navigate', url, '--session', self.session, '--wait-until', 'load', '--timeout', '30s')
        time.sleep(2)

    def evaluate(self, script):
        expression = '(async () => JSON.stringify(await (' + script + ')))()'
        value = self.run('evaluate', expression, '--session', self.session, '--timeout', '30s')
        try:
            result = json.loads(value)
            if isinstance(result, str):
                result = json.loads(result)
            if not isinstance(result, dict):
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise BrowserError('BrowserSkill 页面响应不兼容') from exc
        if result.get('error'):
            raise BrowserError(str(result['error'])[:300])
        return result

    def page(self, operation, **args):
        script = Path(__file__).with_name('page.js').read_text('utf-8')
        return self.evaluate('(async () => {const operation=' + json.dumps(operation) + ';const args=' +
                             json.dumps(args, ensure_ascii=False) + ';' + script + '})()')

    def try_page(self, operation, **args):
        """页面元素异步渲染：找不到时返回 None 由调用方重试；其他错误（未登录等）直接抛出。"""
        try:
            return self.page(operation, **args)
        except BrowserError as exc:
            if '找不到' in str(exc) or '没有国家或品类' in str(exc):
                self.last_miss = str(exc)
                return None
            raise

    def open_ranking(self):
        module = upstream(self.settings)
        self.navigate(module.SECTIONS['products']['url'])
        return module

    def catalog(self, market):
        """从新品榜页面读取真实品类（标识 + 中文名）；英文名来自分类接口，失败不影响。"""
        self.open_ranking()
        options = self.wait_for(lambda: self.try_page('catalog'))
        if not options:
            raise BrowserError(getattr(self, 'last_miss', '榜单页面没有分类筛选项'))
        if not any(c.get('value') == market for c in options.get('countries', [])):
            raise BrowserError(f'榜单页面不提供{MARKETS[market]}，请检查账号权限')
        try:
            payload = self.evaluate('''(async () => {
                const r = await fetch('/api/analysis/GoodCategory/filterInfo?region=' + %s, {credentials:'include'});
                if (!r.ok) return {};
                const body = await r.json();
                return body.code === 200 ? body.data : {};
            })()''' % json.dumps(market))
        except BrowserError:
            payload = {}
        return categories_from_page(options.get('categories'), english_names(payload))

    def wait_for(self, check, attempts=15):
        result = None
        for _ in range(attempts):
            result = check()
            if result:
                return result
            time.sleep(1)
        return result

    def verify(self, market, category, page_number):
        """国家与品类必须同时在页面生效：单选已选中，且页面数据请求带 region / l1_cid / page。"""
        args = dict(country=market, country_label=MARKETS[market], category_id=category['id'],
                    category_label=category['name'], page=page_number)
        observed = {}

        def check():
            observed.update(self.page('verify', **args))
            return observed if observed.get('country') and observed.get('category') and observed.get('page') else None

        if not self.wait_for(check):
            request = observed.get('request') or {}
            parts = [f"国家{'已' if observed.get('country') else '未'}生效（请求地区 {request.get('region') or '无'}）",
                     f"品类{'已' if observed.get('category') else '未'}生效（请求品类 {request.get('l1_cid') or '无'}）",
                     f"页码{'一致' if observed.get('page') else '不一致'}（第 {page_number} 页，请求第 {request.get('page') or '?'} 页）"]
            raise BrowserError('无法确认国家与品类同时生效，已停止抓取，未导入综合榜：' + '；'.join(parts))
        return observed['request']

    def scrape(self, market, category, pages):
        self.deadline = time.monotonic() + min(self.settings.category_timeout, 600)
        module = self.open_ranking()
        # 先国家后品类：与页面数据请求参数一一对应，可逐步验证
        for value, label in ((market, MARKETS[market]), (category['id'], category['name'])):
            if not self.wait_for(lambda: self.try_page('select', value=value, label=label)):
                raise BrowserError(getattr(self, 'last_miss', f'页面找不到筛选项：{label}'))
            time.sleep(2)
        results, prior = [], None
        for page_number in range(1, pages + 1):
            request = self.verify(market, category, page_number)
            snapshot, empty_seen = None, 0
            for _ in range(15):
                snapshot = self.page('extract')
                urls = [r['product_url'] or r['cells'][1] for r in snapshot.get('rows') or []]
                if not snapshot.get('loading') and urls and urls != prior:
                    break
                # 连续多次看到“暂无数据”占位（非加载中）才认定为真实空榜单
                empty_seen = empty_seen + 1 if snapshot.get('empty') else 0
                if empty_seen >= 3:
                    if page_number == 1:
                        raise BrowserError(f'来源榜单在{MARKETS[market]}「{category["name"]}」下暂无商品（页面显示无数据）')
                    break
                time.sleep(1)
            else:
                raise BrowserError('商品列表为空或翻页内容未更新，请检查权限与页面结构')
            if snapshot.get('empty'):
                break  # 后续页无数据：保留已抓取的页
            prior = urls
            page_size = snapshot.get('page_size') or len(snapshot['rows'])
            for item in snapshot['rows']:
                row = module.products_parse_row(item['cells'])
                if not row:
                    raise BrowserError('商品列结构已变化，请更新适配器')
                if row.get('country') not in (MARKETS[market], market):
                    raise BrowserError('商品国家与筛选条件不一致，已停止导入')
                if item.get('rank_icon') and not row.get('rank'):
                    # 前三名为奖牌图标：按页面顺序得到原始排名，并在原始数据中注明来源
                    row['rank'] = str((page_number - 1) * page_size + item['position'])
                    row['rank_source'] = 'icon_position'
                row.update(product_url=item['product_url'], image_url=item['image_url'], shop_url=item.get('shop_url') or '',
                           source_url=snapshot['source_url'], period=snapshot.get('period') or '',
                           observed_on=snapshot.get('stat_end') or '', stat_start=snapshot.get('stat_start') or '',
                           stat_end=snapshot.get('stat_end') or '', category_id=category['id'],
                           category_path=' / '.join(category['path']), page=str(page_number),
                           filter_region=request.get('region') or '', filter_l1_cid=request.get('l1_cid') or '')
                results.append(row)
            if len(results) >= 500 or page_number == pages or not self.page('next').get('clicked'):
                break
            time.sleep(2)
        return results[:500]


def load_catalog(market, settings=None):
    with Browser(settings) as browser:
        return browser.catalog(market)
