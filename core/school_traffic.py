"""Local request ceilings shared by campus transports and application processes."""

from datetime import timezone
from email.utils import parsedate_to_datetime
import math
import sqlite3
import time
from urllib.parse import urlsplit

import httpx

from core import operations
from core.domain import trusted_url
from core.webvpn import from_webvpn_url


# These are application ceilings, not estimates of the school's limits.
ACCOUNT_LIMITS = ((60, 24), (3600, 120), (86400, 600))
INSTALLATION_LIMITS = ((60, 60), (3600, 360), (86400, 1800))
ACTION_LIMITS = {"sms": ((90, 1), (3600, 3), (86400, 5)),
                 "login": ((600, 4), (3600, 10))}
INSTALLATION_SMS_LIMITS = ((60, 3), (3600, 12), (86400, 30))

_account_count_provider = lambda: 1


def set_account_count_provider(provider):
    global _account_count_provider
    _account_count_provider = provider if callable(provider) else (lambda: 1)


def installation_limits():
    active_keys = None
    count = 1
    try:
        provided = _account_count_provider()
        if isinstance(provided, (list, tuple, set, frozenset)):
            active_keys = {owner_key(u) for u in provided if isinstance(u, str) and u.strip()}
            count = max(1, len(active_keys))
        else:
            count = max(1, int(provided))
    except Exception:
        count = 1
    try:
        recent = operations.ledger.recent_school_owners()
        if isinstance(recent, set):
            count = max(count, len((active_keys or set()) | recent))
        elif type(recent) is int:
            count = max(count, recent)
    except Exception:
        pass
    if count <= 3:
        return INSTALLATION_LIMITS
    scaled = min(count, 20)
    return (
        (60, max(INSTALLATION_LIMITS[0][1], ACCOUNT_LIMITS[0][1] * scaled)),
        (3600, max(INSTALLATION_LIMITS[1][1], ACCOUNT_LIMITS[1][1] * scaled)),
        (86400, max(INSTALLATION_LIMITS[2][1], ACCOUNT_LIMITS[2][1] * scaled)),
    )


class SchoolTrafficPaused(httpx.ConnectError):
    """The application stopped this request before it was sent."""

    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


def owner_key(username):
    return operations.OperationLedger.key(username.strip().casefold(), "school-traffic", "", "")


def _check_or_reserve(username, *, cost=1, action="", allow_auth_pause=False, dry_run=False):
    if not username:
        raise SchoolTrafficPaused("学校请求缺少已绑定账号")
    try:
        delay = operations.ledger.reserve_school_requests(
            owner_key(username), cost, action, ACCOUNT_LIMITS, installation_limits(),
            ACTION_LIMITS.get(action, ()),
            global_action_limits=INSTALLATION_SMS_LIMITS if action == "sms" else (),
            allow_auth_pause=allow_auth_pause,
            dry_run=dry_run,
        )
    except sqlite3.Error:
        raise SchoolTrafficPaused("请求预算无法保存，已暂停学校请求") from None
    if delay is None:
        raise SchoolTrafficPaused("账号需要本人完成学校验证")
    if delay:
        raise SchoolTrafficPaused("已达到本应用的请求频率上限，请等待冷却后再试", delay)


def reserve(username, *, cost=1, action="", allow_auth_pause=False):
    _check_or_reserve(username, cost=cost, action=action, allow_auth_pause=allow_auth_pause, dry_run=False)


def ensure_headroom(username, cost, *, action="", allow_auth_pause=False):
    _check_or_reserve(username, cost=cost, action=action, allow_auth_pause=allow_auth_pause, dry_run=True)


def request_guard(client, request):
    raw = urlsplit(from_webvpn_url(trusted_url(str(request.url))))
    if not client.traffic_allowed():
        raise SchoolTrafficPaused("账号已暂停学校请求")
    action = ""
    if request.method == "POST" and raw.hostname == "sso.buaa.edu.cn":
        action = {"/login": "login", "/token": "sms"}.get(raw.path, "")
    reserve(client.operation_user, action=action, allow_auth_pause=client.interactive_auth.get())


def note_response(client, response):
    if response.status_code != 429 or not client.operation_user:
        return
    retry_after = response.headers.get("Retry-After", "")
    stamp = time.time()
    try:
        if retry_after.isascii() and retry_after.isdigit():
            delay = float(retry_after)
        else:
            parsed = parsedate_to_datetime(retry_after)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            delay = parsed.timestamp() - stamp
        if not math.isfinite(stamp + delay):
            delay = 300
    except (ValueError, TypeError, OverflowError):
        delay = 300
    operations.ledger.cool_school_requests(owner_key(client.operation_user), stamp + max(300, delay))


def auth_pause(username):
    return operations.ledger.school_auth_pause(owner_key(username))


def set_auth_pause(username, reason):
    operations.ledger.set_school_auth_pause(owner_key(username), reason)
