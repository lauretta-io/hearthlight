import asyncio
import json
import unittest
from types import SimpleNamespace

from src.webapp import main as webapp_main


class WebappSecurityTests(unittest.TestCase):
    def setUp(self):
        self.original_api_key = webapp_main.API_KEY
        self.original_allow_remote = webapp_main.ALLOW_REMOTE_WITHOUT_API_KEY
        self.original_local_stack_mode = webapp_main.LOCAL_STACK_MODE

    def tearDown(self):
        webapp_main.API_KEY = self.original_api_key
        webapp_main.ALLOW_REMOTE_WITHOUT_API_KEY = self.original_allow_remote
        webapp_main.LOCAL_STACK_MODE = self.original_local_stack_mode

    def test_request_is_local_only_accepts_loopback_hosts(self):
        request = SimpleNamespace(
            headers={
                "host": "localhost:8000",
                "origin": "http://127.0.0.1:3000",
            },
            client=SimpleNamespace(host="127.0.0.1"),
        )

        self.assertTrue(webapp_main.request_is_local_only(request))

    def test_request_is_local_only_rejects_remote_hosts(self):
        request = SimpleNamespace(
            headers={
                "host": "example.com",
            },
            client=SimpleNamespace(host="10.0.0.8"),
        )

        self.assertFalse(webapp_main.request_is_local_only(request))

    def test_request_is_local_only_rejects_spoofed_loopback_headers_from_remote_client(self):
        request = SimpleNamespace(
            headers={
                "host": "localhost:8000",
                "origin": "http://127.0.0.1:3000",
            },
            client=SimpleNamespace(host="10.0.0.8"),
        )

        self.assertFalse(webapp_main.request_is_local_only(request))

    def test_request_is_local_only_accepts_loopback_forwarded_by_local_proxy(self):
        request = SimpleNamespace(
            headers={
                "host": "localhost:8000",
                "origin": "http://127.0.0.1:3000",
                "x-real-ip": "127.0.0.1",
                "x-forwarded-for": "127.0.0.1",
            },
            client=SimpleNamespace(host="172.18.0.10"),
        )

        self.assertTrue(webapp_main.request_is_local_only(request))

    def test_request_is_local_only_accepts_loopback_hosts_in_local_stack_mode(self):
        webapp_main.LOCAL_STACK_MODE = True
        request = SimpleNamespace(
            headers={
                "host": "localhost:8000",
                "origin": "http://127.0.0.1:3000",
            },
            client=SimpleNamespace(host="172.18.0.10"),
        )

        self.assertTrue(webapp_main.request_is_local_only(request))

    def test_remote_requests_require_api_key_when_key_not_configured(self):
        webapp_main.API_KEY = None
        webapp_main.ALLOW_REMOTE_WITHOUT_API_KEY = False

        request = SimpleNamespace(
            method="GET",
            headers={"host": "example.com"},
            url=SimpleNamespace(path="/"),
            client=SimpleNamespace(host="10.0.0.8"),
        )

        response = asyncio.run(webapp_main.require_api_key(request, lambda _: None))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            json.loads(response.body.decode("utf-8"))["detail"],
            "remote API access requires WEBAPP_API_KEY",
        )

    def test_local_requests_work_without_api_key(self):
        webapp_main.API_KEY = None
        webapp_main.ALLOW_REMOTE_WITHOUT_API_KEY = False

        request = SimpleNamespace(
            method="GET",
            headers={"host": "localhost:8000"},
            url=SimpleNamespace(path="/"),
            client=SimpleNamespace(host="127.0.0.1"),
        )

        async def call_next(_request):
            return SimpleNamespace(headers={})

        response = asyncio.run(webapp_main.require_api_key(request, call_next))

        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_spoofed_loopback_headers_do_not_bypass_api_key_requirement(self):
        webapp_main.API_KEY = None
        webapp_main.ALLOW_REMOTE_WITHOUT_API_KEY = False

        request = SimpleNamespace(
            method="GET",
            headers={
                "host": "localhost:8000",
                "origin": "http://127.0.0.1:3000",
            },
            url=SimpleNamespace(path="/"),
            client=SimpleNamespace(host="10.0.0.8"),
        )

        response = asyncio.run(webapp_main.require_api_key(request, lambda _: None))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            json.loads(response.body.decode("utf-8"))["detail"],
            "remote API access requires WEBAPP_API_KEY",
        )

    def test_forwarded_loopback_proxy_request_works_without_api_key(self):
        webapp_main.API_KEY = None
        webapp_main.ALLOW_REMOTE_WITHOUT_API_KEY = False

        request = SimpleNamespace(
            method="GET",
            headers={
                "host": "localhost:8000",
                "origin": "http://127.0.0.1:3000",
                "x-real-ip": "127.0.0.1",
                "x-forwarded-for": "127.0.0.1",
            },
            url=SimpleNamespace(path="/"),
            client=SimpleNamespace(host="172.18.0.10"),
        )

        async def call_next(_request):
            return SimpleNamespace(headers={})

        response = asyncio.run(webapp_main.require_api_key(request, call_next))

        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")


if __name__ == "__main__":
    unittest.main()
