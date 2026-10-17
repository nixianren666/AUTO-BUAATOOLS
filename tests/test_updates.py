"""No school requests, GitHub writes or installation; deterministic release checks."""
import concurrent.futures
import threading
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.updates import API_URL, UpdateChecker, UpdateUnavailable, release_version, request_latest, version_tuple
from core.version import VERSION
from server.management import install as management
from server.update_routes import install


def release(tag="v1.2.10", **extra):
    return {"tag_name": tag, "draft": False, "prerelease": False, **extra}


class UpdateTests(unittest.TestCase):
    def test_numeric_version_comparison(self):
        self.assertGreater(version_tuple("1.2.10"), version_tuple("1.2.9"))
        self.assertEqual(UpdateChecker("1.2.9", lambda: release()).check()["status"], "update_available")

    def test_same_version(self):
        self.assertEqual(UpdateChecker("1.2.10", lambda: release()).check()["status"], "up_to_date")

    def test_local_candidate_never_downgrades(self):
        self.assertEqual(UpdateChecker("1.2.11", lambda: release()).check()["status"], "local_ahead")

    def test_tags_are_strict_stable_semver(self):
        for tag in [None, True, 12, "1.2.10", "v01.2.10", "v1.2.10-rc.1", "v1.2.10+build", "v1.2", "v1.2.3/other", "v1.2.3\n"]:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release_version(tag)

    def test_draft_prerelease_and_missing_flags_are_not_stable(self):
        for data in [release(draft=True), release(prerelease=True), {"tag_name": "v1.2.10"}, [], release(draft="false")]:
            self.assertEqual(UpdateChecker(fetcher=lambda: data).check()["status"], "unavailable")

    def test_external_links_and_html_are_not_forwarded(self):
        result = UpdateChecker("1.2.9", lambda: release(html_url="https://untrusted.invalid", body="<script>bad()</script>")).check()
        self.assertEqual(result["release_url"], "https://github.com/nixianren666/AUTO-BUAATOOLS/releases/tag/v1.2.10")
        self.assertNotIn("body", result)

    def test_day_cache_and_manual_cooldown(self):
        clock = [100.0]
        calls = []
        checker = UpdateChecker(fetcher=lambda: (calls.append(1) or release()), clock=lambda: clock[0])
        self.assertFalse(checker.check()["cached"])
        clock[0] += 59
        self.assertTrue(checker.check(manual=True)["cached"])
        clock[0] += 2
        self.assertTrue(checker.check()["cached"])
        self.assertFalse(checker.check(manual=True)["cached"])
        self.assertEqual(len(calls), 2)

    def test_failed_checks_back_off_even_when_manual(self):
        clock = [100.0]
        def failed():
            raise UpdateUnavailable("synthetic limit", 3600)
        checker = UpdateChecker(fetcher=failed, clock=lambda: clock[0])
        self.assertEqual(checker.check()["status"], "unavailable")
        clock[0] += 61
        self.assertTrue(checker.check(manual=True)["cached"])

    def test_network_failure_does_not_leak_exception(self):
        def failed():
            raise httpx.ConnectError("synthetic private proxy")
        result = UpdateChecker(fetcher=failed).check()
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("proxy", result["message"])

    def test_concurrent_callers_share_one_fetch(self):
        calls = []
        def fetch():
            calls.append(1)
            time.sleep(.02)
            return release()
        checker = UpdateChecker(fetcher=fetch)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: checker.check(manual=True), range(4)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(not r["cached"] for r in results), 1)

    def test_public_request_has_no_credentials_and_only_fixed_target(self):
        requests = []
        def transport(req):
            requests.append(req)
            return httpx.Response(200, json=release())
        real = httpx.Client
        def client(**kwargs):
            self.assertFalse(kwargs["trust_env"])
            self.assertFalse(kwargs["follow_redirects"])
            return real(transport=httpx.MockTransport(transport), **kwargs)
        with patch.dict("os.environ", {"TESTING": "0", "BUAA_SMOKE_PROFILE": "0"}), patch("core.updates.httpx.Client", side_effect=client):
            self.assertEqual(request_latest()["tag_name"], "v1.2.10")
        self.assertEqual(str(requests[0].url), API_URL)
        self.assertNotIn("authorization", requests[0].headers)
        self.assertNotIn("cookie", requests[0].headers)

    def test_smoke_profile_never_contacts_github(self):
        with patch.dict("os.environ", {"BUAA_SMOKE_PROFILE": "1"}), patch("core.updates.httpx.Client") as client:
            self.assertEqual(request_latest()["tag_name"], "v" + VERSION)
            client.assert_not_called()

    def test_response_size_is_bounded(self):
        real = httpx.Client
        def client(**kwargs):
            return real(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"x" * 262145)), **kwargs)
        with patch.dict("os.environ", {"TESTING": "0", "BUAA_SMOKE_PROFILE": "0"}), patch("core.updates.httpx.Client", side_effect=client), self.assertRaises(UpdateUnavailable):
            request_latest()

    def test_rate_limit_and_redirect_do_not_follow(self):
        real = httpx.Client
        for code in [403, 429, 302, 500]:
            def client(**kwargs):
                return real(transport=httpx.MockTransport(lambda req: httpx.Response(code, headers={"Location": "https://untrusted.invalid"})), **kwargs)
            with patch.dict("os.environ", {"TESTING": "0", "BUAA_SMOKE_PROFILE": "0"}), patch("core.updates.httpx.Client", side_effect=client):
                self.assertEqual(UpdateChecker().check()["status"], "unavailable")

    def test_management_boundary_also_protects_update_route(self):
        app = FastAPI()
        management(app)
        install(app)
        app.state.update_checker = UpdateChecker(fetcher=lambda: release("v" + VERSION))
        client = TestClient(app)
        self.assertEqual(client.get("/api/system/updates").status_code, 401)
        client.get("/api/session")
        self.assertEqual(client.get("/api/system/updates?manual=true").json()["status"], "up_to_date")
        self.assertEqual(client.get("/api/system/updates?manual=invalid").status_code, 422)

    def test_release_metadata_validator(self):
        from scripts.check_release_format import validate
        validate("v" + VERSION)
        with self.assertRaises(ValueError):
            validate("v0.0.1")


if __name__ == "__main__":
    unittest.main()
