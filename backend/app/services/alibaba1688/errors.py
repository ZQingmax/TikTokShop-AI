"""CLI 退出码 / 错误码 → 系统状态。参考 1688-cli docs/SAFETY.md 的退出码约定。"""

# 系统对外暴露的状态值（前端与 Agent 依赖这些值）
STATES = {
    'cli_not_installed': '未检测到 1688 CLI',
    'browser_error': '浏览器环境异常',
    'not_logged_in': '1688 未登录',
    'login_expired': '1688 登录已过期',
    'risk_control': '1688 触发风控/滑块验证',
    'busy': '1688 CLI 正忙（同一 Profile 同时只能执行一个命令）',
    'timeout': '1688 查询超时',
    'network_error': '网络错误',
    'bad_input': '参数无效',
    'not_found': '商品或供应商不存在',
    'contract_changed': 'CLI 输出结构与预期不一致（可能 CLI 版本已变化）',
    'adapter_error': 'CLI Adapter 不可用',
    'cli_error': '1688 CLI 执行失败',
    'ok': '查询成功',
}

HINTS = {
    'cli_not_installed': '在运行后端的同一环境执行：npm install -g 1688-cli，然后执行 1688 doctor',
    'browser_error': '执行 1688 doctor 检查；需安装 Google Chrome，或执行 npx playwright install chromium',
    'not_logged_in': '请在运行后端的同一台机器、同一用户下手动执行：1688 login，并用 1688 App 扫码登录',
    'login_expired': '登录已失效，请手动执行：1688 login 重新扫码登录',
    'risk_control': '请在终端手动执行一次同样的命令并加 --headed，例如：1688 search "关键词" --headed，由本人完成滑块验证；系统不会自动绕过验证码',
    'busy': '请稍后再试；不要并发发起多个 1688 查询',
    'timeout': '可稍后重试；若持续超时请执行 1688 daemon status 和 1688 doctor 检查浏览器',
    'network_error': '检查本机网络后重试',
    'contract_changed': '请执行 1688 --version 核对版本，并更新后端标准化映射；原始输出已在服务端日志中记录错误码',
    'adapter_error': '检查宿主机上的 1688 CLI Adapter 是否启动，以及 ALIBABA1688_ADAPTER_URL / TOKEN 配置',
}

# HTTP 状态：避免使用 401（前端会把 401 当作本系统登录失效并退出）
HTTP_STATUS = {
    'bad_input': 422, 'not_found': 404, 'busy': 429, 'timeout': 504,
    'cli_not_installed': 503, 'browser_error': 503, 'adapter_error': 503,
    'not_logged_in': 424, 'login_expired': 424, 'risk_control': 424,
    'network_error': 502, 'contract_changed': 502, 'cli_error': 502,
}

EXIT_STATES = {2: 'bad_input', 3: 'not_logged_in', 4: 'risk_control', 5: 'busy', 6: 'browser_error',
               7: 'timeout', 8: 'not_logged_in', 9: 'network_error'}


class Alibaba1688Error(Exception):
    def __init__(self, state: str, message: str | None = None, code: str | None = None,
                 exit_code: int | None = None, retryable: bool = False):
        self.state = state if state in STATES else 'cli_error'
        self.message = message or STATES[self.state]
        self.code = code or self.state.upper()
        self.exit_code = exit_code
        self.retryable = retryable
        super().__init__(self.message)

    @property
    def http_status(self) -> int:
        return HTTP_STATUS.get(self.state, 502)

    def to_dict(self) -> dict:
        return {'state': self.state, 'code': self.code, 'message': self.message,
                'label': STATES[self.state], 'hint': HINTS.get(self.state), 'retryable': self.retryable,
                'exit_code': self.exit_code}


def classify(exit_code: int, code: str | None, message: str | None, details: dict | None = None) -> Alibaba1688Error:
    """只读取 code / failureKind / category / pausedUntil；details 中的 currentUrl、artifactDir 可能含登录令牌或本机路径，
    一律不透传、不记录。"""
    code = (code or '').upper()
    details = details if isinstance(details, dict) else {}
    kind = str(details.get('failureKind') or details.get('pageState') or '').lower()
    category = str(details.get('category') or '').lower()
    # 只依据错误码和 failureKind 判断，不依据 message：CLI 在从未登录时也提示 "Session expired"
    text = f'{code} {kind.upper()}'
    if 'EXPIRED' in code and ('SESSION' in code or 'LOGIN' in code):
        state = 'login_expired'
    elif 'NOT_LOGGED_IN' in text or category == 'auth' or exit_code in (3, 8):
        state = 'not_logged_in'
    elif 'RISK' in text or 'SLIDER' in text or 'CAPTCHA' in text or 'PUNISH' in text:
        state = 'risk_control'
    elif 'NOT_FOUND' in code or 'OFFER_UNAVAILABLE' in code or 'INVALID_OFFER' in code:
        state = 'not_found'
    elif 'TIMEOUT' in code:
        state = 'timeout'
    elif 'LOCK' in code:
        state = 'busy'
    elif 'CHROM' in code or 'BROWSER' in code:
        state = 'browser_error'
    else:
        state = EXIT_STATES.get(exit_code, 'cli_error')
    readable = STATES[state]
    if state == 'bad_input' and message:
        readable = f'{readable}：{message[:200]}'
    if code == 'DAEMON_PAUSED':
        readable += f'（CLI 守护进程在连续失败后已暂停，至 {str(details.get("pausedUntil") or "")[:30]}；处理后可执行 1688 daemon reload）'
    return Alibaba1688Error(state, readable, code or None, exit_code,
                            retryable=state in ('busy', 'timeout', 'network_error'))
