import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout, redirect_stderr
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import wait_for_meeting as w


class Feed:
    def __init__(self):
        self.responses = []  # (status, body) popped in order; last one repeats
        self.queries = []


def make_server(feed):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            u = urlparse(self.path)
            feed.queries.append((u.path, parse_qs(u.query)))
            r = feed.responses.pop(0) if len(feed.responses) > 1 else feed.responses[0]
            body = json.dumps(r[1]).encode()
            self.send_response(r[0])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def speech(i, who="Dana", text="hello agent", **kw):
    e = {"id": i, "at": "2026-11-18T10:00:05Z", "type": "speech", "from": who, "text": text}
    e.update(kw)
    return e


class T(unittest.TestCase):
    def setUp(self):
        self.feed = Feed()
        self.srv = make_server(self.feed)
        self.dir = tempfile.mkdtemp()
        self.cf = os.path.join(self.dir, "sub", "c.cursor")
        self.env = {
            "LIVE_NOTES_AGENT_LINK": "http://127.0.0.1:%d/a/secret/" % self.srv.server_port,
            "LIVE_NOTES_CURSOR_FILE": self.cf,
            "LIVE_NOTES_MAX_WAIT_S": "5",
            "LIVE_NOTES_POLL_S": "1",
        }

    def tearDown(self):
        self.srv.shutdown()

    def run_hook(self, **env):
        e = dict(self.env, **env)
        out, err = io.StringIO(), io.StringIO()
        old = sys.stdin
        sys.stdin = io.StringIO("{}")
        try:
            with redirect_stdout(out), redirect_stderr(err):
                rc = w.run(e, sleep=lambda s: None)
        finally:
            sys.stdin = old
        self.assertEqual(rc, 0)
        return out.getvalue()

    def test_wakes_with_line(self):
        self.feed.responses = [
            (200, {"cursor": "c1", "events": [speech(1, text="old")]}),
            (200, {"next": "c2", "events": [
                speech(2, who="vibe-agent", text="mine"),
                speech(3, in_scope=False, text="side talk"),
                speech(4, text="what is the plan?")]}),
        ]
        out = self.run_hook()
        d = json.loads(out)
        self.assertEqual(d["decision"], "deny")
        self.assertIn("10:00:05 Dana: what is the plan?", d["reason"])
        self.assertNotIn("old", d["reason"])
        self.assertNotIn("mine", d["reason"])
        self.assertNotIn("side talk", d["reason"])
        self.assertEqual(open(self.cf).read(), "c2")

    def test_starts_from_now_without_cursor_file(self):
        self.feed.responses = [(200, {"cursor": "c9", "events": [speech(1)]}),
                               (200, {"next": "c9", "events": []})]
        out = self.run_hook(LIVE_NOTES_MAX_WAIT_S="2")
        self.assertEqual(out, "")
        self.assertEqual(self.feed.queries[0][1].get("after"), None)
        self.assertEqual(self.feed.queries[1][1]["after"], ["c9"])

    def test_resumes_from_cursor_file(self):
        os.makedirs(os.path.dirname(self.cf))
        open(self.cf, "w").write("c5")
        self.feed.responses = [(200, {"next": "c6", "events": [speech(6, text="hi")]})]
        out = self.run_hook()
        self.assertEqual(self.feed.queries[0][1]["after"], ["c5"])
        self.assertIn("hi", json.loads(out)["reason"])

    def test_max_wait_returns_nothing(self):
        os.makedirs(os.path.dirname(self.cf))
        open(self.cf, "w").write("c5")
        self.feed.responses = [(200, {"next": "c5", "events": []})]
        self.assertEqual(self.run_hook(LIVE_NOTES_MAX_WAIT_S="2"), "")

    def test_survives_failed_request(self):
        os.makedirs(os.path.dirname(self.cf))
        open(self.cf, "w").write("c5")
        self.feed.responses = [(500, {}), (200, {"next": "c6", "events": [speech(6)]})]
        out = self.run_hook()
        self.assertEqual(json.loads(out)["decision"], "deny")

    def test_revoked_accepts(self):
        os.makedirs(os.path.dirname(self.cf))
        open(self.cf, "w").write("c5")
        self.feed.responses = [(403, {})]
        self.assertEqual(self.run_hook(), "")

    def test_missing_link_accepts(self):
        self.assertEqual(self.run_hook(LIVE_NOTES_AGENT_LINK=""), "")


if __name__ == "__main__":
    unittest.main()
