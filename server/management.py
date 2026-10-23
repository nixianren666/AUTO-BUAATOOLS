"""Same-origin management sessions for desktop and explicit remote deployments."""
import ipaddress
import asyncio
import json
import os
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic import Field
from server.presentation import capabilities
from core.management_store import ManagementStore

def install(app):
    sessions = {}
    attempts = defaultdict(deque)
    password = os.environ.get("BUAA_ADMIN_PASSWORD", "")
    store = ManagementStore()
    hashing = asyncio.Semaphore(2)
    headless_setup = os.environ.get('BUAA_RUNTIME_MODE') == 'headless'
    # A malformed private store fails startup rather than opening the service.
    store.read()
    allowed = {"127.0.0.1", "localhost", "::1"}
    allowed.update(x.strip().lower() for x in os.environ.get("BUAA_ALLOWED_HOSTS", "").split(",") if x.strip())
    if os.environ.get("TESTING") == "1":
        allowed.add("testserver")

    def local(request):
        try:
            return ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            return os.environ.get("TESTING") == "1" and request.client.host == "testclient"

    def response_session(request):
        stamp = time.monotonic()
        for key, value in list(sessions.items()):
            if stamp - value[1] > 86400:
                sessions.pop(key, None)
        if len(sessions) >= 128:
            return JSONResponse({"detail": "管理会话数量已达上限"}, status_code=429)
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sessions[sid] = (csrf, stamp)
        result = JSONResponse({"csrf": csrf, "runtime": capabilities()})
        result.set_cookie("buaa_session", sid, httponly=True, samesite="strict", secure=request.url.scheme == "https", max_age=86400)
        result.headers["Cache-Control"] = "no-store"
        return result

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        host = request.headers.get("host", "")
        try:
            parsed = urlsplit("//" + host)
            safe_host = parsed.hostname in allowed and parsed.username is None and parsed.password is None and parsed.path == ""
            _ = parsed.port
        except ValueError:
            safe_host = False
        if not safe_host:
            return JSONResponse({"detail": "不可信管理主机"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != f"{request.url.scheme}://{host}":
            return JSONResponse({"detail": "拒绝跨站管理请求"}, status_code=403)
        public = (request.url.path == "/api/health" or
                  request.url.path == "/api/session" and request.method in ("GET", "POST") or
                  request.url.path in ('/api/management/setup', '/api/management/reset') and request.method == 'POST')
        if request.url.path.startswith("/api/") and not public:
            session = sessions.get(request.cookies.get("buaa_session"))
            if not session or time.monotonic() - session[1] > 86400:
                return JSONResponse({"detail": "管理会话未建立"}, status_code=401)
            if request.method not in ("GET", "HEAD") and not secrets.compare_digest(request.headers.get("x-buaa-csrf", ""), session[0]):
                return JSONResponse({"detail": "管理请求校验失败"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/api/session")
    async def bootstrap(request: Request):
        # A password protects creation, not reuse of an already authenticated
        # HttpOnly cookie. Reloading a remote browser must not discard it.
        existing = sessions.get(request.cookies.get("buaa_session"))
        if existing and time.monotonic()-existing[1] <= 86400:
            return {"csrf": existing[0], "runtime": capabilities()}
        configured = bool(store.read() or password)
        if configured or headless_setup or not local(request):
            return JSONResponse({"detail": "需要管理密码", "password_required": True,
                                 "configured": configured,
                                 "setup_required": headless_setup and not configured,
                                 "recovery_available": bool(store.read())}, status_code=401)
        return response_session(request)

    class ManagementLogin(BaseModel):
        password: str = Field(strict=True, max_length=1024)

    class Credentials(BaseModel):
        password: str = Field(strict=True, min_length=8, max_length=128)
        proof: str = Field(strict=True, max_length=1024)

    async def bounded_body(request, model):
        data = bytearray()
        try:
            async with asyncio.timeout(12):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > 16384:
                        return JSONResponse({'detail': '管理请求过大'}, status_code=413)
                    data.extend(chunk)
            return model.model_validate(json.loads(data))
        except TimeoutError:
            return JSONResponse({'detail': '管理请求超时'}, status_code=408)
        except (ValueError, TypeError):
            return JSONResponse({'detail': '管理凭据格式无效'}, status_code=422)

    def limited(request):
        key, stamp = request.client.host, time.monotonic()
        if len(attempts) >= 1024:
            for old_key, values in list(attempts.items()):
                if not values or stamp-values[-1] > 60:
                    attempts.pop(old_key, None)
            if key not in attempts and len(attempts) >= 1024:
                return JSONResponse({'detail': '管理登录繁忙'}, status_code=429, headers={'Retry-After': '60'})
        history = attempts[key]
        while history and stamp-history[0] > 60:
            history.popleft()
        if len(history) >= 5:
            return JSONResponse({'detail': '请稍后重试管理登录'}, status_code=429,
                                headers={'Retry-After': str(max(1, int(61-(stamp-history[0]))))})
        history.append(stamp)

    @app.post("/api/session")
    async def authenticate(request: Request):
        # This is the only anonymous JSON write. Bound it before JSON/model
        # parsing (including chunked bodies), rather than after allocation.
        body = await bounded_body(request, ManagementLogin)
        if isinstance(body, JSONResponse): return body
        rate = limited(request)
        if rate: return rate
        if hashing.locked(): return JSONResponse({'detail':'管理验证繁忙，请稍后重试'},status_code=429,headers={'Retry-After':'5'})
        async with hashing:
            valid = await asyncio.to_thread(store.verify, body.password, password)
        if not valid:
            return JSONResponse({"detail": "管理密码错误"}, status_code=401)
        return response_session(request)

    async def replace_credentials(request, action):
        body = await bounded_body(request, Credentials)
        if isinstance(body, JSONResponse): return body
        rate = limited(request)
        if rate: return rate
        if hashing.locked(): return JSONResponse({'detail':'管理验证繁忙，请稍后重试'},status_code=429,headers={'Retry-After':'5'})
        try:
            if action == 'setup':
                if not headless_setup or store.read() or password:
                    return JSONResponse({'detail': '服务已经配置或不支持初始化'}, status_code=409)
                if not secrets.compare_digest(body.proof.encode(), store.bootstrap_token().encode()):
                    return JSONResponse({'detail': '初始化凭据无效，请使用部署日志中的初始化链接'}, status_code=403)
                async with hashing:
                    code = await asyncio.to_thread(store.set_password, body.password, first=True)
            else:
                async with hashing:
                    code = await asyncio.to_thread(store.set_password, body.password,
                        **({'recovery': body.proof} if action == 'reset' else {'current': body.proof, 'legacy': password}))
        except PermissionError:
            return JSONResponse({'detail': '管理凭据无效'}, status_code=401)
        except (ValueError, FileExistsError):
            return JSONResponse({'detail': '凭据状态已变化，请刷新后重新操作'}, status_code=409)
        except OSError:
            return JSONResponse({'detail': '管理凭据保存失败，原凭据保持，请检查私有目录'}, status_code=503)
        sessions.clear()
        # Show the new offline recovery code once; only its hash is persisted.
        result = response_session(request)
        payload = json.loads(result.body)
        payload['recovery_code'] = code
        result.body = json.dumps(payload).encode()
        result.headers['content-length'] = str(len(result.body))
        return result

    @app.post('/api/management/setup')
    async def setup(request: Request):
        return await replace_credentials(request, 'setup')

    @app.post('/api/management/reset')
    async def reset(request: Request):
        return await replace_credentials(request, 'reset')

    @app.post('/api/management/password')
    async def change_password(request: Request):
        return await replace_credentials(request, 'password')

    @app.delete("/api/session")
    async def logout(request: Request):
        # The normal cookie/CSRF middleware applies; this never stops tasks.
        sessions.pop(request.cookies.get("buaa_session"), None)
        response = JSONResponse({"status": "ok"})
        response.delete_cookie("buaa_session", httponly=True, samesite="strict",
                               secure=request.url.scheme == "https")
        return response

    @app.get("/api/health")
    async def health():
        from core.version import VERSION
        return {"status": "ok", "application": "AUTO-BUAATOOLS", "version": VERSION}
