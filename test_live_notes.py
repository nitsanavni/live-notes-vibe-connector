import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import live_notes as ln


class Meeting:
    """A fake Live Notes agent link that refuses what the real one refuses."""

    def __init__(self):
        self.pages, self.keys, self.chat, self.left = {}, {}, [], []

    def handle(self, method, path, q, headers, body):
        name = (q.get("name") or [""])[0]
        if not name:
            return 400, {"error": "name needed"}
        route = path.split("/a/code/", 1)[1]
        if method == "GET" and route == "feed":
            return 200, {"cursor": "c1", "events": [], "title": "Test", "ended_at": None,
                         "participants": {"people": [{"name": "Dana"}]}}
        if route.startswith("pages/"):
            page = route[6:]
            if method == "DELETE":
                self.pages.pop(page, None)
                self.keys.pop(page, None)
                return 200, {}
            if page in self.keys and headers.get("X-Agent-Key") != self.keys[page]:
                return 409, {"error": "taken"}
            first = page not in self.keys
            self.keys.setdefault(page, "key-%d" % len(self.keys))
            self.pages[page] = body.decode()
            d = {"version": 1, "view_url": "https://x/p/1/"}
            if first:
                d["owner_key"] = self.keys[page]
            return 200, d
        if method == "POST" and route == "chat":
            self.chat.append(json.loads(body)["text"])
            return 200, {"id": "chat.1"}
        if method == "POST" and route == "leave":
            self.left.append(name)
            return 200, {}
        return 404, {"error": "no route"}


def serve(m):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def go(self):
            u = urlparse(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            code, d = m.handle(self.command, u.path, parse_qs(u.query), self.headers, body)
            out = json.dumps(d).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        do_GET = do_PUT = do_POST = do_DELETE = go

    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


class T(unittest.TestCase):
    def setUp(self):
        self.m = Meeting()
        self.srv = serve(self.m)
        self.link = "http://127.0.0.1:%d/a/code/" % self.srv.server_port
        self.old = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        os.environ.pop("LIVE_NOTES_AGENT_NAME", None)

    def tearDown(self):
        os.chdir(self.old)
        self.srv.shutdown()

    def run_cmd(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = ln.main(list(argv))
        return rc, out.getvalue()

    def join(self):
        return self.run_cmd("join", self.link)

    def test_join_saves_link_and_publishes_first_page(self):
        rc, out = self.join()
        self.assertEqual(rc, 0, out)
        self.assertEqual(open(".vibe/agent-link").read().strip(), self.link)
        self.assertIn("vibe-agent", self.m.pages)
        self.assertEqual(open(".vibe/live-notes/owner-key").read().strip(), "key-0")
        self.assertIn("cron", out)

    def test_publish_sends_the_owner_key(self):
        self.join()
        open("page.md", "w").write("# Answer\n\n42\n")
        rc, out = self.run_cmd("publish", "page.md")
        self.assertEqual(rc, 0, out)
        self.assertIn("42", self.m.pages["vibe-agent"])

    def test_rejoin_without_key_replaces_the_page(self):
        self.join()
        self.run_cmd("leave")
        rc, out = self.join()  # key file gone: 409, then delete and publish anew
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.exists(".vibe/live-notes/owner-key"))

    def test_leave_deletes_files_and_says_cancel_the_loop(self):
        self.join()
        open(".vibe/live-notes.cursor", "w").write("c1")
        rc, out = self.run_cmd("leave")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.m.left, ["vibe-agent"])
        self.assertEqual(os.listdir(".vibe"), [])
        self.assertIn("cancel", out)

    def test_chat(self):
        self.join()
        self.assertEqual(self.run_cmd("chat", "hello", "all")[0], 0)
        self.assertEqual(self.m.chat, ["hello all"])

    def test_bad_link_refused(self):
        rc, out = self.run_cmd("join", "https://example.com/not-a-link")
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(".vibe/agent-link"))


if __name__ == "__main__":
    unittest.main()
