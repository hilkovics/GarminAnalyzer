"""Credentials never reach a log line, even via urllib3 DEBUG output (CLAUDE.md rule 8, review phase 7)."""

import io
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

from training import log_redaction
from training.services import notify

TOKEN = "123456789:AAEhBOweik9ai2o4-SECRET_token"


def test_redact_patterns():
    text = f"POST /bot{TOKEN}/sendMessage key=sk-ant-api03-abc_DEF-123 Authorization: Bearer abc.def-ghi"
    out = log_redaction.redact(text)
    assert TOKEN not in out and "sk-ant-api03" not in out and "abc.def-ghi" not in out
    assert "bot<redacted>" in out and "Bearer <redacted>" in out


class _Ok(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):  # keep the test server quiet
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Ok)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()


def test_telegram_token_is_redacted_from_urllib3_debug_lines(server, monkeypatch):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    urllib3_logger = logging.getLogger("urllib3")
    old_level, old_root = urllib3_logger.level, root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    urllib3_logger.setLevel(logging.DEBUG)  # what `training -v` does
    log_redaction.install()
    monkeypatch.setattr(notify, "API_URL", f"http://127.0.0.1:{server}/bot{{token}}/sendMessage")
    try:
        assert notify._post(requests, TOKEN, "42", "ahoj") is True
    finally:
        root.removeHandler(handler)
        root.setLevel(old_root)
        urllib3_logger.setLevel(old_level)
    output = stream.getvalue()
    assert "/bot<redacted>/sendMessage" in output  # urllib3 did log the request line …
    assert TOKEN not in output and "SECRET_token" not in output  # … without the token
