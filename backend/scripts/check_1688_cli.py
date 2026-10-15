"""只读检查 1688 CLI 状态：安装路径、版本、浏览器、登录（不搜索、不登录、不读取 Cookie）。

在 backend 目录运行（应与后端进程使用同一操作系统用户）：
    ../.venv/Scripts/python.exe -m scripts.check_1688_cli
"""
import asyncio
import json
import sys

from app.services.alibaba1688.provider import Alibaba1688Provider


async def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    status = await Alibaba1688Provider().status(refresh=True)
    print(json.dumps(status, ensure_ascii=False, indent=2, default=str))
    return 0 if status['state'] == 'logged_in' else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
