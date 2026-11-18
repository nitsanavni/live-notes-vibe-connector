#!/usr/bin/env python3
"""Vibe post_agent hook: block while idle, wake the agent when a Live Notes line arrives.

Prints {"decision":"deny","reason":...} (Vibe then continues the turn with the
reason) or nothing (Vibe accepts the turn). Standard library only.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

POLL_S = 25
CONTEXT = 12  # lines delivered with a wake at most: the line that names the agent and those before it
MAX_WAKES = 3  # Vibe ignores a 4th deny in one turn (_MAX_POST_AGENT_RETRIES)
STOP_CODES = (401, 403, 404, 410)  # revoked / gone: accept the turn


class Stop(Exception):
    """Meeting ended, agent revoked, or max wait reached: print nothing."""


def get(link, name, after, wait, timeout):
    q = {"name": name}
    if wait is not None:
        q["wait"] = str(wait)
    if after:
        q["after"] = after
    url = link.rstrip("/") + "/feed?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in STOP_CODES:
            raise Stop()
        raise


def load_cursor(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def save_cursor(path, cursor):
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(cursor))
    except OSError as e:
        print("live-notes: cannot save cursor: %s" % e, file=sys.stderr)


def max_wait(env):
    """Longest wait in one hook run. Typed text waits meanwhile; the loop re-arms the hook."""
    try:
        return float(env.get("LIVE_NOTES_MAX_WAIT_S", "60"))
    except ValueError:
        return 60.0


def wakes_used(path, turn):
    """Wakes already given in this turn: the file holds '<turn id> <count>'."""
    try:
        with open(path, encoding="utf-8") as f:
            t, n = f.read().split()
        return int(n) if t == turn else 0
    except (OSError, ValueError):
        return 0


def who(ev):
    f = ev.get("from")
    if isinstance(f, dict):
        return str(f.get("name") or f.get("id") or "?")
    return str(f or "?")


def wake_words(env, me):
    """None: wake on every line. Default: the agent's name and its first part (vibe-agent, vibe)."""
    v = env.get("LIVE_NOTES_WAKE_ON", "").strip()
    if v.lower() == "all":
        return None
    if v:
        return [w.strip().lower() for w in v.split(",") if w.strip()]
    return sorted({me.lower(), me.split("-")[0].lower()})


def calls_me(ev, me, words):
    if me.lower() in [str(n).lower() for n in (ev.get("to") or []) + (ev.get("mentions") or [])]:
        return True
    text = str(ev.get("text")).lower()
    return any(re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(w), text) for w in words)


def is_line(ev, me):
    if ev.get("type") not in ("speech", "chat"):
        return False
    if ev.get("in_scope") is False:
        return False
    if who(ev).lower() == me.lower():
        return False
    return bool(ev.get("text"))


def fmt_time(at):
    s = str(at or "")
    if "T" in s:
        s = s.split("T", 1)[1]
    return s[:8] or "--:--:--"


def build_reason(events):
    lines = ["%s %s: %s" % (fmt_time(e.get("at")), who(e), e.get("text")) for e in events]
    return (
        "New lines from the Live Notes meeting:\n"
        + "\n".join(lines)
        + "\nAnswer what is addressed to you on your page: write .vibe/live-notes/page.md, then run "
        "python live_notes.py publish .vibe/live-notes/page.md (skill live-notes). "
        "Otherwise reply with a single dot (.) and nothing else."
    )


def read_payload():
    try:
        d = json.loads(sys.stdin.read() or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def log(env, ev, **kw):
    """One JSON line per hook step, only when LIVE_NOTES_HOOK_LOG names a file (tests)."""
    path = env.get("LIVE_NOTES_HOOK_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(t=time.time(), ev=ev, pid=os.getpid(), **kw)) + "\n")
    except OSError:
        pass


def run(env=None, sleep=time.sleep, clock=time.monotonic):
    env = os.environ if env is None else env
    payload = read_payload()
    log(env, "start", session_id=payload.get("session_id"), turn_id=payload.get("turn_id"),
        payload={k: v for k, v in payload.items() if k != "response_text"})
    link = env.get("LIVE_NOTES_AGENT_LINK", "").strip()
    if not link:
        try:
            with open(os.path.join(".vibe", "agent-link"), encoding="utf-8") as f:
                link = f.read().strip()
        except OSError:
            pass
    if not link:
        print("live-notes: no agent link (LIVE_NOTES_AGENT_LINK or .vibe/agent-link)", file=sys.stderr)
        return 0
    name = env.get("LIVE_NOTES_AGENT_NAME") or load_cursor(os.path.join(".vibe", "live-notes", "name")) or "vibe-agent"
    cfile = env.get("LIVE_NOTES_CURSOR_FILE", os.path.join(".vibe", "live-notes.cursor"))
    wfile = env.get("LIVE_NOTES_WAKES_FILE", os.path.join(".vibe", "live-notes.wakes"))
    turn = str(payload.get("turn_id") or "")
    used = wakes_used(wfile, turn) if turn else 0
    if used >= MAX_WAKES:
        # Leave the line for the loop's next turn, where a deny counts again.
        log(env, "capped", turn_id=turn)
        return 0
    longest = max_wait(env)
    poll = int(env.get("LIVE_NOTES_POLL_S", POLL_S))
    deadline = clock() + longest
    backoff = 1.0
    cursor = load_cursor(cfile)
    words = wake_words(env, name)
    heard = []

    try:
        while True:
            if clock() >= deadline:
                raise Stop()
            try:
                if cursor is None:
                    # Boot call: no wait, the server rejects wait without after.
                    d = get(link, name, None, None, 30)
                    if d.get("ended_at"):
                        raise Stop()
                    cursor = d.get("cursor") or d.get("next")
                    if cursor is not None:
                        save_cursor(cfile, cursor)
                    continue
                left = max(1, min(poll, int(deadline - clock())))
                d = get(link, name, cursor, left, left + 15)
                backoff = 1.0
            except Stop:
                raise
            except Exception as e:  # network, bad JSON: retry
                print("live-notes: %s; retrying" % e, file=sys.stderr)
                sleep(min(backoff, max(0.0, deadline - clock())))
                backoff = min(backoff * 2, 30.0)
                continue
            nxt = d.get("next") or d.get("cursor") or cursor
            lines = [e for e in d.get("events") or [] if is_line(e, name)]
            heard = (heard + lines)[-CONTEXT:]
            if lines and (words is None or any(calls_me(e, name, words) for e in lines)):
                wake = heard
                save_cursor(cfile, nxt)
                if turn:
                    save_cursor(wfile, "%s %d" % (turn, used + 1))
                print(json.dumps({"decision": "deny", "reason": build_reason(wake)}))
                log(env, "deny", turn_id=payload.get("turn_id"), texts=[e.get("text") for e in wake])
                return 0
            if nxt != cursor:
                cursor = nxt
                save_cursor(cfile, cursor)
            if d.get("ended_at"):
                raise Stop()
    except Stop:
        log(env, "accept", turn_id=payload.get("turn_id"))
        return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as e:  # never a traceback on stdout; accept the turn
        print("live-notes: fatal: %s" % e, file=sys.stderr)
        sys.exit(0)
