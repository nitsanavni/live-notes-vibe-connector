import io
import json
import os
import re
import shutil
import subprocess
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
            q = parse_qs(u.query)
            feed.queries.append((u.path, q))
            # Refuse what the real service refuses (seen 18 November 2026).
            if not q.get("name") or q["name"][0] in ("agent", "your-name", "claude", "codex"):
                r = (400, {"error": "name needed"})
            elif "wait" in q and "after" not in q:
                r = (400, {"error": "wait needs after=<cursor>"})
            elif "wait" in q and not 1 <= int(q["wait"][0]) <= 30:
                r = (400, {"error": "wait is 1-30"})
            else:
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
            "LIVE_NOTES_WAKES_FILE": os.path.join(self.dir, "w.wakes"),
            "LIVE_NOTES_MAX_WAIT_S": "5",
            "LIVE_NOTES_POLL_S": "1",
            "LIVE_NOTES_WAKE_ON": "all",
        }

    def tearDown(self):
        self.srv.shutdown()

    def run_hook(self, payload=None, **env):
        e = dict(self.env, **env)
        out, err = io.StringIO(), io.StringIO()
        old = sys.stdin
        sys.stdin = io.StringIO(json.dumps(payload or {}))
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

    def test_fourth_wake_in_a_turn_takes_nothing(self):
        # Vibe ignores a 4th deny in one turn: the line it carried would be lost.
        os.makedirs(os.path.dirname(self.cf))
        open(self.cf, "w").write("c5")
        self.feed.responses = [(200, {"next": "c%d" % i, "events": [speech(i, text="line %d" % i)]})
                               for i in range(6, 11)]
        turn = {"session_id": "s1", "turn_id": "t1"}
        for i in range(6, 9):
            self.assertIn("line %d" % i, json.loads(self.run_hook(turn))["reason"])
        asked = len(self.feed.queries)
        self.assertEqual(self.run_hook(turn), "")
        self.assertEqual(len(self.feed.queries), asked)  # did not read
        self.assertEqual(open(self.cf).read(), "c8")  # did not move the cursor
        out = self.run_hook({"session_id": "s1", "turn_id": "t2"})  # the loop's next turn
        self.assertIn("line 9", json.loads(out)["reason"])

    def test_waits_at_most_60_s_by_default(self):
        # Typed text waits while the hook waits: end the turn after a minute; the loop re-arms it.
        self.assertEqual(w.max_wait({}), 60.0)
        self.assertEqual(w.max_wait({"LIVE_NOTES_MAX_WAIT_S": "300"}), 300.0)
        self.assertEqual(w.max_wait({"LIVE_NOTES_MAX_WAIT_S": "soon"}), 60.0)

    @unittest.skipUnless(os.path.exists("/bin/sh"), "needs a POSIX shell")
    def test_hook_command_runs_with_python3_only(self):
        here = os.path.dirname(os.path.abspath(__file__))
        cmd = re.search(r'^command = "(.*)"', open(os.path.join(here, ".vibe", "hooks.toml")).read(), re.M).group(1)
        bin_dir = os.path.join(self.dir, "bin")
        os.makedirs(bin_dir)
        os.symlink(shutil.which("python3") or sys.executable, os.path.join(bin_dir, "python3"))
        os.makedirs(os.path.dirname(self.cf))
        open(self.cf, "w").write("c5")
        self.feed.responses = [(200, {"next": "c6", "events": [speech(6, text="hi")]})]
        env = dict(self.env, PATH=bin_dir)
        p = subprocess.run(["/bin/sh", "-c", cmd], cwd=here, env=env, input="{}", capture_output=True,
                           text=True, timeout=30)
        self.assertEqual(json.loads(p.stdout)["decision"], "deny", p.stderr)

    def test_wakes_only_on_its_name_by_default(self):
        os.makedirs(os.path.dirname(self.cf))
        open(self.cf, "w").write("c5")
        self.feed.responses = [(200, {"next": "c6", "events": [speech(6, text="lunch at one?")]}),
                               (200, {"next": "c7", "events": [speech(7, text="Vibe, what was that?")]})]
        out = self.run_hook(LIVE_NOTES_WAKE_ON="")
        reason = json.loads(out)["reason"]
        self.assertIn("Vibe, what was that?", reason)
        self.assertIn("lunch at one?", reason)  # earlier line, as context
        self.assertEqual(open(self.cf).read(), "c7")

    def test_no_wake_without_its_name(self):
        os.makedirs(os.path.dirname(self.cf))
        open(self.cf, "w").write("c5")
        self.feed.responses = [(200, {"next": "c6", "events": [speech(6, text="vibes are good today")]})]
        self.assertEqual(self.run_hook(LIVE_NOTES_WAKE_ON="", LIVE_NOTES_MAX_WAIT_S="2"), "")
        self.assertEqual(open(self.cf).read(), "c6")

    def test_wakes_on_to_or_mention(self):
        os.makedirs(os.path.dirname(self.cf))
        open(self.cf, "w").write("c5")
        self.feed.responses = [(200, {"next": "c6", "events": [speech(6, text="and you?", to=["vibe-agent"])]})]
        self.assertIn("and you?", json.loads(self.run_hook(LIVE_NOTES_WAKE_ON=""))["reason"])

    def test_missing_link_accepts(self):
        self.assertEqual(self.run_hook(LIVE_NOTES_AGENT_LINK=""), "")


if __name__ == "__main__":
    unittest.main()
