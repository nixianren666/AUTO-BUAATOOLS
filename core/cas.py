"""
BUAA 统一身份认证 (CAS/SSO) 页面解析与参数构造模块
对应 UBAA LocalCasParser
"""

import re
from typing import Dict, Optional, Tuple


class CasParser:
    EXECUTION_REGEX = re.compile(r'<input[^>]*name=["\']execution["\'][^>]*value=["\']([^"\']+)["\'][^>]*>', re.I)
    TIP_REGEX = re.compile(r'<div[^>]*class=["\'][^"\']*tip-text[^"\']*["\'][^>]*>([\s\S]*?)</div>', re.I)
    CAPTCHA_CONFIG_REGEX = re.compile(r'config\.captcha\s*=\s*\{\s*type:\s*[\'"]([^\'"]+)[\'"],\s*id:\s*[\'"]([^\'"]+)[\'"]')
    INPUT_TAG_REGEX = re.compile(r'<input\b([^>]*)>', re.I)
    ATTR_REGEX = re.compile(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*["\']([^"\']*)["\']')

    @classmethod
    def extract_execution(cls, html: str) -> str:
        match = cls.EXECUTION_REGEX.search(html)
        return match.group(1) if match else ""

    @classmethod
    def extract_tip_text(cls, html: str) -> Optional[str]:
        match = cls.TIP_REGEX.search(html)
        if match:
            text = cls._strip_html(match.group(1)).strip()
            return text if text else None
        return None

    @classmethod
    def detect_captcha(cls, html: str) -> Optional[Tuple[str, str]]:
        """检测是否需要验证码，返回 (captcha_type, captcha_id)"""
        match = cls.CAPTCHA_CONFIG_REGEX.search(html)
        if match:
            return match.group(1), match.group(2)
        return None

    @classmethod
    def find_login_error(cls, html: str) -> Optional[str]:
        if not html:
            return None
        tip = cls.extract_tip_text(html)
        if tip:
            return tip

        candidates = [
            re.compile(r'<div[^>]*id=["\']errorDiv["\'][^>]*>([\s\S]*?)</div>', re.I),
            re.compile(r'<div[^>]*class=["\'][^"\']*errors[^"\']*["\'][^>]*>([\s\S]*?)</div>', re.I),
            re.compile(r'<p[^>]*class=["\'][^"\']*errors[^"\']*["\'][^>]*>([\s\S]*?)</p>', re.I),
            re.compile(r'<span[^>]*class=["\'][^"\']*errors[^"\']*["\'][^>]*>([\s\S]*?)</span>', re.I),
        ]
        for regex in candidates:
            m = regex.search(html)
            if m:
                text = cls._strip_html(m.group(1)).strip()
                if text:
                    return text
        return None

    @classmethod
    def is_ignorable_password_expiry(cls, html: str) -> bool:
        if not html or not cls.extract_execution(html):
            return False
        lower = html.lower()
        return (
            "continueform" in lower
            or "ignoreandcontinue" in lower
            or "账号存在安全风险" in html
            or "密码过期" in html
        )

    @classmethod
    def parse_inputs(cls, html: str) -> list[Dict[str, str]]:
        inputs = []
        for match in cls.INPUT_TAG_REGEX.finditer(html):
            attr_str = match.group(1)
            attrs = dict(cls.ATTR_REGEX.findall(attr_str))
            if re.search(r'\bchecked\b', attr_str, re.I):
                attrs["checked"] = "checked"
            inputs.append(attrs)
        return inputs

    @classmethod
    def build_login_params(cls, html: str, username: str, password: str, execution: str = "", captcha: str = "") -> Dict[str, str]:
        inputs = cls.parse_inputs(html)
        params: Dict[str, str] = {}
        present_names = set()

        for attrs in inputs:
            name = attrs.get("name", "").strip()
            if not name:
                continue
            input_type = attrs.get("type", "").strip().lower()
            val = attrs.get("value", "")

            if name in ("username", "password"):
                present_names.add(name)
            elif input_type in ("submit", "button", "image"):
                continue
            elif input_type == "checkbox":
                present_names.add(name)
                if "checked" in attrs:
                    params[name] = val if val else "on"
            else:
                present_names.add(name)
                if input_type == "hidden" or val:
                    params[name] = val

        params["username"] = username
        params["password"] = password
        params["submit"] = "登录"
        if "execution" not in params or not params["execution"]:
            params["execution"] = execution or cls.extract_execution(html)
        if "_eventId" not in params:
            params["_eventId"] = "submit"
        if "type" not in params:
            params["type"] = "username_password"

        if captcha:
            params["captcha"] = captcha
            params["captchaResponse"] = captcha

        return params

    @classmethod
    def _strip_html(cls, text: str) -> str:
        return re.sub(r'<[^>]+>', ' ', text)
