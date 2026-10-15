"""1688 CLI 执行层：解析路径、白名单参数、超时、串行化、严格 JSON 解析。

- 绝不使用 shell=True；Windows 下不直接执行 1688.cmd（cmd.exe 会二次解析参数），而是 node + dist/cli.js。
- stdout / stderr / 退出码分开处理；stdout 只接受单个 JSON 文档。
- 日志只记录命令名、退出码、耗时、错误码；不记录 stdout、stderr 原文、环境变量和 CLI 返回的 URL。
"""
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.services.alibaba1688.commands import READ_ONLY_COMMANDS, build
from app.services.alibaba1688.config import Alibaba1688Settings
from app.services.alibaba1688.errors import Alibaba1688Error, classify

logger = logging.getLogger(__name__)

# 不把后端自身的密钥透传给第三方 CLI 进程
SECRET_ENV = re.compile(r'(KEY|SECRET|TOKEN|PASSWORD|PASSWD|DATABASE_URL|DSN|CREDENTIAL)', re.I)


@dataclass
class CliResult:
    data: dict
    duration_ms: int


def resolve_cli(settings: Alibaba1688Settings) -> list[str] | None:
    """返回启动 CLI 的 argv 前缀；找不到时返回 None。"""
    candidates = [settings.cli_path] if settings.cli_path else []
    if not candidates:
        for name in ('1688.cmd', '1688') if sys.platform == 'win32' else ('1688',):
            found = shutil.which(name)
            if found:
                candidates.append(found)
        if sys.platform == 'win32' and os.environ.get('APPDATA'):
            candidates.append(str(Path(os.environ['APPDATA']) / 'npm' / '1688.cmd'))
    for raw in candidates:
        path = Path(raw)
        if not path.exists():
            continue
        if path.suffix.lower() == '.js':
            script = path
        elif sys.platform == 'win32' and path.suffix.lower() in ('.cmd', '.ps1', ''):
            # npm 全局 shim：<prefix>/1688.cmd → <prefix>/node_modules/1688-cli/dist/cli.js
            script = path.parent / 'node_modules' / '1688-cli' / 'dist' / 'cli.js'
            if not script.exists():
                continue
        else:
            return [str(path)]
        node = settings.node_path or shutil.which('node') or shutil.which('node.exe')
        if not node:
            return None
        return [node, str(script)]
    return None


def child_env(settings: Alibaba1688Settings) -> dict:
    env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
    env.update(NO_COLOR='1', FORCE_COLOR='0')
    if settings.cli_home:
        env['BB1688_HOME'] = settings.cli_home
    return env


def parse_json_document(text: str) -> dict:
    text = (text or '').strip()
    if not text:
        raise ValueError('empty')
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('not an object')
    return value


def parse_error(stderr: str) -> tuple[str | None, str | None, dict]:
    """CLI 失败时在 stderr 输出 {"ok":false,"code","message","details"}；可能夹杂更新提示行。"""
    for line in reversed((stderr or '').strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and value.get('ok') is False:
                return value.get('code'), value.get('message'), value.get('details') or {}
    return None, None, {}


class LocalCliTransport:
    """后端与 CLI 位于同一环境（同一操作系统用户）时使用。"""

    def __init__(self, settings: Alibaba1688Settings):
        self.settings = settings
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)
        self._last_call = 0.0

    def available(self) -> bool:
        return resolve_cli(self.settings) is not None

    def _execute(self, argv: list[str], timeout: int) -> tuple[int, str, str]:
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=child_env(self.settings), shell=False, creationflags=flags)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        return proc.returncode, out.decode('utf-8', 'replace'), err.decode('utf-8', 'replace')

    async def run(self, command: str, params: dict, timeout: int) -> CliResult:
        if command not in READ_ONLY_COMMANDS:
            raise Alibaba1688Error('bad_input', '不支持的 1688 命令')
        prefix = resolve_cli(self.settings)
        if not prefix:
            raise Alibaba1688Error('cli_not_installed')
        options, positional = build(command, params, self.settings.max_results)
        if command != 'version':
            options += ['--profile', self.settings.profile]
        argv = prefix + options + (['--', *positional] if positional else [])
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.settings.queue_wait)
        except asyncio.TimeoutError:
            raise Alibaba1688Error('busy', '已有 1688 查询正在执行，请稍后再试', retryable=True) from None
        started = time.monotonic()
        try:
            wait = self.settings.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                code, out, err = await asyncio.to_thread(self._execute, argv, timeout)
            except subprocess.TimeoutExpired:
                logger.warning('1688 cli %s timeout after %ss', command, timeout)
                raise Alibaba1688Error('timeout', f'1688 查询超过 {timeout} 秒未响应', retryable=True) from None
            except OSError:
                raise Alibaba1688Error('cli_not_installed', '无法启动 1688 CLI 进程') from None
            finally:
                self._last_call = time.monotonic()
        finally:
            self._semaphore.release()
        duration = int((time.monotonic() - started) * 1000)
        if code != 0 and command == 'doctor':
            # doctor 有 fail 项时退出码非 0，但 stdout 仍是完整诊断结果
            try:
                data = parse_json_document(out)
                if isinstance(data.get('checks'), list):
                    return CliResult(data, duration)
            except ValueError:
                pass
        if code != 0:
            err_code, message, details = parse_error(err)
            error = classify(code, err_code, message, details)
            logger.warning('1688 cli %s failed exit=%s code=%s state=%s %sms', command, code, err_code, error.state, duration)
            raise error
        if command == 'version':
            return CliResult({'version': out.strip()[:40]}, duration)
        try:
            data = parse_json_document(out)
        except ValueError:
            logger.error('1688 cli %s returned non-JSON stdout (%s bytes) %sms', command, len(out), duration)
            raise Alibaba1688Error('contract_changed', 'CLI 输出不是有效 JSON') from None
        logger.info('1688 cli %s ok %sms', command, duration)
        return CliResult(data, duration)


class RemoteAdapterTransport:
    """后端运行在容器内、CLI 和登录会话在宿主机时使用。浏览器 Profile / Cookie 从不离开宿主机。"""

    def __init__(self, settings: Alibaba1688Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client

    def available(self) -> bool:
        return bool(self.settings.adapter_token.get_secret_value())

    async def run(self, command: str, params: dict, timeout: int, file: bytes | None = None,
                  filename: str | None = None) -> CliResult:
        if command not in READ_ONLY_COMMANDS:
            raise Alibaba1688Error('bad_input', '不支持的 1688 命令')
        token = self.settings.adapter_token.get_secret_value()
        if not token:
            raise Alibaba1688Error('adapter_error', '未配置 ALIBABA1688_ADAPTER_TOKEN')
        build(command, {**params, 'path': 'upload'} if command == 'image_search' else params, self.settings.max_results)
        headers = {'Authorization': f'Bearer {token}'}
        url = self.settings.adapter_url.rstrip('/') + '/run'
        payload = {'command': command, 'params': {k: v for k, v in params.items() if k != 'path'}}
        client = self.client or httpx.AsyncClient()
        try:
            if file is not None:
                response = await client.post(url, headers=headers, timeout=timeout + 10,
                                             data={'payload': json.dumps(payload, ensure_ascii=False)},
                                             files={'image': (filename or 'image', file)})
            else:
                response = await client.post(url, headers=headers, json=payload, timeout=timeout + 10)
        except httpx.TimeoutException:
            raise Alibaba1688Error('timeout', retryable=True) from None
        except httpx.HTTPError:
            raise Alibaba1688Error('adapter_error') from None
        finally:
            if self.client is None:
                await client.aclose()
        try:
            body = response.json()
        except ValueError:
            raise Alibaba1688Error('adapter_error', 'Adapter 返回了非 JSON 响应') from None
        if response.status_code == 401:
            raise Alibaba1688Error('adapter_error', 'Adapter 令牌无效')
        if response.status_code != 200 or not body.get('ok'):
            e = body.get('error') or {}
            raise Alibaba1688Error(e.get('state', 'cli_error'), e.get('message'), e.get('code'), e.get('exit_code'),
                                   bool(e.get('retryable')))
        return CliResult(body.get('data') or {}, int(body.get('duration_ms') or 0))
