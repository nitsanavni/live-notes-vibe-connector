"""Machinery for the real tests: Vibe in an hc terminal, a Live Notes test meeting, teardown.

Checks state (files, Vibe's stored loops and journal, Live Notes), never what the model says.
Standard library only. Scenarios are in run.py.
"""
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SESSIONS = os.path.expanduser("~/.vibe/logs/session/unified")
START_API = "https://notes-production-43ef.up.railway.app/api"
PRICE_IN, PRICE_OUT = 0.1e-6, 0.3e-6  # US$ per token, mistral-small as Vibe prices it
OURS = ("vibe-rs", "vibe-app-server", "vibe-background", "wait_for_meeting", "live_notes.py")
LOOP_PROMPT = ("Call the cron tool: action schedule, interval_seconds 30, and a prompt of two lines: "
               "first line 'Live Notes meeting', second line 'Nothing to do in this turn. Reply with "
               "a single dot (.) and nothing else.' Then reply with a single dot.")


class Abort(Exception):
    pass


def http(method, url, body=None, headers=None, raw=False):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    h = {"content-type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            text = r.read().decode("utf-8")
            return r.status, (text if raw else json.loads(text or "null"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def hc(*args, timeout=30):
    p = subprocess.run(["hc", *args], capture_output=True, text=True, timeout=timeout)
    return p.stdout


class Run:
    def __init__(self, out, link_file=None, limit=600, max_cents=3.0, env=None, allow_prompts=False):
        self.out = os.path.abspath(out)
        os.makedirs(self.out, mode=0o700, exist_ok=True)
        self.name = "lnv-" + uuid.uuid4().hex[:6]
        self.work = os.path.join(self.out, "work")
        self.link_file, self.limit, self.max_cents = link_file, limit, max_cents
        self.extra_env, self.allow_prompts = env or {}, allow_prompts
        self.hook_log = os.path.join(self.out, "hook.jsonl")
        self.t0 = time.time()
        self.meeting = None  # (id, host_key) when we started it
        self.link = None
        self.session = None
        self.records, self.seen, self.offsets = {}, {}, {}
        self.intents, self.results = {}, {}  # action_id -> (payload, first seen)
        self.prompts, self.last_prompt = [], 0
        self.failures = []
        self.started_vibe = False

    # --- log and checks ---
    def note(self, what, **kw):
        line = dict(t=round(time.time() - self.t0, 2), what=what, **kw)
        print(json.dumps(line), flush=True)
        with open(os.path.join(self.out, "timeline.jsonl"), "a") as f:
            f.write(json.dumps(line) + "\n")

    def check(self, ok, what):
        self.note("PASS" if ok else "FAIL", check=what)
        if not ok:
            self.failures.append(what)
        return ok

    # --- setup ---
    def setup(self):
        def ignore(d, names):
            skip = {".git", "__pycache__", "docs", "tests"}
            if os.path.basename(d) == ".vibe":
                skip |= {"agent-link", "live-notes.cursor", "live-notes"}
            return [n for n in names if n in skip]
        shutil.copytree(REPO, self.work, ignore=ignore)
        if self.link_file:
            self.link = open(self.link_file).read().strip()
        else:
            code, d = http("POST", START_API + "/meetings", {"title": "vibe connector test", "solo": True})
            if code != 201:
                raise Abort("cannot start a meeting: %s %s" % (code, d))
            self.meeting = (d["id"], d["host_key"])
            self.link = d["agent_url"]
            with open(os.path.join(self.out, "meeting.secret"), "w") as f:  # for a human, if all else fails
                os.chmod(f.name, 0o600)
                f.write(json.dumps({"id": d["id"], "host_key": d["host_key"], "link": self.link}))
        if not self.link.endswith("/"):
            self.link += "/"
        self.note("meeting", started_here=bool(self.meeting))

    def start_vibe(self):
        env = {"MISTRAL_API_KEY": "proxy-injected", "LIVE_NOTES_HOOK_LOG": self.hook_log}
        env.update(self.extra_env)
        exports = " ".join("%s=%s" % (k, _q(v)) for k, v in env.items())
        cmd = "export %s; exec timeout --foreground %d vibe --trust" % (exports, self.limit + 30)
        hc("run", "--bg", "--no-notify", "--name", self.name, "--cwd", self.work, "--", "bash", "-c", cmd)
        self.started_vibe = True
        self.wait(lambda: "Type /help" in self.screen() or ">" in self.screen(), 30, "Vibe ready")
        self.note("vibe started", terminal=self.name)

    def write_link(self):
        with open(os.path.join(self.work, ".vibe", "agent-link"), "w") as f:
            f.write(self.link + "\n")

    # --- Vibe's screen ---
    def screen(self):
        return hc("read", self.name, "--lines", "0")

    def send(self, text):
        end = time.time() + 60
        while '"started":true' not in hc("send", self.name, text, timeout=90):  # still starting: nothing typed
            if time.time() > end:
                raise Abort("hc send kept failing")
            time.sleep(1)
        self.note("typed", text=text.replace(self.link, "<LINK>")[:120])

    # --- Vibe's journal ---
    def find_session(self):
        for meta in glob.glob(os.path.join(SESSIONS, "*", "meta.json")):
            try:
                m = json.load(open(meta))
            except (OSError, ValueError):
                continue
            if m.get("environment", {}).get("working_directory") == self.work:
                return os.path.dirname(meta)
        return None

    def poll_journal(self):
        if not self.session:
            self.session = self.find_session()
            if not self.session:
                return
            self.note("session", id=os.path.basename(self.session))
        now = time.time()
        for f in sorted(glob.glob(os.path.join(self.session, "journal", "*.jsonl"))):
            try:
                with open(f) as fh:
                    fh.seek(self.offsets.get(f, 0))
                    chunk = fh.read()
            except OSError:
                continue
            done = chunk.rfind("\n") + 1
            self.offsets[f] = self.offsets.get(f, 0) + len(chunk[:done].encode())
            for line in chunk[:done].splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("sequence") in self.records:
                    continue
                self.records[r.get("sequence")] = r
                self.seen[r.get("sequence")] = now
                p = r.get("payload", {})
                if r.get("type") == "action_intent" and p.get("kind") == "completion":
                    self.intents[p["action_id"]] = (json.dumps(p), now)
                elif r.get("type") == "action_result" and p.get("action_id") in self.intents:
                    self.results[p["action_id"]] = (p, now)

    def completions(self):
        """[(intent text, intent seen, result payload or None, result seen)], oldest first."""
        out = []
        for aid, (text, seen) in sorted(self.intents.items(), key=lambda x: x[1][1]):
            res = self.results.get(aid)
            out.append((text, seen, res[0] if res else None, res[1] if res else None))
        return out

    def tool_calls(self):
        calls = []
        for _, _, res, _ in self.completions():
            for part in ((res or {}).get("result", {}).get("result", {}) or {}).get("parts", []):
                if part.get("type") == "tool_call":
                    calls.append((part.get("name"), part.get("arguments_json") or ""))
        return calls

    def usage(self):
        tin = tout = 0
        for _, _, res, _ in self.completions():
            u = ((res or {}).get("result", {}).get("result", {}) or {}).get("usage") or {}
            tin += u.get("input_tokens", 0)
            tout += u.get("output_tokens", 0)
        return tin, tout, (tin * PRICE_IN + tout * PRICE_OUT) * 100

    def answered(self, token):
        """When the model's first answer after the input holding token was seen, or None.

        Completion requests do not inline the text; the hook's result or the typed command does.
        """
        first = next((q for q in sorted(self.records) if token in json.dumps(self.records[q])), None)
        if first is None:
            return None
        for q in sorted(self.records):
            r = self.records[q]
            if q > first and r.get("type") == "action_result" and r["payload"].get("action_id") in self.intents:
                return self.seen[q]
        return None

    def loops(self):
        try:
            return json.load(open(os.path.join(self.session, "scheduled-loops.json"))).get("loops", [])
        except (OSError, ValueError, TypeError):
            return []

    # --- the hook's log ---
    def hook_events(self):
        try:
            return [json.loads(l) for l in open(self.hook_log)]
        except (OSError, ValueError):
            return []

    # --- Live Notes ---
    def post(self, text):
        t = time.time()
        code, d = http("POST", self.link + "chat?name=tester", {"text": text})
        if code != 200:
            raise Abort("post failed: %s %s" % (code, d))
        self.note("posted", text=text)
        return t

    def pages(self):
        code, d = http("GET", self.link + "pages?name=tester")
        return d.get("pages", []) if code == 200 else []

    def page_text(self, name):
        code, d = http("GET", self.link + "pages/%s?name=tester" % name, headers={"accept": "text/markdown"}, raw=True)
        return d if code == 200 else ""

    def participants(self):
        code, d = http("GET", self.link + "participants?name=tester")
        return [a["name"] for a in d.get("agents", [])] if code == 200 else []

    # --- waiting ---
    def tick(self):
        if time.time() - self.t0 > self.limit:
            raise Abort("time limit %d s" % self.limit)
        self.poll_journal()
        s = self.screen() if self.started_vibe else ""
        if "Allow once" in s and time.time() - self.last_prompt > 2:
            self.last_prompt = time.time()
            self.prompts.append(s)
            self.note("permission prompt", allowed=self.allow_prompts, screen=_prompt_text(s))
            if not self.allow_prompts:
                raise Abort("permission prompt on screen")
            hc("keys", self.name, "enter")
        if "Trust folder" in s:
            hc("keys", self.name, "enter")
        cents = self.usage()[2]
        if cents > self.max_cents:
            raise Abort("price limit: %.2f cents" % cents)

    def wait(self, cond, timeout, what):
        end = time.time() + timeout
        while time.time() < end:
            self.tick()
            v = cond()
            if v:
                return v
            time.sleep(0.5)
        self.note("timeout", waiting_for=what, after_s=timeout)
        return None

    # --- teardown ---
    def ours(self):
        """Processes this run started: cwd or command line inside our folder, or Vibe's own."""
        found = []
        for pid in os.listdir("/proc"):
            if not pid.isdigit() or int(pid) == os.getpid():
                continue
            try:
                cmd = open("/proc/%s/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode()
                cwd = os.readlink("/proc/%s/cwd" % pid)
            except OSError:
                continue
            if cwd.startswith(self.work) or self.work in cmd or any(o in cmd for o in OURS):
                found.append((int(pid), cmd.strip()[:100]))
        return found

    def teardown(self):
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(s, signal.SIG_IGN)
        signal.alarm(0)
        problems = []
        try:
            self.poll_journal()
        except Exception:
            pass
        if self.started_vibe:
            hc("kill", self.name)
            end = time.time() + 10
            while time.time() < end and self.ours():
                time.sleep(0.5)
        for pid, _ in self.ours():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        time.sleep(0.5)
        for d in [self.session] if self.session else []:
            for f, key in (("scheduled-loops.json", "loops"), ("meta.json", "loops")):
                p = os.path.join(d, f)
                try:
                    data = json.load(open(p))
                    if data.get(key):
                        data[key] = []
                        json.dump(data, open(p, "w"), indent=2)
                except (OSError, ValueError):
                    pass
        vibe_dir = os.path.join(self.work, ".vibe")
        for p in glob.glob(os.path.join(vibe_dir, "agent-link")) + glob.glob(os.path.join(vibe_dir, "live-notes*")):
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        if self.meeting:
            code, _ = http("POST", START_API + "/end", {"id": self.meeting[0], "hostKey": self.meeting[1]})
            if code != 200:
                problems.append("meeting not ended (HTTP %s)" % code)
            else:
                os.remove(os.path.join(self.out, "meeting.secret"))
        # verify
        left = self.ours()
        if left:
            problems.append("processes left: %s" % left)
        if self.name in hc("ls"):
            problems.append("hc terminal %s still live" % self.name)
        if self.session and self.loops():
            problems.append("stored loops left")
        if glob.glob(os.path.join(vibe_dir, "agent-link")) + glob.glob(os.path.join(vibe_dir, "live-notes*")):
            problems.append("link or cursor files left")
        if self.meeting:
            code, d = http("GET", self.link + "feed?name=tester")
            if code == 200 and not d.get("ended_at"):
                problems.append("meeting still live")
        if os.path.isdir(self.work):
            shutil.rmtree(self.work, ignore_errors=True)
        tin, tout, cents = self.usage()
        self.note("teardown", problems=problems, tokens_in=tin, tokens_out=tout, cents=round(cents, 3),
                  completions=len(self.intents))
        if problems:
            print("TEARDOWN FAILED: %s" % problems, file=sys.stderr, flush=True)
        return problems


def _q(v):
    return "'" + str(v).replace("'", "'\\''") + "'"


def _prompt_text(s):
    """The lines of a permission prompt above its choices, without the box."""
    lines = [l.strip(" \u2502\u250c\u2510\u2500") for l in s.splitlines()]
    i = next((n for n, l in enumerate(lines) if "Allow once" in l), len(lines))
    return " | ".join(l for l in lines[max(0, i - 8):i] if l)


def main(scenarios):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scenario", choices=sorted(scenarios))
    ap.add_argument("--out", required=True, help="folder for logs, outside the repo")
    ap.add_argument("--link-file", help="use this meeting's agent link instead of starting one")
    ap.add_argument("--limit", type=int, default=600, help="whole-run limit, seconds")
    ap.add_argument("--max-cents", type=float, default=3.0)
    ap.add_argument("--allow-prompts", action="store_true", help="press Allow once on permission prompts")
    ap.add_argument("--env", action="append", default=[], help="KEY=VALUE for Vibe and the hook")
    a = ap.parse_args()
    run = Run(a.out, a.link_file, a.limit, a.max_cents, dict(e.split("=", 1) for e in a.env), a.allow_prompts)

    def on_signal(sig, _):
        raise Abort("signal %d" % sig)
    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, on_signal)
    signal.signal(signal.SIGALRM, on_signal)
    signal.alarm(a.limit + 60)
    error = None
    try:
        run.setup()
        scenarios[a.scenario](run)
    except Abort as e:
        error = str(e)
        run.note("aborted", reason=error)
    except Exception as e:
        error = "%s: %s" % (type(e).__name__, e)
        run.note("error", reason=error)
    finally:
        problems = run.teardown()
    ok = not (error or run.failures or problems)
    run.note("RESULT", ok=ok, failures=run.failures, error=error)
    sys.exit(0 if ok else (3 if problems else 1))
