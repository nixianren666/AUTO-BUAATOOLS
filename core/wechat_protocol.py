"""Notification-only iLink client, based on Tencent/openclaw-weixin docs/protocol.md.

Reference snapshot: 874637a0dbc24050f72d1385add4fc6170a2d726 (MIT).
This is an independent implementation; it does not load an agent or school API.
"""
import base64
import secrets
from urllib.parse import urlsplit
import re

import httpx
from core.version import VERSION

BASE_URL = 'https://ilinkai.weixin.qq.com'
CHANNEL_VERSION = '2.4.10'


class WechatError(Exception):
    def __init__(self, code=None, kind='business'):
        self.code = code
        self.kind = kind
        super().__init__('微信通道暂不可用' if code != -14 else '微信登录状态已失效，请重新绑定')


def trusted_base(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname or ''
    except (ValueError, TypeError, AttributeError):
        raise WechatError() from None
    if (parsed.scheme != 'https' or parsed.username or parsed.password or port not in (None, 443)
        or parsed.path not in ('', '/') or parsed.query or parsed.fragment
        or not re.fullmatch(r'ilink[a-z0-9-]*\.weixin\.qq\.com', host)):
        raise WechatError()
    return 'https://' + host


class WechatProtocol:
    def __init__(self, client=None):
        # No ambient application credentials, cookies or third-party proxies.
        self.client = client or httpx.AsyncClient(trust_env=False, follow_redirects=False)

    async def close(self):
        await self.client.aclose()

    async def request(self, endpoint, *, base=BASE_URL, token=None, body=None, params=None, poll=False, timeout_ms=None):
        base = trusted_base(base)
        headers = {'iLink-App-Id': 'bot', 'iLink-App-ClientVersion': str((2 << 16) | (4 << 8) | 10)}
        if body is not None:
            headers.update({'Content-Type':'application/json', 'AuthorizationType':'ilink_bot_token',
                'X-WECHAT-UIN':base64.b64encode(str(secrets.randbits(32)).encode()).decode()})
        if token:
            headers['Authorization'] = 'Bearer ' + token
            body = dict(body or {}, base_info={'channel_version':CHANNEL_VERSION, 'bot_agent':'AUTO-BUAATOOLS/'+VERSION})
        try:
            seconds=38 if poll else 15
            if poll and type(timeout_ms) is int and 0<timeout_ms<=120000:seconds=timeout_ms/1000+3
            async with self.client.stream('POST' if body is not None else 'GET', base + '/ilink/bot/' + endpoint,
                json=body, params=params, headers=headers, timeout=httpx.Timeout(seconds, connect=10)) as result:
                result.raise_for_status()
                content = bytearray()
                async for chunk in result.aiter_bytes():
                    if len(content) + len(chunk) > 1048576:
                        raise WechatError()
                    content.extend(chunk)
            import json
            data = json.loads(content)
            if not isinstance(data, dict): raise WechatError()
            codes=[data.get(field) for field in ('ret','errcode') if data.get(field) not in (None,0)]
            if codes:
                # Preserve bounded numeric diagnostics, never provider text or tokens.
                code=-14 if -14 in codes else next((x for x in reversed(codes) if type(x) is int and abs(x)<1000000),None)
                raise WechatError(code)
            return data
        except httpx.HTTPStatusError as exc:
            raise WechatError(exc.response.status_code,kind='http') from None
        except httpx.HTTPError:
            raise WechatError(kind='transport') from None
        except (ValueError, TypeError):
            raise WechatError(kind='payload') from None

    async def qrcode(self):
        return await self.request('get_bot_qrcode', params={'bot_type':'3'}, body={'local_token_list':[]})

    async def qr_status(self, qrcode, base=BASE_URL, verify_code=None):
        params={'qrcode':qrcode}
        if verify_code:params['verify_code']=verify_code
        return await self.request('get_qrcode_status', base=base, params=params, poll=True)

    async def updates(self, binding):
        return await self.request('getupdates', base=binding['base'], token=binding['token'],
            body={'get_updates_buf':binding.get('cursor','')}, poll=True, timeout_ms=binding.get('poll_timeout_ms'))

    async def send(self, binding, text, client_id):
        if not binding.get('context'): raise WechatError()
        result = await self.request('sendmessage', base=binding['base'], token=binding['token'], body={'msg':{
            'from_user_id':'', 'to_user_id':binding['peer'], 'client_id':client_id,
            'message_type':2, 'message_state':2, 'context_token':binding['context'],
            'item_list':[{'type':1, 'text_item':{'text':text}}]}})
        # Tencent's official helper permits an absent optional ret field. A
        # parsed HTTP success without ret is submitted, never delivery proof.
        return result
