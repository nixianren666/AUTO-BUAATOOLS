"""TD management stays behind the application's existing session/CSRF boundary."""
import asyncio
import sqlite3
import json
import struct
from contextlib import suppress
from typing import Annotated, Literal

from fastapi import HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from core.td_store import TDStore
from core.td_scheduler import TDEngine


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Settings(StrictModel):
    campus: Literal["学院路", "沙河"]
    start: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    end: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    semester_start: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    semester_end: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    target: Annotated[int, Field(strict=True, ge=1, le=99)] = 32
    daily_limit: Annotated[int, Field(strict=True, ge=1, le=3)] = 3
    confirmed: StrictBool
    weekdays: Annotated[list[Annotated[int,Field(strict=True,ge=0,le=6)]],Field(min_length=1,max_length=7)]
    closed_dates: Annotated[list[Annotated[str,Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]],Field(max_length=100)] = []


class Toggle(StrictModel):
    enabled: StrictBool


class Manual(StrictModel):
    phase: Literal['entry','exit']
    confirmed: StrictBool


class Batch(StrictModel):
    confirmed: StrictBool


class Activation(StrictModel):
    code: Annotated[str, Field(strict=True,min_length=80,max_length=4096)]


class Empty(StrictModel):
    pass


class Delete(StrictModel):
    ids: Annotated[list[Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]], Field(min_length=1, max_length=100)]


class Count(StrictModel):
    count: Annotated[int, Field(strict=True, ge=0, le=999)]


class Resolve(StrictModel):
    verified: StrictBool


class GroupRef(StrictModel):
    entry_image: Annotated[str, Field(pattern=r'^[0-9a-f]{32}$')]
    exit_image: Annotated[str, Field(pattern=r'^[0-9a-f]{32}$')]
    name: Annotated[str, Field(max_length=40)] = ''
    confirmed: StrictBool


class GroupUpload(StrictModel):
    entry_size: Annotated[int, Field(strict=True, ge=1, le=8*1024*1024)]
    exit_size: Annotated[int, Field(strict=True, ge=1, le=8*1024*1024)]
    name: Annotated[str, Field(max_length=40)] = ''
    confirmed: StrictBool


def install(app, config_path, resolve_account, accounts, log):
    holder = {"engine": None, "task": None}
    private = config_path.parent / (config_path.stem + ".td-private")
    import_slots = asyncio.Semaphore(2)

    def service():
        if holder["engine"] is None:
            try:
                store=TDStore(private)
                try:holder["engine"] = TDEngine(store, accounts.get, log)
                except BaseException:
                    store.db.close();raise
            except (OSError, sqlite3.Error) as exc:
                raise HTTPException(status_code=503, detail="TD私有存储不可读；原数据未重置，请备份后检查权限和磁盘") from exc
        return holder["engine"]

    async def start():
        if holder["task"] is None or holder["task"].done():
            holder["task"] = asyncio.create_task(service().run(accounts))

    async def perform(username, callback):
        acc = resolve_account(username)
        engine = service()
        def work():
            with engine.account_lock(username):
                if acc.removed or accounts.get(username) is not acc:
                    raise ValueError("账号已移除，请重新选择学生")
                return callback(engine)
        try:
            return await asyncio.to_thread(work)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=409, detail=str(exc) if isinstance(exc, ValueError) else "图片不可用，请重新导入") from exc
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail="TD私有数据无法读写，请检查磁盘空间与权限") from exc

    @app.on_event("startup")
    async def restore():
        # An unchanged user profile does not acquire a new directory until TD
        # is opened. Existing configured tasks resume independently of CAS.
        if private.is_dir():
            try:
                await start()
            except Exception:
                log('error', 'TD私有存储暂不可用，已停用TD恢复；常规课堂与博雅不受影响，原数据未重置', category='td')

    @app.on_event("shutdown")
    async def shutdown():
        if holder["engine"]:
            holder["engine"].stopping = True
        if holder["task"]:
            holder["task"].cancel()
            with suppress(asyncio.CancelledError):
                await holder["task"]
        if holder['engine']:
            await asyncio.to_thread(holder['engine'].close)
        holder.update(engine=None, task=None)

    @app.get("/api/td/status")
    async def status(username: str = Query(min_length=1)):
        resolve_account(username)
        # Reads use the short storage lock, not the network-operation lock, so
        # sending_entry/sending_exit remain observable while sockets are busy.
        try:
            return await asyncio.to_thread(service().status,username)
        except (OSError,sqlite3.Error) as exc:
            raise HTTPException(503,'TD私有数据暂不可读，请检查磁盘与权限') from exc

    @app.post('/api/td/batch')
    async def batch(body: Batch, username: str = Query(min_length=1)):
        result=await perform(username,lambda e:e.start_batch(username,body.confirmed))
        await start()
        return {'status':'ok',**result}

    @app.post("/api/td/settings")
    async def settings(body: Settings, username: str = Query(min_length=1)):
        await perform(username, lambda engine: engine.configure(username, body.model_dump()))
        return {"status": "ok"}

    @app.post("/api/td/toggle")
    async def toggle(body: Toggle, username: str = Query(min_length=1)):
        await perform(username, lambda engine: engine.toggle(username, body.enabled))
        await start()
        return {"status": "ok"}

    @app.post("/api/td/count")
    async def count(body: Count, username: str = Query(min_length=1)):
        await perform(username, lambda engine: engine.record_count(username, body.count))
        return {"status": "ok"}

    @app.post("/api/td/resolve")
    async def resolve(body: Resolve, username: str = Query(min_length=1)):
        await perform(username, lambda engine: engine.resolve(username, body.verified))
        return {"status": "ok"}

    @app.post('/api/td/manual')
    async def manual(body: Manual, username: str = Query(min_length=1)):
        result=await perform(username,lambda e:e.manual(username,body.phase,body.confirmed))
        return {'status':'ok',**result}

    @app.get('/api/td/license/status')
    async def license_status(username: str = Query(min_length=1)):
        # The entrance reads only authorization, never gallery/task/school data.
        return {'license': await perform(username, lambda e: e.licensing.status(username))}

    @app.post('/api/td/license/request')
    async def license_request(body: Empty, username: str = Query(min_length=1)):
        code=await perform(username,lambda e:e.licensing.request(username))
        return {'request':code}

    @app.post('/api/td/license/activate')
    async def license_activate(body: Activation, username: str = Query(min_length=1)):
        state=await perform(username,lambda e:e.licensing.activate(username,body.code.strip()))
        log('info','TD离线授权已激活，有效至 '+state['expires_at'],username=username,category='td')
        return {'license':state}

    @app.post('/api/td/groups/from-library')
    async def group_from_library(body: GroupRef, username: str = Query(min_length=1)):
        result = await perform(username, lambda e:e.store.create_group(username,body.entry_image,body.exit_image,body.name,body.confirmed))
        return {'status':'ok', **result}

    @app.post('/api/td/groups')
    async def group_upload(request: Request, username: str = Query(min_length=1)):
        resolve_account(username)
        if request.headers.get('content-type') != 'application/octet-stream':
            raise HTTPException(415, '请按一组入口/出口照片提交')
        data = bytearray()
        try:
            async with asyncio.timeout(30):
                async for chunk in request.stream():
                    if len(data)+len(chunk) > 16*1024*1024+2052:
                        raise HTTPException(413, '每组两张照片，每张最多8MB')
                    data.extend(chunk)
            if len(data) < 4:
                raise ValueError()
            size = struct.unpack('>I',data[:4])[0]
            if not 1 <= size <= 2048 or len(data) < 4+size:
                raise ValueError()
            meta = GroupUpload.model_validate(json.loads(data[4:4+size].decode('utf-8')))
            start = 4+size
            if len(data) != start+meta.entry_size+meta.exit_size:
                raise ValueError()
        except TimeoutError as exc:
            raise HTTPException(408, '照片组上传超时') from exc
        except ValueError as exc:
            raise HTTPException(422, '照片组内容不完整或参数无效') from exc
        async with import_slots:
            result = await perform(username, lambda e:e.store.import_group(username,bytes(data[start:start+meta.entry_size]),bytes(data[start+meta.entry_size:]),meta.name,meta.confirmed))
        return {'status':'ok', **result}

    @app.delete('/api/td/groups')
    async def group_delete(body: Delete, username: str = Query(min_length=1)):
        result = await perform(username, lambda e:e.store.delete_groups(username,list(set(body.ids))))
        return {'status':'ok', **result}

    @app.post("/api/td/images")
    async def upload(request: Request, username: str = Query(min_length=1)):
        resolve_account(username)
        if request.headers.get("content-type", "").split(";")[0] not in ("image/jpeg", "image/png", "image/webp"):
            raise HTTPException(status_code=415, detail="仅支持JPEG/PNG/WebP图片")
        data = bytearray()
        try:
            async with asyncio.timeout(30):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > 8 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="每张图片最多8MB")
                    data.extend(chunk)
        except TimeoutError as exc:
            raise HTTPException(status_code=408, detail="导入超时，请重新选择图片") from exc
        result = await perform(username, lambda engine: engine.store.add_image(username, bytes(data)))
        return {"status": "ok", **result}

    @app.delete("/api/td/images")
    async def delete(body: Delete, username: str = Query(min_length=1)):
        result = await perform(username, lambda engine: engine.store.delete_images(username, list(set(body.ids))))
        return {"status": "ok", **result}

    @app.get("/api/td/images/{image_id}")
    async def image(image_id: str, username: str = Query(min_length=1), thumbnail: bool = True):
        data = await perform(username, lambda engine: engine.store.read_image(username, image_id, thumbnail))
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store", "Content-Disposition": "inline"})

    async def remove(username):
        if holder["engine"] is not None:
            await asyncio.to_thread(holder["engine"].remove_account, username)
        elif private.exists():
            # Account disposal without an active TD lifespan must not leave an
            # idle SQLite handle behind (including isolated TestClient users).
            engine = TDEngine(TDStore(private), accounts.get, log)
            try:
                await asyncio.to_thread(engine.remove_account, username)
            finally:
                await asyncio.to_thread(engine.close)

    app.state.td_holder = holder
    return remove
