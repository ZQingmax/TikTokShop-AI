"""宿主机 1688 CLI Adapter：后端在 Docker/WSL 中、而 1688 登录会话在宿主机时使用。

    # 宿主机（已执行过 1688 login 的同一用户）在 backend 目录运行：
    ALIBABA1688_ADAPTER_TOKEN=<随机长令牌> python -m app.services.alibaba1688.adapter_server

- 只暴露白名单只读命令；浏览器 Profile、Cookie 始终留在宿主机，不经接口返回。
- 必须配置令牌，否则拒绝启动；默认只监听 127.0.0.1。容器访问时可设 ALIBABA1688_ADAPTER_BIND
  为 Docker 网关地址（不要绑定公网网卡）。
- 后端设置 ALIBABA1688_TRANSPORT=remote、ALIBABA1688_ADAPTER_URL、ALIBABA1688_ADAPTER_TOKEN。
"""
import hmac
import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.alibaba1688.commands import READ_ONLY_COMMANDS
from app.services.alibaba1688.config import Alibaba1688Settings
from app.services.alibaba1688.errors import Alibaba1688Error
from app.services.alibaba1688.provider import Alibaba1688Provider, sniff_image
from app.services.alibaba1688.runner import LocalCliTransport

logger = logging.getLogger(__name__)


def create_adapter_app(settings: Alibaba1688Settings | None = None, transport=None) -> FastAPI:
    settings = settings or Alibaba1688Settings()
    token = settings.adapter_token.get_secret_value()
    if len(token) < 24:
        raise RuntimeError('ALIBABA1688_ADAPTER_TOKEN 未配置或少于 24 个字符，拒绝启动')
    local = settings.model_copy(update={'transport': 'local'})
    transport = transport or LocalCliTransport(local)
    provider = Alibaba1688Provider(local, transport)
    app = FastAPI(title='1688 CLI Adapter', docs_url=None, redoc_url=None, openapi_url=None)

    def error(e: Alibaba1688Error, status: int = 200):
        return JSONResponse({'ok': False, 'error': e.to_dict()}, status_code=status)

    @app.get('/health')
    async def health():
        return {'ok': True, 'cli_found': transport.available()}

    @app.post('/run')
    async def run(request: Request):
        auth = request.headers.get('authorization', '')
        if not hmac.compare_digest(auth.encode(), f'Bearer {token}'.encode()):
            return JSONResponse({'ok': False, 'error': {'state': 'adapter_error', 'message': '令牌无效'}}, status_code=401)
        content = None
        try:
            if request.headers.get('content-type', '').startswith('multipart/form-data'):
                form = await request.form()
                payload = json.loads(form.get('payload') or '{}')
                upload = form.get('image')
                content = await upload.read(settings.image_max_bytes + 1) if upload is not None else None
            else:
                payload = await request.json()
        except (ValueError, TypeError):
            return error(Alibaba1688Error('bad_input', '请求格式无效'), 400)
        command = payload.get('command') if isinstance(payload, dict) else None
        params = payload.get('params') if isinstance(payload, dict) and isinstance(payload.get('params'), dict) else {}
        if command not in READ_ONLY_COMMANDS:
            return error(Alibaba1688Error('bad_input', '不支持的 1688 命令'), 400)
        params.pop('path', None)  # 远程调用不允许指定宿主机文件路径
        try:
            if command == 'image_search':
                if not content or len(content) > settings.image_max_bytes:
                    raise Alibaba1688Error('bad_input', '图片为空或超过大小限制')
                kind = sniff_image(content)
                if not kind:
                    raise Alibaba1688Error('bad_input', '仅支持 JPG、PNG、WebP 图片')
                data = await provider.run_image_file(content, kind, int(params.get('max', 20)))
                return {'ok': True, 'data': data}
            timeout = settings.status_timeout if command in ('doctor', 'whoami', 'daemon_status', 'version') else settings.search_timeout
            result = await transport.run(command, params, timeout)
            return {'ok': True, 'data': result.data, 'duration_ms': result.duration_ms}
        except Alibaba1688Error as e:
            return error(e)

    return app


if __name__ == '__main__':
    import uvicorn

    s = Alibaba1688Settings()
    uvicorn.run(create_adapter_app(s), host=s.adapter_bind, port=s.adapter_port, log_level='info')
