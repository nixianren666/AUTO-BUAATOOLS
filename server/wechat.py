"""Authenticated, explicitly account-scoped notification management routes."""
import io
import asyncio
from fastapi import HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from core.wechat import WechatNotifications
from core.wechat_protocol import WechatError


def install(app, config_path, accounts, course_reader=None):
    engine=WechatNotifications(config_path.with_name('.wechat-private'),
        lambda username: username in accounts and not accounts[username].removed, course_reader=course_reader)

    def account(username):
        if username not in accounts or accounts[username].removed:
            raise HTTPException(404,'指定账号不存在')

    async def safely(action):
        try:return await action
        except (WechatError, ValueError) as exc:raise HTTPException(409,str(exc)) from None

    class Student(BaseModel):
        username: str = Field(min_length=1,max_length=128,strict=True)

    class Wait(Student):
        binding_id: str = Field(min_length=32,max_length=32,pattern='^[a-f0-9]+$')
        verify_code: str | None = Field(default=None,min_length=1,max_length=16,pattern='^[0-9]+$',strict=True)

    class Settings(Student):
        enabled: bool = Field(strict=True)
        important_only: bool = Field(strict=True)
        course_reminders: bool | None = Field(default=None,strict=True)

    @app.on_event('startup')
    async def start():
        await engine.start()

    @app.on_event('shutdown')
    async def stop():
        await engine.stop()

    @app.get('/api/wechat/status')
    async def status(username: str=Query(min_length=1,max_length=128)):
        account(username)
        return dict(engine.status(username),username=username)

    @app.post('/api/wechat/bind')
    async def bind(body: Student):
        account(body.username)
        return await safely(engine.begin(body.username))

    @app.post('/api/wechat/bind/status')
    async def wait(body: Wait):
        account(body.username)
        return await safely(engine.wait(body.username,body.binding_id,body.verify_code))

    @app.get('/api/wechat/qrcode')
    async def qr(username: str=Query(min_length=1,max_length=128), binding_id: str=Query(min_length=32,max_length=32)):
        account(username)
        try:content=engine.qr_content(username,binding_id)
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
        # Generate locally. Do not send private QR content to a QR image service.
        import qrcode
        def render():
            image=qrcode.make(content)
            buffer=io.BytesIO();image.save(buffer,format='PNG')
            return buffer.getvalue()
        return Response(await asyncio.to_thread(render),media_type='image/png',headers={'Cache-Control':'no-store'})

    @app.post('/api/wechat/settings')
    async def settings(body: Settings):
        account(body.username)
        await safely(engine.configure(body.username,body.enabled,body.important_only,body.course_reminders))
        return {'status':'ok'}

    @app.post('/api/wechat/unbind')
    async def unbind(body: Student):
        account(body.username)
        await safely(engine.remove(body.username))
        return {'status':'ok'}

    @app.post('/api/wechat/test')
    async def test(body: Student):
        account(body.username)
        return await safely(engine.test(body.username))

    return engine
