"""1688 CLI 只读货源集成（Alibaba1688Provider）。"""
from app.services.alibaba1688.errors import Alibaba1688Error
from app.services.alibaba1688.provider import Alibaba1688Provider, get_provider

__all__ = ['Alibaba1688Error', 'Alibaba1688Provider', 'get_provider']
