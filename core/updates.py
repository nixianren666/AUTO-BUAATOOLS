"""Bounded, anonymous checks of this project's public stable GitHub release."""
import os
import re
import threading
import time

import httpx

from core.version import VERSION

REPOSITORY = "nixianren666/AUTO-BUAATOOLS"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
CHECK_INTERVAL = 86400
_VERSION = re.compile(r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})")


def version_tuple(value):
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise ValueError("Expected X.Y.Z without leading zeroes")
    return tuple(map(int, value.split(".")))


def release_version(tag):
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise ValueError("Stable release tag must be vX.Y.Z")
    version_tuple(tag[1:])
    return tag[1:]


class UpdateUnavailable(Exception):
    def __init__(self, message, retry=600):
        super().__init__(message)
        self.retry = retry


def request_latest():
    # Acceptance profiles must never contact GitHub or inherit a user's token.
    if os.environ.get("TESTING") == "1" or os.environ.get("BUAA_SMOKE_PROFILE") == "1":
        return {"tag_name": f"v{VERSION}", "draft": False, "prerelease": False}
    with httpx.Client(trust_env=False, follow_redirects=False,
                      timeout=httpx.Timeout(6, connect=3), headers={
                          "Accept": "application/vnd.github+json",
                          "X-GitHub-Api-Version": "2022-11-28",
                          "User-Agent": f"AUTO-BUAATOOLS/{VERSION}",
                      }) as client:
        with client.stream("GET", API_URL) as response:
            if response.status_code in (403, 429):
                raise UpdateUnavailable("GitHub暂时限制请求，请稍后重试", 3600)
            if response.status_code == 404:
                raise UpdateUnavailable("暂未找到可用的正式发行版")
            response.raise_for_status()
            data = bytearray()
            deadline = time.monotonic() + 10
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 262144 or time.monotonic() > deadline:
                    raise UpdateUnavailable("发行信息过大，本次检查已停止")
            import json
            return json.loads(data)


class UpdateChecker:
    def __init__(self, current=VERSION, fetcher=None, clock=time.monotonic):
        self.current = current
        version_tuple(current)
        self._fetcher = fetcher or request_latest
        self._clock = clock
        self._lock = threading.Lock()
        self._result = None
        self._stamp = 0
        self._ttl = CHECK_INTERVAL

    def check(self, manual=False):
        # Concurrent windows share one in-flight request and a process cache.
        with self._lock:
            stamp = self._clock()
            age = max(0, stamp - self._stamp)
            limit = 60 if manual and self._result and self._result["status"] != "unavailable" else self._ttl
            if self._result and age < limit:
                return {**self._result, "cached": True,
                        "retry_after_seconds": max(0, int(limit - age))}
            result = {"current_version": self.current, "latest_version": None,
                      "release_url": RELEASES_URL, "checked_at": int(time.time()),
                      "automatic_interval_seconds": CHECK_INTERVAL}
            self._ttl = CHECK_INTERVAL
            try:
                release = self._fetcher()
                if not isinstance(release, dict) or release.get("draft") is not False or release.get("prerelease") is not False:
                    raise UpdateUnavailable("最新发行信息不是有效的正式版")
                latest = release_version(release.get("tag_name"))
                a, b = version_tuple(latest), version_tuple(self.current)
                status = "update_available" if a > b else "up_to_date" if a == b else "local_ahead"
                messages = {"update_available": f"发现新版本 v{latest}", "up_to_date": "当前已是最新正式版",
                            "local_ahead": "当前本地版本高于已发布正式版，无需降级"}
                result.update(status=status, latest_version=latest,
                              release_url=f"{RELEASES_URL}/tag/v{latest}", message=messages[status])
            except (httpx.HTTPError, ValueError, TypeError, UpdateUnavailable) as error:
                self._ttl = error.retry if isinstance(error, UpdateUnavailable) else 600
                result.update(status="unavailable", message=str(error) if isinstance(error, UpdateUnavailable)
                              else "暂时无法检查更新，请确认网络后重试")
            self._result = result
            self._stamp = self._clock()
            return {**result, "cached": False, "retry_after_seconds": self._ttl}
