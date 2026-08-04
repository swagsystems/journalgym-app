import importlib
import os
import tempfile
import unittest
from types import SimpleNamespace


class ProxyHeaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["FITNESS_DB_PATH"] = os.path.join(self.tmp.name, "fitness.db")
        os.environ["FITNESS_TRUSTED_PROXIES"] = "10.0.0.0/8,127.0.0.1"

        import api.main

        self.main = importlib.reload(api.main)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("FITNESS_TRUSTED_PROXIES", None)

    def test_uses_forwarded_for_from_trusted_proxy(self):
        request = SimpleNamespace(
            headers={"x-forwarded-for": "203.0.113.9, 10.1.2.3"},
            client=SimpleNamespace(host="10.1.2.3"),
        )
        self.assertEqual(self.main.client_ip(request), "203.0.113.9")

    def test_ignores_forwarded_for_from_untrusted_peer(self):
        request = SimpleNamespace(
            headers={"x-forwarded-for": "203.0.113.9"},
            client=SimpleNamespace(host="198.51.100.4"),
        )
        self.assertEqual(self.main.client_ip(request), "198.51.100.4")


if __name__ == "__main__":
    unittest.main()
