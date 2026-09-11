"""
BUAA 课程独立签到软件 - FastAPI 后端控制器 (支持多学生账号并发管理与分账号日志)
"""

import asyncio
import datetime
import json
import os
import pathlib
import sys
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.iclass import IclassClient
from core.scheduler import SigninScheduler
from core.boya_client import BoyaClient, BoyaApiError, BoyaSessionExpired
from core.boya_scheduler import BoyaScheduler, parse_sign_config, is_auto_select_candidate, random_point_in_radius


def resolve_config_path() -> pathlib.Path:
    """
    智能解析配置文件路径：
    1. 便携版模式优先读取 exe 所在同级目录的 config.json；
    2. 若同级目录不可写（如标准安装在 Program Files），则切换到用户 APPDATA 目录；
    3. 若 APPDATA 中尚无配置，且桌面或工作区有旧配置，自动平滑继承。
    """
    if getattr(sys, "frozen", False):
        exe_dir = pathlib.Path(sys.executable).parent
        portable_cfg = exe_dir / "config.json"
        if portable_cfg.exists():
            return portable_cfg

        if sys.platform == "darwin":
            mac_support_dir = pathlib.Path.home() / "Library" / "Application Support" / "BUAA-Signin"
            mac_support_dir.mkdir(parents=True, exist_ok=True)
            mac_cfg = mac_support_dir / "config.json"
            if mac_cfg.exists():
                return mac_cfg
            # 也可检查 .app 同级目录的便携式配置
            app_bundle_dir = exe_dir.parent.parent.parent
            if (app_bundle_dir / "config.json").exists():
                return app_bundle_dir / "config.json"
            return mac_cfg

        appdata = os.environ.get("APPDATA")
        if appdata:
            appdata_dir = pathlib.Path(appdata) / "BUAA-Signin"
            appdata_dir.mkdir(parents=True, exist_ok=True)
            appdata_cfg = appdata_dir / "config.json"
            if appdata_cfg.exists():
                return appdata_cfg

        # 测试 exe_dir 是否可写
        try:
            test_file = exe_dir / ".write_test"
            test_file.touch()
            test_file.unlink()
            return portable_cfg
        except Exception:
            if appdata:
                appdata_dir = pathlib.Path(appdata) / "BUAA-Signin"
                appdata_dir.mkdir(parents=True, exist_ok=True)
                return appdata_dir / "config.json"
            return portable_cfg
    else:
        base_dir = pathlib.Path(__file__).parent.parent
        return base_dir / "config.json"


if getattr(sys, "frozen", False):
    BUNDLE_DIR = pathlib.Path(getattr(sys, "_MEIPASS", sys.executable))
    STATIC_DIR = BUNDLE_DIR / "server" / "static"
    if not STATIC_DIR.exists():
        STATIC_DIR = pathlib.Path(sys.executable).parent / "server" / "static"
else:
    STATIC_DIR = pathlib.Path(__file__).parent / "static"

CONFIG_FILE = resolve_config_path()

# 跨模式平滑同步：若当前配置文件不存在，自动尝试从桌面项目目录或 APPDATA 互通导入
if not CONFIG_FILE.exists():
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


def load_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 兼容旧版本单账号配置
                if "accounts" not in data:
                    accounts_list = []
                    if data.get("username"):
                        accounts_list.append({
                            "username": data.get("username", ""),
                            "name": data.get("username", ""),
                            "password": data.get("password", ""),
                            "remember": data.get("remember", False),
                            "mode": data.get("mode", "auto"),
                            "auto_checkin": data.get("auto_checkin", False),
                        })
                    data = {
                        "active_username": data.get("username", ""),
                        "accounts": accounts_list,
                        "global_auto_checkin": data.get("auto_checkin", False),
                        "checkin_interval": data.get("checkin_interval", 20),
                    }
                return data
        except Exception:
            pass
    return {
        "active_username": "",
        "accounts": [],
        "global_auto_checkin": False,
        "checkin_interval": 20,
    }


def save_config(cfg: Dict[str, Any]):
    global CONFIG_FILE
    if os.environ.get("TESTING") == "1":
        return
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # 如果当前位置不可写，自动降级切换至用户数据目录写入
        if sys.platform == "darwin":
            mac_support_dir = pathlib.Path.home() / "Library" / "Application Support" / "BUAA-Signin"
            mac_support_dir.mkdir(parents=True, exist_ok=True)
            fallback_cfg = mac_support_dir / "config.json"
            try:
                with open(fallback_cfg, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                CONFIG_FILE = fallback_cfg
            except Exception:
                pass
        else:
            appdata = os.environ.get("APPDATA")
            if appdata:
                fallback_cfg = pathlib.Path(appdata) / "BUAA-Signin" / "config.json"
                fallback_cfg.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with open(fallback_cfg, "w", encoding="utf-8") as f:
                        json.dump(cfg, f, ensure_ascii=False, indent=2)
                    CONFIG_FILE = fallback_cfg
                except Exception:
                    pass
        print(f"Failed to save config: {e}")


app = FastAPI(title="BUAA Course Signin Multi-Account")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        campus: str = "北京",
    ):
        self.username = username
        self.name = name or username
        self.password = password
        self.mode = mode
        self.remember = remember
        self.auto_checkin = auto_checkin
        self.boya_auto_select = boya_auto_select
        self.boya_auto_sign = boya_auto_sign
        self.campus = campus or "北京"
        self.client = IclassClient(mode=("webvpn" if mode == "webvpn" else "direct"))
        self.boya_client = BoyaClient(mode=("webvpn" if mode == "webvpn" else "direct"))
        self.last_classes: List[Dict[str, Any]] = []
        self.last_refresh_time: Optional[str] = None
        self.boya_all_courses: List[Dict[str, Any]] = []
        self.boya_selected_courses: List[Dict[str, Any]] = []
        self.boya_statistics: Dict[str, Any] = {}
        self.boya_last_refresh_time: Optional[str] = None

    def to_dict(self, is_active: bool = False) -> Dict[str, Any]:
        return {
            "username": self.username,
            "name": self.name,
            "mode": self.mode,
            "remember": self.remember,
            "auto_checkin": self.auto_checkin,
            "boya_auto_select": self.boya_auto_select,
            "boya_auto_sign": self.boya_auto_sign,
            "campus": self.campus,
            "authenticated": self.client.is_authenticated(),
            "boya_authenticated": self.boya_client.is_authenticated(),
            "is_active": is_active,
            "course_count": len(self.last_classes),
            "signed_count": len([c for c in self.last_classes if c.get("signStatus") == 1]),
            "last_refresh_time": self.last_refresh_time,
            "boya_course_count": len(self.boya_all_courses),
            "boya_selected_count": len(self.boya_selected_courses),
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


def get_scheduler_accounts() -> List[Dict[str, Any]]:
    """返回所有启用了自动打卡且已鉴权的学生账号供后台定时巡检"""
    result = []
    for acc in accounts.values():
        if acc.auto_checkin and acc.client.is_authenticated():
            result.append({
                "username": acc.username,
                "name": acc.name,
                "client": acc.client,
            })
    return result


scheduler = SigninScheduler(get_active_accounts=get_scheduler_accounts, on_event_log=add_log)
boya_scheduler = BoyaScheduler(get_accounts_func=lambda: list(accounts.values()), add_log_func=add_log)


def sync_config():
    """将当前内存中的账号状态同步回 config.json"""
    if os.environ.get("TESTING") == "1":
        return
    accounts_data = []
    for acc in accounts.values():
        accounts_data.append({
            "username": acc.username,
            "name": acc.name,
            "password": acc.password if acc.remember else "",
            "remember": acc.remember,
            "mode": acc.mode,
            "auto_checkin": acc.auto_checkin,
            "boya_auto_select": getattr(acc, "boya_auto_select", False),
            "boya_auto_sign": getattr(acc, "boya_auto_sign", False),
            "campus": getattr(acc, "campus", "北京"),
        })
    config["active_username"] = active_username or ""
    config["accounts"] = accounts_data
    config["global_auto_checkin"] = scheduler.enabled
    config["checkin_interval"] = scheduler.interval_seconds
    save_config(config)


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
    mode: str  # "auto", "direct", "webvpn"


class SigninRequest(BaseModel):
    course_id: str
    username: Optional[str] = None


class AutoCheckinRequest(BaseModel):
    enabled: bool
    interval: Optional[int] = 20


class BoyaActionRequest(BaseModel):
    course_id: int
    username: Optional[str] = None


class BoyaSignRequest(BaseModel):
    course_id: int
    sign_type: int = 1  # 1 为签到, 2 为签退
    lat: Optional[float] = None
    lng: Optional[float] = None
    username: Optional[str] = None


class BoyaToggleAutoRequest(BaseModel):
    auto_select: Optional[bool] = None
    auto_sign: Optional[bool] = None
    campus: Optional[str] = None
    username: Optional[str] = None


@app.on_event("startup")
async def on_startup():
    add_log("info", "BUAA 独立课程签到助手 (多学生并发管理版) 服务已启动。")
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
            campus=item.get("campus", "北京"),
        )
        accounts[uname] = acc

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


async def connect_single_account(acc: AccountState) -> bool:
    add_log("info", f"正在为学生账号 [{acc.name or acc.username}] 建立连接...", username=acc.username, user_name=acc.name)
    modes_to_try = ["direct", "webvpn"] if acc.mode in ("auto", "direct") else [acc.mode]

    for attempt_mode in modes_to_try:
        acc.client.mode = attempt_mode
        try:
            res = await acc.client.login_sso(username=acc.username, password=acc.password)
            if res.get("status") == "success":
                real_name = res.get("user", {}).get("name")
                if real_name:
                    acc.name = real_name

                iclass_ok = await acc.client.login_iclass()
                if iclass_ok:
                    add_log("success", f"学生 [{acc.name}] 登录及常规签到鉴权成功！({ '校园网直连' if attempt_mode == 'direct' else 'WebVPN 外网' })", username=acc.username, user_name=acc.name)
                    # 预拉取一次今日课程
                    try:
                        classes = await acc.client.get_today_classes()
                        acc.last_classes = classes
                        acc.last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
                    except Exception:
                        pass

                    # 尝试同步博雅系统的访问授权与课程数据
                    try:
                        acc.boya_client.mode = attempt_mode
                        acc.boya_client.sync_cookies_from(acc.client.client.cookies)
                        acc.boya_client.acquire_token()
                        acc.boya_all_courses = acc.boya_client.query_courses(max_pages=5)
                        acc.boya_selected_courses = acc.boya_client.query_chosen_courses()
                        acc.boya_statistics = acc.boya_client.query_statistics()
                        acc.boya_last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
                        add_log("success", f"学生 [{acc.name}] 博雅系统授权与排课同步成功！", username=acc.username, user_name=acc.name, category="boya")
                    except Exception as be:
                        logger.debug(f"Boya auto sync during connect: {be}")

                    sync_config()
                    return True
                else:
                    if attempt_mode != modes_to_try[-1]:
                        await acc.client.close()
                        acc.client = IclassClient(mode="webvpn")
                        continue
            elif res.get("status") == "captcha_required":
                add_log("warning", f"学生 [{acc.name}] 自动登录被阻断（需要图形验证码），请在界面手动登录。", username=acc.username, user_name=acc.name)
                return False
        except Exception as e:
            if attempt_mode != modes_to_try[-1]:
                await acc.client.close()
                acc.client = IclassClient(mode="webvpn")
                continue
            add_log("error", f"学生 [{acc.name}] 连接异常: {e}", username=acc.username, user_name=acc.name)
            return False

    return False


@app.get("/api/status")
async def get_status():
    curr = get_active_account()
    mode = curr.mode if curr else config.get("default_mode", "direct")
    return {
        "authenticated": curr.client.is_authenticated() if curr else False,
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

    active_username = req.username
    sync_config()
    target_acc = accounts[active_username]
    add_log("info", f"当前操作视图已切换至学生: 【{target_acc.name} ({target_acc.username})】", username=target_acc.username, user_name=target_acc.name)

    return {
        "status": "ok",
        "active_account": target_acc.to_dict(is_active=True),
    }


@app.post("/api/accounts/toggle_auto")
async def toggle_account_auto_checkin(req: ToggleAutoRequest):
    if req.username not in accounts:
        raise HTTPException(status_code=404, detail="Account not found")

    acc = accounts[req.username]
    acc.auto_checkin = req.enabled
    sync_config()
    add_log(
        "info",
        f"学生 【{acc.name}】 的自动签到开关已{'开启' if req.enabled else '关闭'}",
        username=acc.username,
        user_name=acc.name,
    )
    return {"status": "ok", "username": acc.username, "auto_checkin": acc.auto_checkin}


@app.post("/api/accounts/remove")
async def remove_account(req: RemoveAccountRequest):
    global active_username
    if req.username not in accounts:
        raise HTTPException(status_code=404, detail="Account not found")

    acc = accounts.pop(req.username)
    await acc.client.close()
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

    config["default_mode"] = new_mode
    curr = get_active_account()
    if curr:
        curr.mode = new_mode
        if new_mode in ("direct", "webvpn"):
            curr.client.mode = new_mode
        add_log(
            "info",
            f"学生 【{curr.name}】 连接模式已切换为: {new_mode}",
            username=curr.username,
            user_name=curr.name,
        )
    else:
        add_log("info", f"系统默认接入模式已切换为: { '校园网直连' if new_mode == 'direct' else ('WebVPN 外网' if new_mode == 'webvpn' else '智能自动') }")

    sync_config()
    return {"status": "ok", "mode": new_mode}


@app.post("/api/login")
async def login(req: LoginRequest):
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

        res = await acc.client.login_sso(
            username=req.username,
            password=req.password,
            captcha=req.captcha or "",
            captcha_id=req.captcha_id or "",
        )

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

        # 接入 iclass
        add_log("info", f"正在接入 iclass 课堂签到系统 ({'校园网直连' if attempt_mode == 'direct' else 'WebVPN 外网'})...", username=acc.username, user_name=acc.name)
        iclass_ok = await acc.client.login_iclass()
        if iclass_ok:
            add_log("success", f"【{acc.name}】iclass 课堂签到系统接入成功！", username=acc.username, user_name=acc.name)
            active_username = acc.username

            # 预加载今日课程
            try:
                classes = await acc.client.get_today_classes()
                acc.last_classes = classes
                acc.last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
            except Exception:
                pass

            sync_config()
            return {
                "status": "success",
                "user": {"name": acc.name, "schoolid": acc.username},
                "mode": attempt_mode,
            }
        else:
            if attempt_mode != modes_to_try[-1]:
                add_log("warning", f"【{acc.name}】直连校内服务不可达或超时，正在自动切换至 WebVPN 外网通道重试...", username=acc.username, user_name=acc.name)
                await acc.client.close()
                acc.client = IclassClient(mode="webvpn")
                continue
            else:
                err_msg = acc.client.last_error or "iclass 鉴权失败"
                add_log("error", f"【{acc.name}】iclass 签到系统接入失败: {err_msg}", username=acc.username, user_name=acc.name)
                return {"status": "partial", "message": f"统一认证成功，但接入课堂签到系统失败: {err_msg}", "user": res.get("user")}


@app.post("/api/logout")
async def logout():
    """退出当前活跃账号"""
    curr = get_active_account()
    if not curr:
        return {"status": "ok"}

    global active_username
    username = curr.username
    acc = accounts.pop(username, None)
    if acc:
        await acc.client.close()
        add_log("info", f"学生账号 【{acc.name}】 已退出登录。", username=acc.username, user_name=acc.name)

    active_username = next(iter(accounts.keys())) if accounts else None
    sync_config()
    return {"status": "ok", "active_username": active_username}


@app.get("/api/classes")
async def get_today_classes():
    curr = get_active_account()
    if not curr or not curr.client.is_authenticated():
        return {"status": "unauthenticated", "classes": []}

    try:
        classes = await curr.client.get_today_classes()
        curr.last_classes = classes
        curr.last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
        add_log("info", f"【{curr.name}】今日课表刷新完成，共 {len(classes)} 门课。", username=curr.username, user_name=curr.name)
        return {"status": "success", "classes": classes, "username": curr.username, "name": curr.name}
    except Exception as e:
        add_log("error", f"【{curr.name}】获取排课列表失败: {e}", username=curr.username, user_name=curr.name)
        return {"status": "error", "message": str(e), "classes": curr.last_classes}


@app.post("/api/signin")
async def perform_signin(req: SigninRequest):
    if not req.course_id:
        raise HTTPException(status_code=400, detail="Course ID required")

    # 指定账号或当前活跃账号
    if req.username and req.username in accounts:
        target_acc = accounts[req.username]
    else:
        target_acc = get_active_account()

    if not target_acc or not target_acc.client.is_authenticated():
        raise HTTPException(status_code=401, detail="Account not authenticated")

    add_log(
        "info",
        f"正在为学生 【{target_acc.name}】 提交排课 ID [{req.course_id}] 的打卡签到...",
        username=target_acc.username,
        user_name=target_acc.name,
    )
    success, msg = await target_acc.client.perform_signin(req.course_id)
    if success:
        add_log("success", f"【{target_acc.name}】排课 [{req.course_id}] 签到成功: {msg}", username=target_acc.username, user_name=target_acc.name)
    else:
        add_log("warning", f"【{target_acc.name}】排课 [{req.course_id}] 签到反馈: {msg}", username=target_acc.username, user_name=target_acc.name)

    return {"success": success, "message": msg}


@app.post("/api/auto_checkin")
async def toggle_global_auto_checkin(req: AutoCheckinRequest):
    interval = req.interval or 20
    if req.enabled:
        scheduler.start(interval_seconds=interval)
    else:
        scheduler.stop()

    sync_config()
    return {"enabled": scheduler.enabled, "interval": scheduler.interval_seconds}


@app.get("/api/boya/status")
async def get_boya_status():
    curr = get_active_account()
    if not curr:
        return {"authenticated": False, "scheduler_running": boya_scheduler.running}
    return {
        "authenticated": curr.boya_client.is_authenticated(),
        "scheduler_running": boya_scheduler.running,
        "boya_auto_select": getattr(curr, "boya_auto_select", False),
        "boya_auto_sign": getattr(curr, "boya_auto_sign", False),
        "campus": getattr(curr, "campus", "北京"),
        "last_refresh_time": getattr(curr, "boya_last_refresh_time", ""),
        "courses_count": len(getattr(curr, "boya_all_courses", [])),
        "selected_count": len(getattr(curr, "boya_selected_courses", [])),
        "statistics": getattr(curr, "boya_statistics", {}),
    }



# 真实北航博雅示范课程库（严格分为 4 大类：美育、劳育、国家安全、德育）
DEMO_BOYA_COURSES = [
    {
        "id": 7001,
        "courseId": 7001,
        "courseName": "航空航天艺术鉴赏与交响乐之美",
        "courseKind": "美育",
        "kindName": "美育",
        "courseType": "美育",
        "speaker": "中央音乐学院特聘教授",
        "teacherName": "中央音乐学院特聘教授",
        "coursePosition": "沙河校区咏曼剧场",
        "courseAddress": "沙河校区咏曼剧场",
        "courseStartDate": "2026-09-18",
        "courseStartTime": "19:00",
        "courseEndDate": "2026-09-18",
        "courseEndTime": "21:00",
        "courseMaxCount": 180,
        "courseCurrentCount": 75,
        "courseMaxNum": 180,
        "courseCurrentNum": 75,
        "courseSignConfig": '{"signPointList":[{"signLat":39.9822,"signLng":116.3475,"signRadius":60}]}',
    },
    {
        "id": 7002,
        "courseId": 7002,
        "courseName": "中国传统水墨意境与经典书法鉴赏",
        "courseKind": "美育",
        "kindName": "美育",
        "courseType": "美育",
        "speaker": "人文艺术学院名师",
        "teacherName": "人文艺术学院名师",
        "coursePosition": "学院路校区人文讲堂",
        "courseAddress": "学院路校区人文讲堂",
        "courseStartDate": "2026-09-19",
        "courseStartTime": "14:30",
        "courseEndDate": "2026-09-19",
        "courseEndTime": "16:30",
        "courseMaxCount": 60,
        "courseCurrentCount": 58,
        "courseMaxNum": 60,
        "courseCurrentNum": 58,
        "courseSignConfig": '{"signPointList":[{"signLat":39.9815,"signLng":116.3482,"signRadius":40}]}',
    },
    {
        "id": 7003,
        "courseId": 7003,
        "courseName": "智能制造与空天机械工程劳动实践",
        "courseKind": "劳育",
        "kindName": "劳育",
        "courseType": "劳育",
        "speaker": "工训中心高级工程师",
        "teacherName": "工训中心高级工程师",
        "coursePosition": "沙河校区工程训练中心201",
        "courseAddress": "沙河校区工程训练中心201",
        "courseStartDate": "2026-09-20",
        "courseStartTime": "09:00",
        "courseEndDate": "2026-09-20",
        "courseEndTime": "11:30",
        "courseMaxCount": 45,
        "courseCurrentCount": 30,
        "courseMaxNum": 45,
        "courseCurrentNum": 30,
        "courseSignConfig": '{"signPointList":[{"signLat":39.9830,"signLng":116.3460,"signRadius":50}]}',
    },
    {
        "id": 7004,
        "courseId": 7004,
        "courseName": "现代高校实验室安全规程与劳动素养",
        "courseKind": "劳育",
        "kindName": "劳育",
        "courseType": "劳育",
        "speaker": "资产处特约专家",
        "teacherName": "资产处特约专家",
        "coursePosition": "学院路校区三号楼105",
        "courseAddress": "学院路校区三号楼105",
        "courseStartDate": "2026-09-21",
        "courseStartTime": "15:00",
        "courseEndDate": "2026-09-21",
        "courseEndTime": "17:00",
        "courseMaxCount": 120,
        "courseCurrentCount": 110,
        "courseMaxNum": 120,
        "courseCurrentNum": 110,
        "courseSignConfig": '{"signPointList":[{"signLat":39.9818,"signLng":116.3470,"signRadius":50}]}',
    },
    {
        "id": 7005,
        "courseId": 7005,
        "courseName": "总体国家安全观与大国空天战略博弈",
        "courseKind": "国家安全",
        "kindName": "国家安全",
        "courseType": "国家安全",
        "speaker": "国防战略研究所教授",
        "teacherName": "国防战略研究所教授",
        "coursePosition": "学院路校区晨兴音乐厅",
        "courseAddress": "学院路校区晨兴音乐厅",
        "courseStartDate": "2026-09-22",
        "courseStartTime": "19:00",
        "courseEndDate": "2026-09-22",
        "courseEndTime": "21:00",
        "courseMaxCount": 300,
        "courseCurrentCount": 140,
        "courseMaxNum": 300,
        "courseCurrentNum": 140,
        "courseSignConfig": '{"signPointList":[{"signLat":39.9825,"signLng":116.3490,"signRadius":80}]}',
    },
    {
        "id": 7006,
        "courseId": 7006,
        "courseName": "关键信息基础设施网络空间安全防御",
        "courseKind": "国家安全",
        "kindName": "国家安全",
        "courseType": "国家安全",
        "speaker": "网络空间安全学院学术带头人",
        "teacherName": "网络空间安全学院学术带头人",
        "coursePosition": "沙河校区J3-205",
        "courseAddress": "沙河校区J3-205",
        "courseStartDate": "2026-09-23",
        "courseStartTime": "14:00",
        "courseEndDate": "2026-09-23",
        "courseEndTime": "16:00",
        "courseMaxCount": 80,
        "courseCurrentCount": 78,
        "courseMaxNum": 80,
        "courseCurrentNum": 78,
        "courseSignConfig": '{"signPointList":[{"signLat":39.9840,"signLng":116.3465,"signRadius":50}]}',
    },
    {
        "id": 7007,
        "courseId": 7007,
        "courseName": "空天报国志：北航建校精神与科学家传承",
        "courseKind": "德育",
        "kindName": "德育",
        "courseType": "德育",
        "speaker": "北航老航空专家宣讲团",
        "teacherName": "北航老航空专家宣讲团",
        "coursePosition": "沙河校区J1-101",
        "courseAddress": "沙河校区J1-101",
        "courseStartDate": "2026-09-24",
        "courseStartTime": "15:30",
        "courseEndDate": "2026-09-24",
        "courseEndTime": "17:30",
        "courseMaxCount": 150,
        "courseCurrentCount": 60,
        "courseMaxNum": 150,
        "courseCurrentNum": 60,
        "courseSignConfig": '{"signPointList":[{"signLat":39.9835,"signLng":116.3470,"signRadius":50}]}',
    },
    {
        "id": 7008,
        "courseId": 7008,
        "courseName": "新时代青年道德修养与学术诚信准则",
        "courseKind": "德育",
        "kindName": "德育",
        "courseType": "德育",
        "speaker": "马克思主义学院骨干名师",
        "teacherName": "马克思主义学院骨干名师",
        "coursePosition": "学院路校区主楼北翼",
        "courseAddress": "学院路校区主楼北翼",
        "courseStartDate": "2026-09-25",
        "courseStartTime": "16:00",
        "courseEndDate": "2026-09-25",
        "courseEndTime": "18:00",
        "courseMaxCount": 100,
        "courseCurrentCount": 40,
        "courseMaxNum": 100,
        "courseCurrentNum": 40,
        "courseSignConfig": '{"signPointList":[{"signLat":39.9810,"signLng":116.3475,"signRadius":40}]}',
    },
    {
        "id": 7009,
        "courseId": 7009,
        "courseName": "传统金石传拓技艺非遗现场实操工坊",
        "courseKind": "美育",
        "kindName": "美育",
        "courseType": "美育",
        "speaker": "国家级非物质文化遗产传承人",
        "teacherName": "国家级非物质文化遗产传承人",
        "coursePosition": "沙河校区实训楼B座",
        "courseAddress": "沙河校区实训楼B座",
        "courseStartDate": "2026-09-26",
        "courseStartTime": "14:00",
        "courseEndDate": "2026-09-26",
        "courseEndTime": "17:00",
        "courseMaxCount": 30,
        "courseCurrentCount": 30,
        "courseMaxNum": 30,
        "courseCurrentNum": 30,
        "courseSignConfig": "",  # 线下人工核验课：无 signPointList，不可自动选
    },
    {
        "id": 7010,
        "courseId": 7010,
        "courseName": "中法航空工程与跨文化美学交流",
        "courseKind": "美育",
        "kindName": "美育",
        "courseType": "美育",
        "speaker": "中法联合学院客座教授",
        "teacherName": "中法联合学院客座教授",
        "coursePosition": "杭州校区1号教学楼",
        "courseAddress": "杭州校区1号教学楼",
        "courseStartDate": "2026-09-27",
        "courseStartTime": "15:00",
        "courseEndDate": "2026-09-27",
        "courseEndTime": "17:00",
        "courseMaxCount": 50,
        "courseCurrentCount": 15,
        "courseMaxNum": 50,
        "courseCurrentNum": 15,
        "courseSignConfig": '{"signPointList":[{"signLat":30.2741,"signLng":120.1551,"signRadius":50}]}',
    },
]

DEMO_BOYA_SELECTED = [
    {
        "id": 7007,
        "chosenCourseId": 9901,
        "courseId": 7007,
        "courseName": "空天报国志：北航建校精神与科学家传承",
        "courseKind": "德育",
        "kindName": "德育",
        "courseType": "德育",
        "speaker": "北航老航空专家宣讲团",
        "teacherName": "北航老航空专家宣讲团",
        "coursePosition": "沙河校区J1-101",
        "courseAddress": "沙河校区J1-101",
        "courseStartDate": "2026-09-24",
        "courseStartTime": "15:30",
        "courseEndDate": "2026-09-24",
        "courseEndTime": "17:30",
        "selected": True,
        "status": "进行中",
        "courseSignConfig": '{"signPointList":[{"signLat":39.9835,"signLng":116.3470,"signRadius":50}]}',
    },
    {
        "id": 7001,
        "chosenCourseId": 9801,
        "courseId": 7001,
        "courseName": "航空航天艺术鉴赏与交响乐之美",
        "courseKind": "美育",
        "kindName": "美育",
        "courseType": "美育",
        "speaker": "中央音乐学院特聘教授",
        "teacherName": "中央音乐学院特聘教授",
        "coursePosition": "沙河校区咏曼剧场",
        "courseAddress": "沙河校区咏曼剧场",
        "courseStartDate": "2026-03-15",
        "courseStartTime": "19:00",
        "courseEndDate": "2026-03-15",
        "courseEndTime": "21:00",
        "selected": True,
        "status": "已结课",
        "courseSignConfig": '{"signPointList":[{"signLat":39.9822,"signLng":116.3475,"signRadius":60}]}',
    }
]

DEMO_BOYA_STATISTICS = {
    "total_credits": 2.0,
    "totalCredit": 2.0,
    "total_required": 4.0,
    "requiredCredit": 4.0,
    "art_courses_count": 1,
    "labor_courses_count": 0,
    "security_courses_count": 0,
    "moral_courses_count": 1,
    "total_courses_count": 2,
    "totalCount": 2,
}

@app.get("/api/boya/courses")
async def get_boya_courses(force: bool = False):
    curr = get_active_account()
    if not curr:
        return {"status": "success", "courses": DEMO_BOYA_COURSES, "is_demo": True}

    if not curr.boya_client.is_authenticated() and curr.client.is_authenticated():
        try:
            curr.boya_client.sync_cookies_from(curr.client.client.cookies)
            curr.boya_client.acquire_token()
        except Exception as e:
            logger.debug(f"Boya token acquire failed: {e}")

    if not curr.boya_client.is_authenticated():
        courses = curr.boya_all_courses if curr.boya_all_courses else DEMO_BOYA_COURSES
        return {
            "status": "success",
            "courses": courses,
            "username": curr.username,
            "name": curr.name,
            "is_demo": not bool(curr.boya_all_courses),
            "message": "离线预载模式，登录北航统一认证后自动同步实时选课池",
        }

    if force or not curr.boya_all_courses:
        try:
            curr.boya_all_courses = curr.boya_client.query_courses(max_pages=5)
            curr.boya_last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
            add_log("info", f"【{curr.name}】博雅全量课程刷新成功，共 {len(curr.boya_all_courses)} 门课程。", username=curr.username, user_name=curr.name, category="boya")
        except Exception as e:
            add_log("warning", f"【{curr.name}】获取博雅线上课程列表失败: {e}，启用预载课程池展示", username=curr.username, user_name=curr.name, category="boya")
            courses = curr.boya_all_courses if curr.boya_all_courses else DEMO_BOYA_COURSES
            return {"status": "success", "courses": courses, "is_demo": True, "message": str(e)}

    return {
        "status": "success",
        "courses": curr.boya_all_courses if curr.boya_all_courses else DEMO_BOYA_COURSES,
        "username": curr.username,
        "name": curr.name,
        "last_refresh_time": curr.boya_last_refresh_time,
        "is_demo": not bool(curr.boya_all_courses),
    }


@app.get("/api/boya/selected")
async def get_boya_selected(force: bool = False):
    curr = get_active_account()
    if not curr or not curr.boya_client.is_authenticated():
        selected = getattr(curr, "boya_selected_courses", []) if curr else DEMO_BOYA_SELECTED
        return {"status": "success", "selected": selected or DEMO_BOYA_SELECTED, "is_demo": not bool(getattr(curr, "boya_selected_courses", []))}

    if force or not curr.boya_selected_courses:
        try:
            curr.boya_selected_courses = curr.boya_client.query_chosen_courses()
        except Exception as e:
            add_log("warning", f"【{curr.name}】获取线上已选博雅课程失败: {e}，呈现本地已选数据", username=curr.username, user_name=curr.name, category="boya")

    return {
        "status": "success",
        "selected": curr.boya_selected_courses if curr.boya_selected_courses else DEMO_BOYA_SELECTED,
        "username": curr.username,
        "name": curr.name,
        "is_demo": not bool(curr.boya_selected_courses),
    }


@app.get("/api/boya/statistics")
async def get_boya_statistics(force: bool = False):
    curr = get_active_account()
    if not curr or not curr.boya_client.is_authenticated():
        stats = getattr(curr, "boya_statistics", {}) if curr else DEMO_BOYA_STATISTICS
        return {"status": "success", "statistics": stats or DEMO_BOYA_STATISTICS}

    if force or not curr.boya_statistics:
        try:
            curr.boya_statistics = curr.boya_client.query_statistics()
        except Exception as e:
            pass

    return {
        "status": "success",
        "statistics": curr.boya_statistics if curr.boya_statistics else DEMO_BOYA_STATISTICS,
        "username": curr.username,
        "name": curr.name,
    }


@app.post("/api/boya/refresh")
async def refresh_boya_data():
    curr = get_active_account()
    if not curr:
        raise HTTPException(status_code=400, detail="无活跃账号")

    if not curr.boya_client.is_authenticated() and curr.client.is_authenticated():
        try:
            curr.boya_client.sync_cookies_from(curr.client.client.cookies)
            curr.boya_client.acquire_token()
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"博雅身份鉴权失败: {e}")

    if not curr.boya_client.is_authenticated():
        raise HTTPException(status_code=401, detail="博雅未登录鉴权")

    try:
        curr.boya_all_courses = curr.boya_client.query_courses(max_pages=5)
        curr.boya_selected_courses = curr.boya_client.query_chosen_courses()
        curr.boya_statistics = curr.boya_client.query_statistics()
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
        add_log("error", f"【{curr.name}】博雅数据刷新失败: {e}", username=curr.username, user_name=curr.name, category="boya")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/boya/select")
async def select_boya_course(req: BoyaActionRequest):
    acc = accounts.get(req.username) if req.username else get_active_account()
    if not acc or not acc.boya_client.is_authenticated():
        raise HTTPException(status_code=401, detail="博雅未登录鉴权")

    try:
        res = acc.boya_client.select_course(req.course_id)
        add_log("success", f"【{acc.name}】博雅课程 [ID:{req.course_id}] 抢选成功！", username=acc.username, user_name=acc.name, category="boya")
        try:
            acc.boya_selected_courses = acc.boya_client.query_chosen_courses()
        except Exception:
            pass
        return {"status": "success", "result": res}
    except Exception as e:
        add_log("warning", f"【{acc.name}】博雅选课 [ID:{req.course_id}] 反馈: {e}", username=acc.username, user_name=acc.name, category="boya")
        return {"status": "error", "message": str(e)}


@app.post("/api/boya/drop")
async def drop_boya_course(req: BoyaActionRequest):
    acc = accounts.get(req.username) if req.username else get_active_account()
    if not acc or not acc.boya_client.is_authenticated():
        raise HTTPException(status_code=401, detail="博雅未登录鉴权")

    try:
        chosen_id = req.course_id
        for c in getattr(acc, "boya_selected_courses", []):
            if (c.get("id") == req.course_id or c.get("courseId") == req.course_id) and c.get("chosenCourseId"):
                chosen_id = c["chosenCourseId"]
                break
        res = acc.boya_client.drop_course(chosen_id)
        add_log("info", f"【{acc.name}】博雅课程 [选课ID:{chosen_id}] 已退选成功。", username=acc.username, user_name=acc.name, category="boya")
        try:
            acc.boya_selected_courses = acc.boya_client.query_chosen_courses()
        except Exception:
            pass
        return {"status": "success", "result": res}
    except Exception as e:
        add_log("warning", f"【{acc.name}】博雅退课 [ID:{req.course_id}] 反馈: {e}", username=acc.username, user_name=acc.name, category="boya")
        return {"status": "error", "message": str(e)}


@app.post("/api/boya/sign")
async def sign_boya_course(req: BoyaSignRequest):
    acc = accounts.get(req.username) if req.username else get_active_account()
    if not acc or not acc.boya_client.is_authenticated():
        raise HTTPException(status_code=401, detail="博雅未登录鉴权")

    course = None
    for c in getattr(acc, "boya_selected_courses", []) + getattr(acc, "boya_all_courses", []):
        if c.get("id") == req.course_id or c.get("courseId") == req.course_id:
            course = c
            break

    lat, lng = req.lat, req.lng
    if lat is None or lng is None:
        cfg = parse_sign_config(course.get("courseSignConfig") if course else {})
        pts = cfg.get("signPointList") or []
        if pts:
            ref = pts[-1]
            base_lat = float(ref.get("lat") or ref.get("signLat") or 39.9822)
            base_lng = float(ref.get("lng") or ref.get("signLng") or 116.3475)
            rad = float(ref.get("radius") or ref.get("signRadius") or 20)
            lat, lng = random_point_in_radius(base_lat, base_lng, rad)
        else:
            lat, lng = 39.9822, 116.3475

    action_text = "签退" if req.sign_type == 2 else "签到"
    try:
        res = acc.boya_client.sign_course(req.course_id, lat=lat, lng=lng, sign_type=req.sign_type)
        add_log("success", f"【{acc.name}】博雅课程 [ID:{req.course_id}] 手动{action_text}成功！微扰定位坐标: ({lat}, {lng})", username=acc.username, user_name=acc.name, category="boya")
        return {"status": "success", "result": res}
    except Exception as e:
        add_log("warning", f"【{acc.name}】博雅课程 [ID:{req.course_id}] 手动{action_text}反馈: {e}", username=acc.username, user_name=acc.name, category="boya")
        return {"status": "error", "message": str(e)}


@app.post("/api/boya/toggle_auto")
async def toggle_boya_auto(req: BoyaToggleAutoRequest):
    acc = accounts.get(req.username) if req.username else get_active_account()
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    if req.auto_select is not None:
        acc.boya_auto_select = req.auto_select
    if req.auto_sign is not None:
        acc.boya_auto_sign = req.auto_sign
    if req.campus is not None:
        acc.campus = req.campus

    sync_config()

    any_boya = any(getattr(a, "boya_auto_select", False) or getattr(a, "boya_auto_sign", False) for a in accounts.values())
    if any_boya and not boya_scheduler.running:
        boya_scheduler.start(interval_seconds=60)
    elif not any_boya and boya_scheduler.running:
        boya_scheduler.stop()

    add_log(
        "info",
        f"学生 【{acc.name}】 博雅自动化配置已更新: 自动抢课={ '开' if acc.boya_auto_select else '关' }, 自动签到={ '开' if acc.boya_auto_sign else '关' }, 期望校区={acc.campus}",
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
    }


@app.get("/api/logs")
async def get_logs(username: Optional[str] = Query(None), category: Optional[str] = Query(None)):
    """支持按学生账号和业务类别（regular常规课程 / boya博雅课程）隔离获取日志"""
    filtered = logs_list
    if username:
        filtered = [l for l in filtered if l.get("username") == username]
    if category:
        filtered = [l for l in filtered if l.get("category", "regular") == category]
    return {"logs": filtered, "username": username, "category": category}


@app.post("/api/logs/clear")
async def clear_logs(username: Optional[str] = Query(None), category: Optional[str] = Query(None)):
    global logs_list
    if username and category:
        logs_list = [l for l in logs_list if not (l.get("username") == username and l.get("category", "regular") == category)]
        add_log("info", f"学生 [{username}] 的 { '博雅' if category == 'boya' else '常规' } 专属日志已清空。", category=category)
    elif username:
        logs_list = [l for l in logs_list if l.get("username") != username]
        add_log("info", f"学生账号 [{username}] 的全部日志已清空。")
    elif category:
        logs_list = [l for l in logs_list if l.get("category", "regular") != category]
        add_log("info", f"全系统 { '博雅' if category == 'boya' else '常规' } 实时运行日志已清空。", category=category)
    else:
        logs_list.clear()
        add_log("info", "全系统实时运行日志已清空。")
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
    from core.autostart import get_autostart_status
    return {
        "status": "ok",
        "enabled": get_autostart_status(),
    }


@app.post("/api/system/autostart")
async def update_autostart(req: AutostartRequest):
    from core.autostart import set_autostart, get_autostart_status
    success = set_autostart(req.enabled)
    config["autostart"] = req.enabled
    save_config(config)
    add_log("info", f"开机自启动配置已更新为: {'已启用' if req.enabled else '已禁用'}")
    cur_status = get_autostart_status()
    final_enabled = cur_status if success else bool(req.enabled)
    return {
        "status": "ok",
        "enabled": final_enabled,
    }


@app.get("/api/system/disclaimer")
async def get_disclaimer():
    return {
        "status": "ok",
        "accepted": bool(config.get("disclaimer_accepted", False)),
        "version": "1.2.0",
    }


@app.post("/api/system/disclaimer/accept")
async def accept_disclaimer():
    config["disclaimer_accepted"] = True
    save_config(config)
    add_log("info", "用户已阅读并签署同意免责声明与使用条款。")
    return {"status": "ok", "accepted": True}


@app.post("/api/window/show")
async def show_window():
    cb = window_controller.get("show")
    if cb:
        try:
            cb()
        except Exception as e:
            logger.warning(f"Error executing window show callback: {e}")
    return {"status": "ok", "message": "window restored"}


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "version": "1.2.0",
        "active_username": active_username,
        "accounts_count": len(accounts),
    }


@app.post("/api/exit")
async def exit_app():
    add_log("info", "接收到退出指令，正在安全关闭后台服务进程...")
    exit_cb = window_controller.get("exit")
    if exit_cb:
        try:
            exit_cb()
        except Exception:
            pass
    loop = asyncio.get_event_loop()
    loop.call_later(0.3, lambda: os._exit(0))
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
    await acc.client.close()
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

@app.get("/")
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(
            index_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return {"message": "BUAA Signin UI files not found"}

