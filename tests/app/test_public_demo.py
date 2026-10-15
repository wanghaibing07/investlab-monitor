"""The network-facing demo is opt-in and cannot serve personal data."""
import os
import unittest
from unittest.mock import patch

from investlab.server import serve


class PublicDemoTest(unittest.TestCase):
    def test_real_account_cannot_be_published(self):
        with patch("investlab.service.settings", return_value={"demo": False}):
            with self.assertRaisesRegex(ValueError, "虚构演示账户"):
                serve("/tmp/not-a-real-account", 0, public_demo=True)

    def test_public_hostname_required(self):
        with patch("investlab.service.settings", return_value={"demo": True}):
            with patch.dict(os.environ, {"INVESTLAB_PUBLIC_HOSTNAME": "", "RENDER_EXTERNAL_HOSTNAME": ""}):
                with self.assertRaisesRegex(ValueError, "访问域名"):
                    serve("/tmp/demo", 0, public_demo=True)

    def test_public_demo_binds_only_with_synthetic_account_and_hostname(self):
        with patch("investlab.service.settings", return_value={"demo": True}):
            with patch.dict(os.environ, {"INVESTLAB_PUBLIC_HOSTNAME": "investlab.example.org"}):
                with patch("investlab.server.ThreadingHTTPServer") as http:
                    http.return_value.server_port = 8765
                    serve("/tmp/demo", 0, public_demo=True)
                    args = http.call_args
                    self.assertEqual(args.args[0], ("0.0.0.0", 0))

    def test_default_stays_on_loopback(self):
        with patch("investlab.server.ThreadingHTTPServer") as http:
            http.return_value.server_port = 8765
            serve("/tmp/demo", 0)
            self.assertEqual(http.call_args.args[0], ("127.0.0.1", 0))


if __name__ == "__main__":
    unittest.main()
