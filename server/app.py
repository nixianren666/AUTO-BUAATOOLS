"""
BUAA 课程独立签到软件 - FastAPI 后端控制器 (支持多学生账号并发管理与分账号日志)
"""

import asyncio
import datetime
import json
import logging
import os
import pathlib
import sys
import httpx
from typing import Any, Dict, List, Optional

logger = logging.getLogger("buaa_signin_server")

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictBool, Field, field_validator
from typing import Literal, Annotated
import tempfile
from core.version import VERSION
from core import operations
from core.domain import now as china_now, course_id, course_times, sign_config, autonomous, attendance_allowed, drop_allowed, within_semester, semester_bounds, REQUIREMENTS
from core.boya_actions import perform_boya_action, merge_selected, account_lock
from server.management import install as install_management
from server.presentation import StartupPresentation, capabilities
from server.update_routes import install as install_updates

from core.iclass import IclassClient, IclassSessionExpired
from core.scheduler import SigninScheduler
from core.boya_client import BoyaClient, BoyaApiError, BoyaSessionExpired, extract_real_name_from_stats
from core.boya_scheduler import BoyaScheduler, parse_dt, parse_sign_config, is_auto_select_candidate, random_point_in_radius, get_current_semester_range
from core.boya_crypto import encrypt_local_secret, decrypt_local_secret


from core.profile import resolve_config_path


if getattr(sys, "frozen", False):
    BUNDLE_DIR = pathlib.Path(getattr(sys, "_MEIPASS", sys.executable))
    STATIC_DIR = BUNDLE_DIR / "server" / "static"
    if not STATIC_DIR.exists():
        STATIC_DIR = pathlib.Path(sys.executable).parent / "server" / "static"
else:
    STATIC_DIR = pathlib.Path(__file__).parent / "static"

CONFIG_FILE = resolve_config_path()

# 跨模式平滑同步：若当前配置文件不存在，自动尝试从桌面项目目录或 APPDATA 互通导入
if not CONFIG_FILE.exists() and not os.environ.get("BUAA_CONFIG_FILE") and os.environ.get("TESTING") != "1":
    try:
        candidate_paths = [
            pathlib.Path.home() / "Desktop" / "ubaa" / "config.json",
        ]
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidate_paths.append(pathlib.Path(appdata) / "BUAA-Signin" / "config.json")
        for cand in candidate_paths:
            if cand.exists() and cand != CONFIG_FILE:
                import shutil
                CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cand, CONFIG_FILE)
                break
    except Exception:
        pass


config_read_error = False

def load_config() -> Dict[str, Any]:
    global config_read_error
    config_read_error = False
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("配置格式无效")
                # 兼容旧版本单账号配置
                if "accounts" not in data:
                    accounts_list = []
                    if data.get("username"):
                        pwd = data.get("password", "")
                        if pwd:
                            try:
                                pwd = decrypt_local_secret(pwd)
                            except Exception:
                                pwd = ""
                        accounts_list.append({
                            "username": data.get("username", ""),
                            "name": data.get("username", ""),
                            "password": pwd,
                            "remember": data.get("remember", False),
                            "mode": data.get("mode", "auto"),
                            "auto_checkin": data.get("auto_checkin", False),
                            "_protected_password": data.get("password", ""),
                        })
                    data = {
                        # A valid confirmation belongs to the installation, not
                        # to the presence of a student account. Preserve only
                        # recognized non-secret metadata during legacy migration.
                        **{k:data[k] for k in ('disclaimer_accepted','disclaimer_commitment_version',
                                              'disclaimer_accepted_at','autostart') if k in data},
                        "active_username": data.get("username", ""),
                        "accounts": accounts_list,
                        "global_auto_checkin": data.get("auto_checkin", False),
                        "checkin_interval": data.get("checkin_interval", 20),
                    }
                else:
                    for acc in data.get("accounts", []):
                        if not isinstance(acc, dict):
                            raise ValueError("账号配置格式无效")
                        if acc.get("password"):
                            acc["_protected_password"] = acc["password"]
                            try:
                                acc["password"] = decrypt_local_secret(acc["password"])
                            except Exception:
                                acc["password"] = ""
                                acc["auto_checkin"] = acc["boya_auto_select"] = acc["boya_auto_sign"] = False
                return data
        except Exception:
            config_read_error = True
    return {
        "active_username": "",
        "accounts": [],
        "global_auto_checkin": False,
        "checkin_interval": 20,
    }


def save_config(cfg):
    if os.environ.get("TESTING") == "1":
        return
    if config_read_error:
        raise RuntimeError("原配置无法读取，已保留原文件；请先恢复配置再保存")
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=CONFIG_FILE.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(cfg, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, CONFIG_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

app = FastAPI(title="BUAA Course Signin Multi-Account", version=VERSION)
install_management(app)
install_updates(app)
operations.configure(CONFIG_FILE.with_name("operations.sqlite"))

# 结构化运行日志
logs_list: List[Dict[str, Any]] = []


def add_log(
    level: str,
    message: str,
    username: Optional[str] = None,
    user_name: Optional[str] = None,
    category: str = "regular",
):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    entry = {
        "time": timestamp,
        "level": level,
        "message": message,
        "username": username or "",
        "user_name": user_name or "",
        "category": category,
    }
    logs_list.append(entry)
    if len(logs_list) > 1000:
        logs_list.pop(0)
    notifications = globals().get('wechat_notifications')
    if notifications:
        notifications.offer(entry)


class AccountState:
    def __init__(
        self,
        username: str,
        name: str = "",
        password: str = "",
        mode: str = "auto",
        remember: bool = True,
        auto_checkin: bool = True,
        boya_auto_select: bool = False,
        boya_auto_sign: bool = False,
        boya_require_auto_sign: bool = True,
        boya_allow_offline: bool = False,
        campus: str = "北京",
    ):
        self.removed = False
        self.auth_lock = asyncio.Lock()
        self.maintenance = False
        self.auth_epoch = 0
        self.auth_retry_after = 0.0
        self.auth_requires_input = False
        self.protected_password = ""
        self.boya_lock = __import__("threading").RLock()
        self.boya_pending_courses = operations.ledger.reservations(username)
        self.boya_targets = dict(REQUIREMENTS)
        self.regular_health = {"stale": True, "last_success": None}
        self.boya_health = {"stale": True, "last_success": None}
        self.username = username
        self.name = name or username
        self.password = password
        self.mode = mode
        self.remember = remember
        self.auto_checkin = auto_checkin
        self.boya_auto_select = boya_auto_select
        self.boya_auto_sign = boya_auto_sign
        self.boya_require_auto_sign = True
        self.boya_allow_offline = False
        self.campus = campus or "北京"
        self.client = IclassClient(mode=("webvpn" if mode == "webvpn" else "direct"))
        self.boya_client = BoyaClient(mode=("webvpn" if mode == "webvpn" else "direct"))
        self.client.operation_user = username
        self.client.request_guard = lambda: not self.removed and not self.maintenance
        self.boya_client.operation_user = username
        self.boya_client.request_guard = lambda: not self.removed and not self.maintenance
        self.last_classes: List[Dict[str, Any]] = []
        self.last_refresh_time: Optional[str] = None
        self.boya_all_courses: Optional[List[Dict[str, Any]]] = None
        self.boya_selected_courses: Optional[List[Dict[str, Any]]] = None
        self.boya_statistics: Optional[Dict[str, Any]] = None
        self.boya_last_refresh_time: Optional[str] = None
        self._is_connecting: bool = False

    def to_dict(self, is_active: bool = False) -> Dict[str, Any]:
        return {
            "username": self.username,
            "name": self.name,
            "mode": self.mode,
            "remember": self.remember,
            "auto_checkin": self.auto_checkin,
            "boya_auto_select": self.boya_auto_select,
            "boya_auto_sign": self.boya_auto_sign,
            "boya_require_auto_sign": getattr(self, "boya_require_auto_sign", True),
            "boya_allow_offline": getattr(self, "boya_allow_offline", False),
            "campus": getattr(self, "campus", "北京"),
            "authenticated": self.client.is_authenticated() or self.boya_client.is_authenticated(),
            "iclass_authenticated": bool(self.client.user_id and self.client.session_id),
            "boya_authenticated": self.boya_client.is_authenticated(),
            "is_active": is_active,
            "regular_health": self.regular_health,
            "boya_health": self.boya_health,
            "boya_targets": self.boya_targets,
            "auth_requires_input": self.auth_requires_input,
            "connecting": self._is_connecting,
            "course_count": len(self.last_classes),
            "signed_count": len([c for c in self.last_classes if c.get("signStatus") == 1]),
            "last_refresh_time": self.last_refresh_time,
            "boya_course_count": len(self.boya_all_courses) if self.boya_all_courses is not None else 0,
            "boya_selected_count": len(self.boya_selected_courses) if self.boya_selected_courses is not None else 0,
            "boya_last_refresh_time": self.boya_last_refresh_time,
        }


# 全局多账号管理状态
config = load_config()
accounts: Dict[str, AccountState] = {}
active_username: Optional[str] = config.get("active_username") or None


def get_active_account() -> Optional[AccountState]:
    global active_username
    if active_username and active_username in accounts:
        return accounts[active_username]
    if accounts:
        active_username = next(iter(accounts.keys()))
        return accounts[active_username]
    return None


def resolve_account(username=None):
    if username is not None:
        account = accounts.get(username)
        if account is None or account.removed:
            raise HTTPException(status_code=404, detail="指定账号不存在")
        return account
    return get_active_account()

async def dispose_account(account):
    account.removed = True
    try:
        await wechat_notifications.remove(account.username)
    except ValueError:
        add_log('error','微信绑定清理未能保存，本进程已停止通知；请检查私有目录后核对绑定状态',username=account.username)
    try:
        await remove_td_account(account.username)
    except Exception:
        # The removed identity already fails TD's preflight. Still dispose the
        # original clients if TD storage itself has failed.
        add_log('error', 'TD暂停设置无法保存；账号已移除且本进程不会再为其发包，请检查磁盘权限', username=account.username, category='td')
    account.auth_epoch += 1
    account.auto_checkin = account.boya_auto_select = account.boya_auto_sign = False
    scheduler.remove_account(account.username)
    boya_scheduler.remove_account(account.username)
    # Mark removed before waiting: in-flight preflights can no longer authorize POST.
    def close_boya():
        with account_lock(account):
            account.boya_client.close()
    async with account.auth_lock:
        await asyncio.to_thread(close_boya)
        async with account.client._signin_lock:
            await account.client.close()
    account.password = ""
    account.boya_pending_courses.clear()


def get_scheduler_accounts() -> List[Dict[str, Any]]:
    """返回所有启用了自动打卡的学生账号供后台定时巡检（多学生并行后台守护，不受前台切换影响）"""
    result = []
    for acc in accounts.values():
        if acc.auto_checkin:
            result.append({
                "username": acc.username,
                "name": acc.name,
                "client": acc.client,
                "account": acc,
            })
    return result


scheduler = SigninScheduler(
    get_active_accounts=get_scheduler_accounts,
    on_event_log=add_log,
    reconnect_account=lambda acc: connect_single_account(acc),
)
main_loop = None

async def fetch_normal_ranges(account, first, last):
    rows = []
    date = first
    while date <= last:
        if account.removed:
            raise RuntimeError("账号已移除")
        rows.extend(await account.client.get_classes(date))
        date += datetime.timedelta(days=1)
    return rows

def normal_ranges_from_worker(account, first, last):
    if main_loop is None or not main_loop.is_running():
        raise RuntimeError("普通课表服务未就绪")
    future = asyncio.run_coroutine_threadsafe(fetch_normal_ranges(account, first, last), main_loop)
    try:
        return future.result(timeout=30)
    except BaseException:
        future.cancel()
        raise

boya_scheduler = BoyaScheduler(get_accounts_func=lambda: list(accounts.values()), add_log_func=add_log, ordinary_courses=normal_ranges_from_worker)


def sync_config():
    """将当前内存中的账号状态同步回 config.json"""
    if os.environ.get("TESTING") == "1":
        return
    accounts_data = []
    for acc in accounts.values():
        stored_pwd = encrypt_local_secret(acc.password) if (acc.remember and acc.password) else acc.protected_password if acc.remember else ""
        accounts_data.append({
            "username": acc.username,
            "name": acc.name,
            "password": stored_pwd,
            "remember": acc.remember,
            "mode": acc.mode,
            "auto_checkin": acc.auto_checkin,
            "boya_auto_select": getattr(acc, "boya_auto_select", False),
            "boya_auto_sign": getattr(acc, "boya_auto_sign", False),
            "boya_require_auto_sign": getattr(acc, "boya_require_auto_sign", True),
            "boya_allow_offline": getattr(acc, "boya_allow_offline", False),
            "campus": getattr(acc, "campus", "北京"),
            "boya_targets": acc.boya_targets,
        })
    candidate = {**config, "active_username": active_username or "", "accounts": accounts_data,
                 "global_auto_checkin": scheduler.enabled, "checkin_interval": scheduler.interval_seconds}
    save_config(candidate)
    config.update(candidate)


def persist_switch(restore, stop_requested=False):
    try:
        sync_config()
        return True
    except Exception:
        restore()
        if not stop_requested:
            raise HTTPException(status_code=503, detail="配置无法保存；已撤回本次开启/设置变更")
        add_log("warning", "后台已暂停，但配置保存失败；重启前请确认保存，否则旧开关可能恢复")
        return False


class LoginRequest(BaseModel):
    username: str
    password: str
    captcha: Optional[str] = ""
    captcha_id: Optional[str] = ""
    remember: Optional[bool] = True
    mode: Optional[str] = "auto"
    auto_checkin: Optional[bool] = True


class SwitchAccountRequest(BaseModel):
    username: str


class RemoveAccountRequest(BaseModel):
    username: str


class ToggleAutoRequest(BaseModel):
    username: str
    enabled: bool


class ModeRequest(BaseModel):
    username: Optional[str] = None
    mode: str  # "auto", "direct", "webvpn"


class SigninRequest(BaseModel):
    course_id: str = Field(pattern=r"^[1-9][0-9]*$")
    username: Optional[str] = None


class AutoCheckinRequest(BaseModel):
    enabled: bool
    interval: Optional[int] = Field(default=20, strict=True, ge=10, le=60)


class BoyaActionRequest(BaseModel):
    course_id: int = Field(gt=0, strict=True)
    username: Optional[str] = None


class BoyaSignRequest(BaseModel):
    course_id: int = Field(gt=0, strict=True)
    sign_type: Literal[1, 2] = 1  # 1 为签到, 2 为签退
    lat: Optional[float] = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    lng: Optional[float] = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    username: Optional[str] = None

    @field_validator("sign_type", mode="before")
    @classmethod
    def strict_sign_type(cls, value):
        if type(value) is not int or value not in (1, 2):
            raise ValueError("签到类型必须为整数1或2")
        return value


class BoyaToggleAutoRequest(BaseModel):
    auto_select: Optional[bool] = None
    auto_sign: Optional[bool] = None
    campus: Optional[str] = None
    username: Optional[str] = None
    require_auto_sign: Optional[bool] = None
    allow_offline: Optional[bool] = None
    targets: Optional[Dict[str, Annotated[int, Field(strict=True, ge=0, le=20)]]] = None


@app.on_event("startup")
async def on_startup():
    global main_loop
    main_loop = asyncio.get_running_loop()
    if os.environ.get("BUAA_SMOKE_PROFILE") == "1":
        if os.environ.get("TESTING") != "1" or not os.environ.get("BUAA_CONFIG_FILE"):
            raise RuntimeError("验收配置必须与用户配置隔离")
        from core.smoke import seed
        seed(sys.modules[__name__])
        return
    add_log("info", "BUAA 独立课程签到助手 (多学生并发管理版) 服务已启动。")
    if config_read_error:
        add_log("error", "配置文件损坏，已保留原文件且未启动账号；请恢复配置后重启。")
    # 初始化保存的多账号
    saved_accounts = config.get("accounts", [])
    for item in saved_accounts:
        uname = item.get("username", "")
        if not uname:
            continue
        acc = AccountState(
            username=uname,
            name=item.get("name", uname),
            password=item.get("password", ""),
            mode=item.get("mode", "auto"),
            remember=item.get("remember", True),
            auto_checkin=item.get("auto_checkin", True),
            boya_auto_select=item.get("boya_auto_select", False),
            boya_auto_sign=item.get("boya_auto_sign", False),
            boya_require_auto_sign=item.get("boya_require_auto_sign", True),
            boya_allow_offline=item.get("boya_allow_offline", False),
            campus=item.get("campus", "北京"),
        )
        accounts[uname] = acc
        acc.protected_password = item.get("_protected_password", "")
        targets = item.get("boya_targets")
        if isinstance(targets, dict) and set(targets) == set(REQUIREMENTS) and all(type(value) is int and 0 <= value <= 20 for value in targets.values()):
            acc.boya_targets = dict(targets)
        if acc.protected_password and not acc.password:
            acc.auth_requires_input = True
            add_log("warning", "保存的凭据不可解密，原密文已保留，请为此账号重新登录。", username=acc.username)

    global active_username
    if not active_username and accounts:
        active_username = next(iter(accounts.keys()))

    if config.get("global_auto_checkin"):
        scheduler.start(interval_seconds=config.get("checkin_interval", 20))

    # 若任一账号启用了博雅自动抢选或签到，启动博雅后台守护引擎
    if any(getattr(a, "boya_auto_select", False) or getattr(a, "boya_auto_sign", False) for a in accounts.values()):
        boya_scheduler.start(interval_seconds=60)

    # 后台并发自动连接所有保存密码的账号
    asyncio.create_task(auto_connect_saved_accounts())


async def auto_connect_saved_accounts():
    tasks = []
    for acc in list(accounts.values()):
        if acc.remember and acc.password:
            tasks.append(connect_single_account(acc))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def sync_boya_login(acc, mode, cookies):
    with account_lock(acc):
        if acc.removed:
            return False
        acc.boya_client.mode = mode
        acc.boya_client.sync_cookies_from(cookies)
        if not acc.boya_client.acquire_token():
            return False
        pool = acc.boya_client.query_courses()
        selected = acc.boya_client.query_chosen_courses()
        stats = acc.boya_client.query_statistics()
        if acc.removed:
            return False
        acc.boya_all_courses, acc.boya_selected_courses, acc.boya_statistics = pool, selected, stats
        acc.boya_last_refresh_time = china_now().isoformat(timespec="seconds")
        acc.boya_health = {"stale":False,"last_success":acc.boya_last_refresh_time,"error":None}
        real_name = extract_real_name_from_stats(stats)
        if real_name and real_name != acc.username:
            acc.name = real_name
        return True


async def connect_single_account(acc: AccountState) -> bool:
    import time
    if acc.removed or acc.auth_requires_input or time.monotonic() < acc.auth_retry_after:
        return False
    # Concurrent refreshes share one authentication attempt, with a bounded cooldown.
    async with acc.auth_lock:
        if acc.removed or acc.auth_requires_input or time.monotonic() < acc.auth_retry_after:
            return False
        acc.auth_retry_after = time.monotonic() + 60
        acc.maintenance = acc._is_connecting = True
        acc.auth_epoch += 1
        try:
            with account_lock(acc):
                acc.boya_client.token = None
            async with acc.client._signin_lock:
                return await _connect_single_account(acc)
        finally:
            acc.maintenance = acc._is_connecting = False


async def _connect_single_account(acc: AccountState) -> bool:
    add_log("info", f"正在为学生账号 [{acc.name or acc.username}] 建立连接...", username=acc.username, user_name=acc.name)
    modes_to_try = ["direct", "webvpn"] if acc.mode in ("auto", "direct") else [acc.mode]

    for attempt_mode in modes_to_try:
        acc.client.mode = attempt_mode
        try:
            acc.regular_health["stale"] = acc.boya_health["stale"] = True
            res = await acc.client.login_sso(username=acc.username, password=acc.password)
            if res.get("status") == "success":
                real_name = res.get("user", {}).get("name")
                if real_name and real_name != acc.username:
                    acc.name = real_name

                # 优先同步博雅系统授权与课程数据
                try:
                    ready = await asyncio.to_thread(sync_boya_login, acc, attempt_mode, acc.client.client.cookies)
                    if ready:
                        add_log("success", "博雅授权与排课同步成功。", username=acc.username, user_name=acc.name, category="boya")
                except Exception as be:
                    logger.debug(f"Boya auto sync during connect: {type(be).__name__}")

                # 尝试接入常规课堂签到系统
                iclass_ok = await acc.client.login_iclass()
                if iclass_ok:
                    iclass_name = acc.client.user_info.get("name")
                    if iclass_name and iclass_name != acc.username:
                        acc.name = iclass_name
                    add_log("success", f"学生 [{acc.name}] 登录及常规课堂系统接入成功！({ '校园网直连' if attempt_mode == 'direct' else 'WebVPN 外网' })", username=acc.username, user_name=acc.name)
                    try:
                        classes = await acc.client.get_today_classes()
                        acc.last_classes = classes
                        acc.last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
                        acc.regular_health = {"stale":False,"last_success":china_now().isoformat(timespec="seconds")}
                    except Exception:
                        pass
                else:
                    add_log("warning", "统一认证成功，常规考勤尚未就绪；博雅状态以授权指示为准。", username=acc.username, user_name=acc.name)

                if acc.removed:
                    return False
                sync_config()
                return True
            elif res.get("status") == "captcha_required":
                acc.auth_requires_input = True
                add_log("warning", f"学生 [{acc.name}] 自动登录被阻断（需要图形验证码），请在界面手动登录。", username=acc.username, user_name=acc.name)
                return False
            elif res.get("status") != "success" and any(word in str(res.get("message", "")) for word in ("密码", "账号")):
                acc.auth_requires_input = True
                add_log("warning", "自动认证未通过，请手动核对账号凭据；已暂停自动登录。", username=acc.username)
                return False
        except Exception as e:
            if attempt_mode != modes_to_try[-1]:
                await acc.client.close()
                acc.client = IclassClient(mode="webvpn")
                acc.client.operation_user = acc.username
                acc.client.request_guard = lambda: not acc.removed and not acc.maintenance
                continue
            add_log("error", f"学生 [{acc.name}] 连接异常: {type(e).__name__}", username=acc.username, user_name=acc.name)
            return False

    return False



@app.get("/api/status")
async def get_status(username: Optional[str] = None):
    curr = resolve_account(username)
    mode = curr.mode if curr else config.get("default_mode", "direct")
    is_authed = bool(curr and (curr.client.is_authenticated() or curr.boya_client.is_authenticated()))
    return {
        "authenticated": is_authed,
        "mode": mode,
        "user": {"name": curr.name, "schoolid": curr.username} if curr else None,
        "auto_checkin": scheduler.enabled,
        "active_account": curr.to_dict(is_active=True) if curr else None,
        "accounts_count": len(accounts),
        "global_auto_checkin": scheduler.enabled,
        "checkin_interval": scheduler.interval_seconds,
    }


@app.get("/api/accounts")
async def list_accounts():
    curr_user = active_username
    acc_list = [
        acc.to_dict(is_active=(acc.username == curr_user))
        for acc in accounts.values()
    ]
    return {
        "accounts": acc_list,
        "active_username": curr_user,
        "global_auto_checkin": scheduler.enabled,
        "total_count": len(acc_list),
        "online_count": len([a for a in acc_list if a.get("authenticated")]),
    }


@app.post("/api/accounts/switch")
async def switch_account(req: SwitchAccountRequest):
    global active_username
    if req.username not in accounts:
        raise HTTPException(status_code=404, detail="Account not found")

    previous_username=active_username
    active_username = req.username
    try:sync_config()
    except Exception:
        active_username=previous_username
        raise HTTPException(503,'学生视图切换保存失败，已保留原学生，请检查磁盘后重试') from None
    target_acc = accounts[active_username]
    add_log("info", f"当前操作视图已切换至学生: 【{target_acc.name} ({target_acc.username})】", username=target_acc.username, user_name=target_acc.name)
    # 若目标账号尚未完成鉴权且保存了密码，在切换时立即触发自动后台连接
    if (not target_acc.client.is_authenticated() or not target_acc.boya_client.is_authenticated()) and target_acc.password:
        asyncio.create_task(connect_single_account(target_acc))

    return {
        "status": "ok",
        "active_account": target_acc.to_dict(is_active=True),
        "classes": target_acc.last_classes or [],
        "boya_selected": enrich_selected_courses(target_acc.boya_selected_courses or [], target_acc.boya_all_courses or []),
        "boya_courses": enrich_pool(target_acc.boya_all_courses or []),
        "boya_statistics": compute_semester_statistics(target_acc.boya_selected_courses or [], target_acc.boya_statistics or {}),
        "boya_cached": target_acc.boya_all_courses is not None or target_acc.boya_selected_courses is not None,
    }


@app.post("/api/accounts/toggle_auto")
async def toggle_account_auto_checkin(req: ToggleAutoRequest):
    if req.username not in accounts:
        raise HTTPException(status_code=404, detail="Account not found")

    acc = accounts[req.username]
    old_enabled = acc.auto_checkin
    acc.auto_checkin = req.enabled
    persisted = persist_switch(lambda: setattr(acc,"auto_checkin",old_enabled) if req.enabled else None, stop_requested=not req.enabled)
    add_log(
        "info",
        f"学生 【{acc.name}】 的自动签到开关已{'开启' if req.enabled else '关闭'}",
        username=acc.username,
        user_name=acc.name,
    )
    return {"status": "ok", "username": acc.username, "auto_checkin": acc.auto_checkin, "persisted": persisted}


@app.post("/api/accounts/remove")
async def remove_account(req: RemoveAccountRequest):
    global active_username
    if req.username not in accounts:
        raise HTTPException(status_code=404, detail="Account not found")

    acc = accounts.pop(req.username)
    await dispose_account(acc)
    add_log("info", f"学生账号 【{acc.name} ({acc.username})】 已退出并移除。", username=acc.username, user_name=acc.name)

    if active_username == req.username:
        active_username = next(iter(accounts.keys())) if accounts else None

    sync_config()
    return {"status": "ok", "active_username": active_username}


@app.post("/api/mode")
async def switch_mode(req: ModeRequest):
    new_mode = req.mode.lower()
    if new_mode not in ("auto", "direct", "webvpn"):
        raise HTTPException(status_code=400, detail="Invalid mode")

    curr = resolve_account(req.username)
    config["default_mode"] = new_mode
    if curr:
        async with curr.auth_lock:
            curr.maintenance = True
            curr.auth_epoch += 1
            try:
                async with curr.client._signin_lock:
                    await curr.client.close()
                    def reset_boya():
                        with account_lock(curr):
                            curr.boya_client.close()
                            curr.boya_client = BoyaClient(mode="webvpn" if new_mode == "webvpn" else "direct")
                            curr.boya_client.operation_user = curr.username
                            curr.boya_client.request_guard = lambda: not curr.removed and not curr.maintenance
                    await asyncio.to_thread(reset_boya)
                    curr.client = IclassClient(mode="webvpn" if new_mode == "webvpn" else "direct")
                    curr.client.operation_user = curr.username
                    curr.client.request_guard = lambda: not curr.removed and not curr.maintenance
                    curr.mode = new_mode
                    curr.auth_retry_after = 0
                    curr.regular_health["stale"] = curr.boya_health["stale"] = True
            finally:
                curr.maintenance = False
        if curr.password and not curr.auth_requires_input:
            asyncio.create_task(connect_single_account(curr))
        add_log(
            "info",
            f"学生 【{curr.name}】 连接模式已切换为: {new_mode}",
            username=curr.username,
            user_name=curr.name,
        )
    else:
        add_log("info", f"系统默认接入模式已切换为: { '校园网直连' if new_mode == 'direct' else ('WebVPN 外网' if new_mode == 'webvpn' else '智能自动') }")

    sync_config()
    return {"status": "ok", "mode": new_mode, "reconnecting": bool(curr and curr.password and not curr.auth_requires_input)}


@app.post("/api/login")
async def login(req: LoginRequest):
    req_mode = (req.mode or "auto").lower()
    if req_mode not in ("auto", "direct", "webvpn") or not req.username.strip() or not req.password:
        raise HTTPException(status_code=400, detail="账号、密码或连接模式无效")
    acc = accounts.get(req.username)
    if acc is None:
        acc = AccountState(req.username, auto_checkin=False)
        accounts[req.username] = acc
    async with acc.auth_lock:
        if acc.removed:
            raise HTTPException(status_code=409, detail="账号已移除，请重新添加")
        acc.maintenance = acc._is_connecting = True
        acc.auth_epoch += 1
        acc.auth_requires_input = False
        try:
            with account_lock(acc):
                acc.boya_client.token = None
            async with acc.client._signin_lock:
                response = await _login_locked(req)
            if response.get("status") != "success":
                acc.auth_requires_input = True
            return response
        finally:
            acc.maintenance = acc._is_connecting = False


async def _login_locked(req: LoginRequest):
    global active_username
    req_mode = (req.mode or "auto").lower()

    # 查找已有或新建
    if req.username in accounts:
        acc = accounts[req.username]
        acc.password = req.password
        acc.mode = req_mode
        acc.remember = bool(req.remember)
        acc.auto_checkin = bool(req.auto_checkin)
    else:
        acc = AccountState(
            username=req.username,
            name=req.username,
            password=req.password,
            mode=req_mode,
            remember=bool(req.remember),
            auto_checkin=bool(req.auto_checkin),
        )
        accounts[req.username] = acc

    modes_to_try = ["direct", "webvpn"] if req_mode in ("auto", "direct") else [req_mode]

    for attempt_mode in modes_to_try:
        acc.client.mode = attempt_mode
        add_log("info", f"正在通过 [{ '校园网直连' if attempt_mode == 'direct' else 'WebVPN 外网接入' }] 连接北航统一身份认证...", username=acc.username, user_name=acc.name)

        acc.regular_health["stale"] = acc.boya_health["stale"] = True
        try:
            res = await acc.client.login_sso(
                username=req.username,
                password=req.password,
                captcha=req.captcha or "",
                captcha_id=req.captcha_id or "",
            )
        except (httpx.HTTPError, ValueError):
            res = {"status":"failed","message":"统一认证通信未完成，请检查网络通道后重试"}

        if res.get("status") == "captcha_required":
            add_log("warning", f"统一身份认证需要图形验证码", username=acc.username, user_name=acc.name)
            return res

        if res.get("status") != "success":
            err_msg = res.get("message") or "登录失败"
            if "账号" in err_msg or "密码" in err_msg or attempt_mode == modes_to_try[-1]:
                add_log("error", f"统一身份认证失败: {err_msg}", username=acc.username, user_name=acc.name)
                return {"status": "failed", "message": err_msg}
            continue

        real_name = res.get("user", {}).get("name")
        if real_name:
            acc.name = real_name
        add_log("success", f"统一身份认证成功！欢迎您，{acc.name}", username=acc.username, user_name=acc.name)
        active_username = acc.username

        # 优先同步博雅系统授权与课程数据
        ready = False
        try:
            ready = await asyncio.to_thread(sync_boya_login, acc, attempt_mode, acc.client.client.cookies)
            if ready:
                add_log("success", "博雅授权与排课同步成功。", username=acc.username, user_name=acc.name, category="boya")
        except Exception as be:
            logger.debug(f"Boya auto sync during login: {type(be).__name__}")
            add_log("warning", f"【{acc.name}】博雅系统授权同步异常: {type(be).__name__}", username=acc.username, user_name=acc.name, category="boya")

        # 接入 iclass 课堂签到系统
        add_log("info", f"正在接入 iclass 课堂签到系统 ({'校园网直连' if attempt_mode == 'direct' else 'WebVPN 外网'})...", username=acc.username, user_name=acc.name)
        iclass_ok = await acc.client.login_iclass()
        if iclass_ok:
            iclass_name = acc.client.user_info.get("name")
            if iclass_name and iclass_name != acc.username:
                acc.name = iclass_name
            add_log("success", f"【{acc.name}】iclass 课堂考勤系统接入成功！", username=acc.username, user_name=acc.name)
            try:
                classes = await acc.client.get_today_classes()
                acc.last_classes = classes
                acc.last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
                acc.regular_health = {"stale":False,"last_success":china_now().isoformat(timespec="seconds")}
            except Exception as ce:
                iclass_ok = False
                add_log("error", f"【{acc.name}】拉取今日课表失败: {type(ce).__name__}", username=acc.username, user_name=acc.name, category="regular")
        else:
            add_log("warning", "统一认证成功，常规考勤尚未就绪；博雅状态以授权指示为准。", username=acc.username, user_name=acc.name)

        if acc.removed:
            raise HTTPException(status_code=409, detail="认证过程中账号已移除")
        sync_config()
        return {
            "status": "success",
            "authenticated": True,
            "user": {"name": acc.name, "schoolid": acc.username},
            "mode": attempt_mode,
            "iclass_ready": iclass_ok,
            "boya_ready": bool(ready),
        }


@app.post("/api/logout")
async def logout(username: Optional[str] = None):
    """退出明确指定的账号，兼容旧客户端活跃账号默认值。"""
    curr = resolve_account(username)
    if not curr:
        return {"status": "ok"}

    global active_username
    username = curr.username
    acc = accounts.pop(username, None)
    if acc:
        await dispose_account(acc)
        add_log("info", f"学生账号 【{acc.name}】 已退出登录。", username=acc.username, user_name=acc.name)

    active_username = next(iter(accounts.keys())) if accounts else None
    sync_config()
    return {"status": "ok", "active_username": active_username}


@app.get("/api/classes")
async def get_today_classes(username: Optional[str] = None):
    curr = resolve_account(username)
    if not curr:
        return {"status": "unauthenticated", "classes": []}

    # 若尚未完成鉴权且存有密码，在获取前尝试自动建立连接
    if (not curr.client.is_authenticated() or not curr.client.session_id) and curr.password:
        try:
            await connect_single_account(curr)
        except Exception as conn_err:
            logger.debug(f"Auto connect before get_today_classes failed: {type(conn_err).__name__}")

    # 若此时仍未鉴权（如离线或测试模式），坚决返回既有课表缓存，杜绝误显假空态
    if not curr.client.is_authenticated() or not curr.client.session_id:
        return {
            "status": "stale",
            "stale": True,
            "classes": curr.last_classes or [],
            "username": curr.username,
            "name": curr.name,
            "offline": True,
        }

    try:
        classes = await curr.client.get_today_classes()
        curr.last_classes = classes
        curr.last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
        curr.regular_health = {"stale": False, "last_success": china_now().isoformat(timespec="seconds"), "error": None}
        if classes:
            add_log("info", f"【{curr.name}】今日课表刷新完成，共 {len(classes)} 门课。", username=curr.username, user_name=curr.name, category="regular")
        else:
            add_log("info", f"【{curr.name}】今日常规课程暂无排课或无需签到。", username=curr.username, user_name=curr.name, category="regular")
        return {"status": "success", "classes": classes, "username": curr.username, "name": curr.name}
    except Exception as e:
        logger.debug(f"Fetch classes error: {type(e).__name__}")
        # A tunnel/DNS/read failure is not evidence of expired authentication.
        # Only explicit authentication responses may initiate credential use.
        if isinstance(e, IclassSessionExpired) and curr.password:
            try:
                ok = await connect_single_account(curr)
                if ok and curr.client.is_authenticated():
                    classes = await curr.client.get_today_classes()
                    curr.last_classes = classes
                    curr.last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
                    curr.regular_health = {"stale": False, "last_success": china_now().isoformat(timespec="seconds"), "error": None}
                    return {"status": "success", "classes": classes, "username": curr.username, "name": curr.name}
            except Exception:
                pass
        add_log("error", f"【{curr.name}】获取常规课程课表失败: {type(e).__name__}", username=curr.username, user_name=curr.name, category="regular")
        curr.regular_health = {**curr.regular_health, "stale": True, "error": type(e).__name__}
        return {"status": "stale", "stale": True, "classes": curr.last_classes or [], "username": curr.username, "name": curr.name, "message": "课表未同步，显示上次成功数据"}



@app.post("/api/signin")
async def perform_signin(req: SigninRequest):
    if not req.course_id:
        raise HTTPException(status_code=400, detail="Course ID required")

    # 指定账号或当前活跃账号
    target_acc = resolve_account(req.username)

    if not target_acc or not target_acc.client.is_authenticated():
        raise HTTPException(status_code=401, detail="Account not authenticated")

    add_log(
        "info",
        f"正在为学生 【{target_acc.name}】 提交排课 ID [{req.course_id}] 的打卡签到...",
        username=target_acc.username,
        user_name=target_acc.name,
    )
    target_client, epoch = target_acc.client, target_acc.auth_epoch
    def current_operation():
        return not target_acc.removed and not target_acc.maintenance and target_acc.client is target_client and target_acc.auth_epoch == epoch
    success, msg = await target_client.perform_signin(req.course_id, guard=current_operation)
    if success:
        add_log("success", f"【{target_acc.name}】排课 [{req.course_id}] 签到成功: {msg}", username=target_acc.username, user_name=target_acc.name)
        # 步骤完成铁律：签到成功后立即向学校拉取最新课表，即时更新内存与前台状态
        try:
            refreshed = await target_acc.client.get_today_classes()
            if refreshed is not None:
                target_acc.last_classes = refreshed
                target_acc.last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
        except Exception as ref_err:
            logger.debug(f"Post manual signin schedule refresh error: {type(ref_err).__name__}")
    else:
        add_log("warning", f"【{target_acc.name}】排课 [{req.course_id}] 签到反馈: {msg}", username=target_acc.username, user_name=target_acc.name)

    return {"success": success, "message": msg}


@app.post("/api/auto_checkin")
async def toggle_global_auto_checkin(req: AutoCheckinRequest):
    interval = req.interval or 20
    old_enabled, old_interval = scheduler.enabled, scheduler.interval_seconds
    if req.enabled:
        scheduler.start(interval_seconds=interval)
    else:
        scheduler.stop()

    def restore():
        if req.enabled:
            scheduler.start(interval_seconds=old_interval) if old_enabled else scheduler.stop()
    persisted = persist_switch(restore, stop_requested=not req.enabled)
    return {"enabled": scheduler.enabled, "interval": scheduler.interval_seconds, "persisted": persisted}


@app.get("/api/boya/status")
async def get_boya_status(username: Optional[str] = None):
    curr = resolve_account(username)
    if not curr:
        return {"authenticated": False, "scheduler_running": boya_scheduler.running}
    return {
        "authenticated": curr.boya_client.is_authenticated(),
        "scheduler_running": boya_scheduler.running,
        "boya_auto_select": getattr(curr, "boya_auto_select", False),
        "boya_auto_sign": getattr(curr, "boya_auto_sign", False),
        "boya_require_auto_sign": getattr(curr, "boya_require_auto_sign", True),
        "boya_allow_offline": getattr(curr, "boya_allow_offline", False),
        "campus": getattr(curr, "campus", "北京"),
        "last_refresh_time": getattr(curr, "boya_last_refresh_time", ""),
        "courses_count": len(curr.boya_all_courses) if getattr(curr, "boya_all_courses", None) is not None else 0,
        "selected_count": len(curr.boya_selected_courses) if getattr(curr, "boya_selected_courses", None) is not None else 0,
        "health": curr.boya_health,
        "targets": curr.boya_targets,
        "statistics": curr.boya_statistics if getattr(curr, "boya_statistics", None) is not None else {},
    }



# 真实北航博雅示范课程库（严格分为 4 大类：美育、劳育、国家安全、德育）
def enrich_selected_courses(selected_list, pool_list):
    from core.boya_scheduler import get_course_category
    attendance_names = {0: "待考勤", 1: "考勤通过", 2: "迟到", 3: "早退", 4: "缺勤", 5: "已签到，未签退", 6: "签到异常，未签退", 7: "未签到，已签退", 8: "未签到，签退异常", 9: "双签记录，签到异常", 10: "双签记录，签退异常", 11: "双签记录均异常"}
    result = []
    for raw in selected_list or []:
        c = merge_selected(raw, pool_list or [])
        start, end = course_times(c)
        c["is_ended"] = bool(end and china_now() > end)
        def official_integer(value):
            return int(value) if not isinstance(value, bool) and str(value).isdigit() else None
        checkin = official_integer(c.get("checkin"))
        passed = official_integer(c.get("pass"))
        c["attendance_status"] = {"passed": True if checkin == 1 else (False if checkin in (2,3,4,6,8,9,10,11) else None), "text": attendance_names.get(checkin, "考勤状态未知"), "badge": "badge-green" if checkin == 1 else "badge-amber"}
        c["exam_status"] = {"passed": True if passed == 1 else (False if passed == 0 else None), "text": "考核通过" if passed == 1 else ("考核未通过" if passed == 0 else "待官方考核"), "badge": "badge-green" if passed == 1 else "badge-amber"}
        c["final_passed"] = checkin == 1 and passed == 1
        c["can_sign_in"] = attendance_allowed(c, 1, china_now())
        c["can_sign_out"] = attendance_allowed(c, 2, china_now())
        c["signed_in"] = checkin in (1,5,6,9,10,11)
        c["signed_out"] = checkin in (1,7,8,9,10,11)
        c["can_drop"] = drop_allowed(c, china_now())
        c["autonomous_config_valid"] = autonomous(c, require_windows=True)
        c["status_source"] = "official"
        c["category_key"] = get_course_category(c)
        result.append(c)
    return result

def enrich_pool(courses):
    from core.boya_scheduler import capacity_values, capacity_available, get_course_category
    result=[]
    for raw in courses:
        c=dict(raw)
        current,maximum=capacity_values(c)
        c["category_key"] = get_course_category(c)
        valid=lambda value: not isinstance(value,bool) and str(value).isdigit()
        c.update({"capacity_current":int(current) if valid(current) else None,"capacity_maximum":int(maximum) if valid(maximum) and int(maximum)>0 else None,"capacity_available":capacity_available(c),"autonomous_config_valid":autonomous(c,require_windows=True)})
        result.append(c)
    return result

def compute_semester_statistics(selected_list, sso_stats=None):
    from core.boya_scheduler import get_course_category
    stats = sso_stats if isinstance(sso_stats, dict) else {}
    info = stats.get("semesterInfo") or {}
    start, end = semester_bounds(info)
    known = bool(start and end and start <= china_now() <= end)
    counts = {k: 0 for k in REQUIREMENTS}
    unknown, seen = 0, set()
    for course in selected_list or []:
        cid = course_id(course)
        if cid is None or cid in seen:
            continue
        seen.add(cid)
        if not known or not within_semester(course, info):
            if not all(course_times(course)):
                unknown += 1
            continue
        if str(course.get("checkin")) == "1" and str(course.get("pass")) == "1":
            category = get_course_category(course)
            if category in counts:
                counts[category] += 1
    total = sum(min(counts[k], REQUIREMENTS[k]) for k in counts)
    result = {"semester_known": known, "unknown_date_count": unknown, "semester_name": info.get("semesterName") or "官方校历待同步", "semester_start": str(info.get("semesterStartDate") or ""), "semester_end": str(info.get("semesterEndDate") or ""), "semester_passed_total": total, "semester_required_total": 6, "semester_compliance_rate": round(total/6*100) if known else None, "valid_count": total if known else None, "official_valid_count": stats.get("validCount"), "total_passed": total, "total_required": 6, "totalCredit": stats.get("totalCredit"), "total_credits": stats.get("totalCredit"), "requiredCredit": stats.get("requiredCredit", 6), "all_time_stats": {"source": "official", "statistical": stats.get("statistical", {})}}
    for label, category in (("moral","德育"),("labor","劳育"),("art","美育"),("security_health","安全健康")):
        result.update({label+"_completed": counts[category], label+"_required": REQUIREMENTS[category], label+"_effective": min(counts[category], REQUIREMENTS[category])})
    result.update({"moral_courses_count": counts["德育"], "labor_courses_count": counts["劳育"], "art_courses_count": counts["美育"], "security_courses_count": counts["安全健康"]})
    all_time = {"moral": 0, "labor": 0, "art": 0, "security": 0, "source": "official"}
    tree = (stats.get("statistical") or {}).get("60|博雅课程", {}) if isinstance(stats.get("statistical"), dict) else {}
    labels = {"德育": "moral", "劳育": "labor", "美育": "art", "安全健康": "security"}
    if isinstance(tree, dict):
        for category, value in tree.items():
            key = labels.get(get_course_category({"kindName": str(category)}))
            count = value.get("completeAssessmentCount") if isinstance(value, dict) else None
            if key and not isinstance(count, bool) and str(count).isdigit():
                all_time[key] += int(count)
    all_time["total"] = sum(all_time[key] for key in ("moral", "labor", "art", "security"))
    result["all_time_stats"] = all_time
    return result


def ensure_boya_read_session(acc):
    """Reading a page must respect the worker's captcha pause and auth backoff."""
    with account_lock(acc):
        if acc.removed or acc.maintenance:
            return False
        if acc.boya_client.is_authenticated():
            return True
        if not acc.client.is_authenticated():
            return False
        return boya_scheduler._renew_session(acc)


@app.get("/api/boya/courses")
async def get_boya_courses(force: bool = False, username: Optional[str] = None, cached: bool = False):
    stale = False
    curr = resolve_account(username)
    if not curr:
        return {"status": "unauthenticated", "stale":True, "courses":[], "is_demo":False}

    # Reading a completed snapshot never waits behind a worker's network lock.
    # Fresh school actions still enforce their own authentication and guards.
    if cached and not force and curr.boya_all_courses is not None:
        authenticated = curr.boya_client.is_authenticated()
        return {"status": "success" if authenticated else "stale", "stale": not authenticated,
                "courses": enrich_pool(curr.boya_all_courses), "username": curr.username,
                "last_refresh_time": curr.boya_last_refresh_time, "is_demo": False}

    if not await asyncio.to_thread(ensure_boya_read_session, curr):
        courses = curr.boya_all_courses or []
        return {
            "status": "stale", "stale": True,
            "courses": enrich_pool(courses),
            "username": curr.username,
            "name": curr.name,
            "is_demo": False,
            "message": "博雅认证不可用，显示上次成功数据；请检查登录状态",
        }

    if force or curr.boya_all_courses is None:
        try:
            curr.boya_all_courses = await asyncio.to_thread(curr.boya_client.query_courses)
            curr.boya_last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
            add_log("info", f"【{curr.name}】博雅全量课程刷新成功，共 {len(curr.boya_all_courses)} 门课程。", username=curr.username, user_name=curr.name, category="boya")
        except Exception as e:
            stale = True
            add_log("warning", "博雅课池同步失败：" + type(e).__name__ + "，保留上次成功数据", username=curr.username, user_name=curr.name, category="boya")
            return {"status": "stale", "stale": True, "courses": enrich_pool(curr.boya_all_courses or []), "username": curr.username, "is_demo": False, "message": "课池同步失败，显示上次成功数据"}

    return {
        "status": "stale" if stale else "success",
        "stale": stale,
        "courses": enrich_pool(curr.boya_all_courses or []),
        "username": curr.username,
        "name": curr.name,
        "last_refresh_time": curr.boya_last_refresh_time,
        "is_demo": False,
    }


@app.get("/api/boya/selected")
async def get_boya_selected(force: bool = False, username: Optional[str] = None):
    stale = False
    curr = resolve_account(username)
    if not curr or not curr.boya_client.is_authenticated():
        if curr:
            enriched = enrich_selected_courses(curr.boya_selected_courses or [], curr.boya_all_courses or [])
            return {"status": "stale", "stale": True, "selected": enriched, "username": curr.username, "is_demo": False}
        selected = getattr(curr, "boya_selected_courses", None) if curr else None
        pool = getattr(curr, "boya_all_courses", None) if curr else None
        is_demo = False
        enriched = enrich_selected_courses(selected or [], pool or [])
        return {"status": "unauthenticated", "stale":True, "selected": enriched, "is_demo": is_demo}

    if force or curr.boya_selected_courses is None:
        try:
            curr.boya_selected_courses = await asyncio.to_thread(curr.boya_client.query_chosen_courses)
        except Exception as e:
            stale = True
            add_log("warning", f"【{curr.name}】获取线上已选博雅课程失败: {type(e).__name__}，呈现本地已选数据", username=curr.username, user_name=curr.name, category="boya")

    selected_list = curr.boya_selected_courses if curr.boya_selected_courses is not None else []
    all_pool = curr.boya_all_courses if curr.boya_all_courses is not None else []
    enriched = enrich_selected_courses(selected_list, all_pool)
    return {
        "status": "stale" if stale else "success",
        "stale": stale,
        "selected": enriched,
        "username": curr.username,
        "name": curr.name,
        "is_demo": False,
    }


@app.get("/api/boya/statistics")
async def get_boya_statistics(force: bool = False, username: Optional[str] = None):
    stale = False
    curr = resolve_account(username)
    if not curr or not curr.boya_client.is_authenticated():
        if curr:
            enriched = enrich_selected_courses(curr.boya_selected_courses or [], curr.boya_all_courses or [])
            return {"status": "stale", "stale": True, "statistics": compute_semester_statistics(enriched, curr.boya_statistics or {}), "username": curr.username, "is_demo": False}
        selected = getattr(curr, "boya_selected_courses", None) if curr else None
        pool = getattr(curr, "boya_all_courses", None) if curr else None
        stats = getattr(curr, "boya_statistics", None) if curr else None
        enriched = enrich_selected_courses(selected or [], pool or [])
        computed_stats = compute_semester_statistics(enriched, stats or {})
        return {"status": "unauthenticated", "stale":True, "statistics": computed_stats}

    if force or curr.boya_statistics is None:
        try:
            curr.boya_statistics = await asyncio.to_thread(curr.boya_client.query_statistics)
            boya_name = extract_real_name_from_stats(curr.boya_statistics)
            if boya_name and boya_name != curr.username and curr.name != boya_name:
                curr.name = boya_name
                sync_config()
        except Exception as e:
            stale = True
            add_log("error", f"【{curr.name}】获取博雅素养学分统计失败: {type(e).__name__}", username=curr.username, user_name=curr.name, category="boya")

    selected_list = curr.boya_selected_courses if curr.boya_selected_courses is not None else []
    all_pool = curr.boya_all_courses if curr.boya_all_courses is not None else []
    enriched = enrich_selected_courses(selected_list, all_pool)
    stats = compute_semester_statistics(enriched, curr.boya_statistics or {})
    return {
        "status": "stale" if stale else "success",
        "stale": stale,
        "statistics": stats,
        "username": curr.username,
        "name": curr.name,
    }


@app.post("/api/boya/refresh")
async def refresh_boya_data(username: Optional[str] = None):
    curr = resolve_account(username)
    if not curr:
        raise HTTPException(status_code=400, detail="无活跃账号")

    if not await asyncio.to_thread(ensure_boya_read_session, curr):
        raise HTTPException(status_code=401, detail="博雅认证未就绪；需要验证码时请重新登录，其余失败请等待退避后重试")

    try:
        curr.boya_all_courses = await asyncio.to_thread(curr.boya_client.query_courses)
        curr.boya_selected_courses = await asyncio.to_thread(curr.boya_client.query_chosen_courses)
        curr.boya_statistics = await asyncio.to_thread(curr.boya_client.query_statistics)
        curr.boya_last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
        add_log("success", f"【{curr.name}】博雅全部数据（课程、已选、学分统计）刷新成功！", username=curr.username, user_name=curr.name, category="boya")
        return {
            "status": "success",
            "courses_count": len(curr.boya_all_courses),
            "selected_count": len(curr.boya_selected_courses),
            "statistics": curr.boya_statistics,
            "last_refresh_time": curr.boya_last_refresh_time,
        }
    except Exception as e:
        add_log("error", f"【{curr.name}】博雅数据刷新失败: {type(e).__name__}", username=curr.username, user_name=curr.name, category="boya")
        raise HTTPException(status_code=500, detail="博雅数据未同步："+type(e).__name__)


async def boya_action_response(req, action):
    acc = resolve_account(req.username)
    if not acc:
        raise HTTPException(status_code=401, detail="请先登录账号")
    try:
        coordinates = None
        if action == "sign":
            if (req.lat is None) != (req.lng is None):
                raise HTTPException(status_code=422, detail="经纬度必须同时提供")
            coordinates = None if req.lat is None else (req.lat, req.lng)
        result = await asyncio.to_thread(perform_boya_action, acc, action, req.course_id, sign_type=getattr(req, "sign_type", 1), coordinates=coordinates, renew=boya_scheduler._renew_session)
        add_log("warning" if result.get("pending_verification") else "info", "博雅请求已处理；官方状态待同步。" if result.get("pending_verification") else "博雅操作状态已刷新。", username=acc.username, user_name=acc.name, category="boya")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        add_log("warning", "博雅操作暂未完成：" + type(exc).__name__, username=acc.username, user_name=acc.name, category="boya")
        safe_message = exc.message if isinstance(exc, BoyaApiError) else str(exc) if isinstance(exc, (BoyaSessionExpired, operations.OperationBusy)) else "通信未完成，写入结果可能待官方复核；请刷新官方记录，不要反复提交"
        return {"status": "error", "message": safe_message, "error_type": type(exc).__name__}

@app.post("/api/boya/select")
async def select_boya_course(req: BoyaActionRequest):
    return await boya_action_response(req, "select")

@app.post("/api/boya/drop")
async def drop_boya_course(req: BoyaActionRequest):
    return await boya_action_response(req, "drop")

@app.post("/api/boya/sign")
async def sign_boya_course(req: BoyaSignRequest):
    return await boya_action_response(req, "sign")


@app.post("/api/boya/toggle_auto")
async def toggle_boya_auto(req: BoyaToggleAutoRequest):
    acc = resolve_account(req.username)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    if req.campus is not None and req.campus not in ("北京", "杭州"):
        raise HTTPException(status_code=422, detail="请选择北京或杭州校区")
    if req.targets is not None and set(req.targets) != set(REQUIREMENTS):
        raise HTTPException(status_code=422, detail="预约目标必须包含德育、劳育、美育、安全健康")
    def update_preferences():
        with account_lock(acc):
            if acc.removed:
                raise HTTPException(status_code=409, detail="账号已移除")
            fields={"boya_auto_select":req.auto_select,"boya_auto_sign":req.auto_sign,"campus":req.campus,"boya_targets":req.targets}
            previous={key:getattr(acc,key) for key in fields}
            if req.auto_select is not None:
                acc.boya_auto_select = req.auto_select
            if req.auto_sign is not None:
                acc.boya_auto_sign = req.auto_sign
            if req.campus is not None:
                acc.campus = req.campus
            if req.targets is not None:
                acc.boya_targets = dict(req.targets)
            def restore():
                for key,value in previous.items():
                    if key in ("boya_auto_select","boya_auto_sign") and fields[key] is False:
                        continue
                    setattr(acc,key,value)
            return persist_switch(restore, stop_requested=req.auto_select is False or req.auto_sign is False)
    persisted = await asyncio.to_thread(update_preferences)
    # 铁律：自动秒抢永久仅抢支持线上自主打卡课程，彻底消除线下考勤风险
    acc.boya_require_auto_sign = True
    acc.boya_allow_offline = False

    any_boya = any(getattr(a, "boya_auto_select", False) or getattr(a, "boya_auto_sign", False) for a in accounts.values())
    if any_boya and not boya_scheduler.running:
        boya_scheduler.start(interval_seconds=60)
    elif not any_boya and boya_scheduler.running:
        boya_scheduler.stop()

    add_log(
        "info",
        f"学生 【{acc.name}】 博雅自动化配置已更新: 自动秒抢={ '开' if acc.boya_auto_select else '关' }, 自动打卡={ '开' if acc.boya_auto_sign else '关' }, 期望校区={acc.campus}",
        username=acc.username,
        user_name=acc.name,
        category="boya",
    )

    return {
        "status": "ok",
        "username": acc.username,
        "boya_auto_select": acc.boya_auto_select,
        "boya_auto_sign": acc.boya_auto_sign,
        "campus": acc.campus,
        "scheduler_running": boya_scheduler.running,
        "boya_targets": acc.boya_targets,
        "persisted": persisted,
    }


@app.get("/api/logs")
async def get_logs(username: Optional[str] = Query(None), category: Optional[str] = Query(None)):
    """支持按学生账号和业务类别（all总日志 / regular常规课程 / boya自动博雅）隔离获取日志"""
    filtered = logs_list

    # 1. 账号过滤
    if username:
        if category == "all":
            # 总日志：显示当前学生自己的全部日志，以及系统公共日志（username 为空）
            filtered = [l for l in filtered if l.get("username") == username or not l.get("username")]
        else:
            # 常规课程、自动博雅或未指定板块的纯用户过滤：严格限定该学生
            filtered = [l for l in filtered if l.get("username") == username]

    # 2. 业务板块类别过滤
    if category and category != "all":
        if category == "regular":
            # 常规课程：包含 regular 与 iclass 考勤日志
            filtered = [l for l in filtered if l.get("category", "regular") in ("regular", "iclass")]
        elif category == "boya":
            # 自动博雅：仅包含 boya 相关日志
            filtered = [l for l in filtered if l.get("category", "regular") == "boya"]
        else:
            filtered = [l for l in filtered if l.get("category", "regular") == category]

    return {"logs": filtered, "username": username, "category": category}


@app.post("/api/logs/clear")
async def clear_logs(username: Optional[str] = Query(None), category: Optional[str] = Query(None)):
    global logs_list
    if username and category and category != "all":
        cat_matches = ("regular", "iclass") if category == "regular" else (category,)
        logs_list = [
            l for l in logs_list
            if not (l.get("username") == username and l.get("category", "regular") in cat_matches)
        ]
        add_log("info", f"学生 [{username}] 的 { {'boya':'自动博雅','td':'自动TD'}.get(category,'常规课程')} 专属日志已清空。", category="system")
    elif username:
        logs_list = [l for l in logs_list if l.get("username") != username]
        add_log("info", f"学生账号 [{username}] 的全部日志已清空。", category="system")
    elif category and category != "all":
        cat_matches = ("regular", "iclass") if category == "regular" else (category,)
        logs_list = [l for l in logs_list if l.get("category", "regular") not in cat_matches]
        add_log("info", f"全系统 { {'boya':'自动博雅','td':'自动TD'}.get(category,'常规课程')} 实时运行日志已清空。", category="system")
    else:
        logs_list.clear()
        add_log("info", "全系统实时运行日志已清空。", category="system")
    return {"status": "ok"}


@app.get("/api/config")
async def get_app_config():
    curr = get_active_account()
    return {
        "active_username": active_username,
        "username": curr.username if curr else "",
        "mode": curr.mode if curr else "auto",
        "global_auto_checkin": scheduler.enabled,
        "checkin_interval": scheduler.interval_seconds,
    }


window_controller = {
    "show": None,
    "exit": None,
}


def set_window_controller(show_cb=None, exit_cb=None):
    if show_cb:
        window_controller["show"] = show_cb
    if exit_cb:
        window_controller["exit"] = exit_cb


class AutostartRequest(BaseModel):
    enabled: bool


@app.get("/api/system/autostart")
async def get_autostart():
    runtime = capabilities()
    if not runtime['autostart_supported']:
        return {'status': 'ok', 'enabled': False, 'supported': False, 'runtime': runtime}
    from core.autostart import get_autostart_status
    return {
        "status": "ok",
        "enabled": get_autostart_status(),
        "supported": True, "runtime": runtime,
    }


@app.post("/api/system/autostart")
async def update_autostart(req: AutostartRequest):
    if not capabilities()['autostart_supported']:
        raise HTTPException(status_code=409, detail="后台服务自启动由部署工具管理，网页不能修改宿主机自启动")
    from core.autostart import set_autostart, get_autostart_status
    success = await asyncio.to_thread(set_autostart, req.enabled)
    cur_status = await asyncio.to_thread(get_autostart_status)
    confirmed = success and cur_status == req.enabled
    persisted = True
    if confirmed:
        try:
            candidate={**config,"autostart":cur_status}
            save_config(candidate);config.update(candidate)
        except Exception:persisted=False
    add_log("info" if confirmed else "warning", "系统已确认开机自启状态" if confirmed else "系统未确认自启修改，保留实际查询状态")
    return {
        "status": "ok" if confirmed else "error",
        "enabled": cur_status,
        "persisted": persisted,
    }


COMMITMENT_VERSION = "2026-10-21-v1"
COMMITMENT_TEXT = (
    "本人承诺：仅将本软件用于学习相关网络知识及机制，在获取后24小时内删除；"
    "不用于真实打卡或其他滥用，遵守法律法规及校纪校规；"
    "知悉学号及操作记录可能被留存、滥用记录可能用于调查处理，并依法承担相应后果。"
)


def disclaimer_accepted():
    return (config.get("disclaimer_accepted") is True and
            config.get("disclaimer_commitment_version") == COMMITMENT_VERSION)


class DisclaimerAcceptance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agreed: StrictBool
    commitment: Annotated[str, Field(strict=True, min_length=1, max_length=1024)]
    commitment_version: Annotated[str, Field(strict=True, max_length=64)]


@app.get("/api/system/disclaimer")
async def get_disclaimer():
    return {
        "status": "ok",
        "accepted": disclaimer_accepted(),
        "commitment_text": COMMITMENT_TEXT,
        "commitment_version": COMMITMENT_VERSION,
        "version": VERSION,
    }


@app.post("/api/system/disclaimer/accept")
async def accept_disclaimer(body: DisclaimerAcceptance):
    if body.commitment_version != COMMITMENT_VERSION:
        raise HTTPException(status_code=409, detail="承诺条款已更新，请重新加载后确认")
    # Ignore only explicit spacing/line breaks, consistently with the textarea.
    spacing = str.maketrans('', '', ' \t\r\n\u3000')
    if body.agreed is not True or body.commitment.translate(spacing) != COMMITMENT_TEXT.translate(spacing):
        raise HTTPException(status_code=422, detail="请同意免责声明，并完整输入本人承诺内容")
    if disclaimer_accepted():
        return {"status": "ok", "accepted": True, "commitment_version": COMMITMENT_VERSION}
    candidate = {**config, "disclaimer_accepted": True,
                 "disclaimer_commitment_version": COMMITMENT_VERSION,
                 "disclaimer_accepted_at": china_now().isoformat()}
    try:
        save_config(candidate)
    except Exception:
        add_log("error", "免责声明确认保存失败，请重试。")
        raise HTTPException(status_code=500, detail="免责声明确认保存失败")
    config.update(candidate)
    add_log("info", "用户已同意免责声明并完成本人承诺确认。")
    return {"status": "ok", "accepted": True, "commitment_version": COMMITMENT_VERSION}


@app.post("/api/window/show")
async def show_window():
    cb = window_controller.get("show")
    if cb:
        try:
            cb()
        except Exception as e:
            logger.warning(f"Error executing window show callback: {type(e).__name__}")
    return {"status": "ok", "message": "window restored"}


@app.post("/api/exit")
async def exit_app():
    add_log("info", "接收到退出指令，正在安全关闭后台服务进程...")
    exit_cb = window_controller.get("exit")
    loop = asyncio.get_event_loop()
    def finish_exit():
        if exit_cb:
            exit_cb()
        else:
            os._exit(0)
    loop.call_later(0.3, finish_exit)
    return {"status": "exiting"}


# 挂载静态文件
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")



# ==================== 接口兼容层 (RESTful & Alias Endpoints) ====================

@app.delete("/api/accounts/{username}")
async def delete_account_rest(username: str):
    global active_username
    if username not in accounts:
        raise HTTPException(status_code=404, detail="Account not found")

    acc = accounts.pop(username)
    await dispose_account(acc)
    add_log("info", f"学生账号 【{acc.name} ({acc.username})】 已通过 RESTful 接口移除。", username=acc.username, user_name=acc.name)

    if active_username == username:
        active_username = next(iter(accounts.keys())) if accounts else None

    sync_config()
    return {"status": "ok", "active_username": active_username}


class CheckinCompatRequest(BaseModel):
    course_sched_id: Optional[str] = None
    course_id: Optional[str] = None
    username: Optional[str] = None


@app.post("/api/checkin")
async def checkin_compat(req: CheckinCompatRequest):
    cid = req.course_sched_id or req.course_id
    if not cid:
        raise HTTPException(status_code=400, detail="Course ID required")

    return await perform_signin(SigninRequest(course_id=str(cid), username=req.username))


@app.post("/api/boya/strategy")
async def boya_strategy_alias(req: BoyaToggleAutoRequest):
    return await toggle_boya_auto(req)


@app.get("/api/boya/logs")
async def get_boya_logs(username: Optional[str] = Query(None)):
    return await get_logs(username=username, category="boya")

startup_presentation = StartupPresentation()


@app.get("/")
async def serve_index(request: Request):
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        from fastapi.responses import HTMLResponse
        prefetch = 'prefetch' in (request.headers.get('sec-purpose', '') + request.headers.get('purpose', ''))
        play = startup_presentation.claim(prefetch=prefetch)
        return HTMLResponse(
            index_file.read_text(encoding='utf-8').replace('data-startup-enabled="pending"',
                                                        'data-startup-enabled="' + ('true' if play else 'false') + '"')
            .replace('data-runtime-mode="pending"', 'data-runtime-mode="' + capabilities()['mode'] + '"'),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return {"message": "BUAA Signin UI files not found"}


@app.get("/favicon.ico")
async def serve_favicon():
    fav_file = STATIC_DIR / "favicon.ico"
    if fav_file.exists():
        return FileResponse(fav_file)
    raise HTTPException(status_code=404, detail="Favicon not found")


# Isolated TD routes use the same account identities and management boundary.
from server.td_routes import install as install_td
remove_td_account = install_td(app, CONFIG_FILE, resolve_account, accounts, add_log)
from server.wechat import install as install_wechat

async def wechat_course_snapshot(username):
    """Independent read-only feed. Never enables attendance or depends on active UI."""
    from core.domain import parse_dt
    import copy
    acc=accounts.get(username)
    if not acc or acc.removed or acc.maintenance or acc.auth_requires_input:return None
    current=china_now();health=acc.regular_health
    refreshed=parse_dt(health.get('last_success'))
    if health.get('stale') or not refreshed or refreshed.date()!=current.date() or not 0<=(current-refreshed).total_seconds()<=60:
        if not acc.client.is_authenticated():
            if not acc.password or not await connect_single_account(acc):return None
        epoch=acc.auth_epoch
        try:
            classes=await acc.client.get_today_classes()
        except IclassSessionExpired:
            # Only explicit expiry may reconnect; transient network errors do not.
            if acc.password:await connect_single_account(acc)
            return None
        except Exception:
            acc.regular_health={**acc.regular_health,'stale':True}
            return None
        if accounts.get(username) is not acc or acc.removed or acc.maintenance or acc.auth_epoch!=epoch:return None
        acc.last_classes=classes;acc.last_refresh_time=china_now().isoformat(timespec='seconds')
        acc.regular_health={'stale':False,'last_success':acc.last_refresh_time,'error':None}
    if accounts.get(username) is not acc or acc.removed or acc.maintenance:return None
    return {'classes':copy.deepcopy(acc.last_classes),'semester':copy.deepcopy((acc.boya_statistics or {}).get('semesterInfo') or {})}

wechat_notifications = install_wechat(app, CONFIG_FILE, accounts, course_reader=wechat_course_snapshot)
