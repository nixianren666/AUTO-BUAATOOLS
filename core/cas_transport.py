"""School authentication redirects: upgrade only legacy SSO HTTP, then validate."""
import re
from urllib.parse import urljoin, urlsplit

from core.domain import trusted_url
from core.cas import CasParser
from core.webvpn import from_webvpn_url, to_webvpn_url


def secure_cas_transport_url(url: str) -> str:
    # Do not decode/re-encode CAS service queries: their nested encoding is signed
    # into a service ticket. Other HTTP hosts/ports still fail trusted_url.
    return re.sub(r'^http://sso\.buaa\.edu\.cn(?::80)?(?=[/?#]|$)',
                  'https://sso.buaa.edu.cn', url, count=1, flags=re.I)


def resolve_auth_redirect(current_url: str, location: str, mode=None) -> str:
    if not location or not location.strip():
        raise ValueError('学校认证跳转缺少目标')
    location = location.strip()
    if location.startswith(('/https/', '/https-', '/http/', '/http-')):
        candidate = 'https://d.buaa.edu.cn' + location
    else:
        candidate = urljoin(current_url, location)
    wrapped = urlsplit(candidate).hostname == 'd.buaa.edu.cn'
    raw = from_webvpn_url(candidate)
    if wrapped and raw == candidate:
        # Gateway landing/error paths remain subject to the existing allowlist.
        safe = trusted_url(candidate)
    else:
        safe = trusted_url(secure_cas_transport_url(raw))
    use_gateway = mode == 'webvpn' if mode is not None else wrapped
    return to_webvpn_url(safe) if use_gateway else safe


class CasFlowError(ValueError):
    """A safe user-facing failure, without credential-bearing redirect URLs."""


class CasCaptchaRequired(CasFlowError):
    def __init__(self, response, captcha):
        super().__init__('统一认证需要验证码，请在界面重新登录')
        self.response = response
        self.captcha = captcha


REDIRECTS = (301, 302, 303, 307, 308)


def _next_step(response, mode, state):
    if response.status_code in REDIRECTS:
        state['hops'] += 1
        if state['hops'] > 10:
            raise CasFlowError('统一认证跳转次数过多，请稍后重试')
        return 'get', resolve_auth_redirect(str(response.url), response.headers.get('location', ''), mode), None
    raw = urlsplit(from_webvpn_url(str(response.url)))
    # The school's UC root can be 404 after a valid ticket exchange. This is
    # only a landing page; the caller must still verify UC identity/BYKC data.
    uc_root_404 = response.status_code == 404 and raw.hostname == 'uc.buaa.edu.cn' and raw.path in ('', '/')
    if response.status_code >= 400 and not uc_root_404:
        raise CasFlowError('统一认证未通过，请检查账号或稍后重试' if response.status_code in (401,403) else '统一认证服务暂不可用，请稍后重试')
    html = response.text
    captcha = CasParser.detect_captcha(html)
    if captcha:
        raise CasCaptchaRequired(response, captcha)
    if CasParser.is_ignorable_password_expiry(html):
        if state['continued']:
            raise CasFlowError('学校密码提示未能继续，请在学校官方页面处理后重试')
        state['continued'] = True
        target = resolve_auth_redirect(str(response.url), str(response.url).split('?',1)[0], mode)
        return 'post', target, {'execution':CasParser.extract_execution(html),'_eventId':'ignoreAndContinue'}
    error = CasParser.find_login_error(html)
    if error:
        raise CasFlowError(error)
    if CasParser.extract_execution(html):
        raise CasFlowError('统一认证仍停留在登录页，请检查账号密码或验证码')
    return None


async def follow_auth_response(response, client, mode):
    state = {'hops':0,'continued':False}
    while True:
        step = _next_step(response, mode, state)
        if step is None:
            return response
        method, target, data = step
        # Never replay a credential POST onto a redirect target, even for 307/308.
        response = await (client.post(target, data=data) if method == 'post' else client.get(target))


def follow_auth_response_sync(response, client, mode):
    state = {'hops':0,'continued':False}
    while True:
        step = _next_step(response, mode, state)
        if step is None:
            return response
        method, target, data = step
        response = client.post(target, data=data) if method == 'post' else client.get(target)
