#!/usr/bin/env python3
"""Vibe post_agent hook: block while idle, wake the agent when a Live Notes line arrives.

Prints {"decision":"deny","reason":...} (Vibe then continues the turn with the
reason) or nothing (Vibe accepts the turn). Standard library only.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

POLL_S = 25
STOP_CODES = (401, 403, 404, 410)  # revoked / gone: accept the turn


class Stop(Exception):
    """Meeting ended, agent revoked, or max wait reached: print nothing."""


def get(link, name, after, wait, timeout):
    q = {"name": name, "wait": str(wait)}
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


def who(ev):
    f = ev.get("from")
    if isinstance(f, dict):
        return str(f.get("name") or f.get("id") or "?")
    return str(f or "?")


def is_wake(ev, me):
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
        + "\nAnswer what is addressed to you on your meeting page; "
        "otherwise do nothing and end your turn."
    )


def run(env=None, sleep=time.sleep, clock=time.monotonic):
    env = os.environ if env is None else env
    try:
        sys.stdin.read()
    except Exception:
        pass
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
    name = env.get("LIVE_NOTES_AGENT_NAME", "vibe-agent")
    cfile = env.get("LIVE_NOTES_CURSOR_FILE", os.path.join(".vibe", "live-notes.cursor"))
    try:
        max_wait = float(env.get("LIVE_NOTES_MAX_WAIT_S", "1500"))
    except ValueError:
        max_wait = 1500.0
    poll = int(env.get("LIVE_NOTES_POLL_S", POLL_S))
    deadline = clock() + max_wait
    backoff = 1.0
    cursor = load_cursor(cfile)

    try:
        while True:
            if clock() >= deadline:
                raise Stop()
            try:
                if cursor is None:
                    d = get(link, name, None, 1, 30)
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
            wake = [e for e in d.get("events") or [] if is_wake(e, name)]
            if wake:
                save_cursor(cfile, nxt)
                print(json.dumps({"decision": "deny", "reason": build_reason(wake)}))
                return 0
            if nxt != cursor:
                cursor = nxt
                save_cursor(cfile, cursor)
            if d.get("ended_at"):
                raise Stop()
    except Stop:
        return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as e:  # never a traceback on stdout; accept the turn
        print("live-notes: fatal: %s" % e, file=sys.stderr)
        sys.exit(0)
