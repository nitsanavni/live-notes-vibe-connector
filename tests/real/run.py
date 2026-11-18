#!/usr/bin/env python3
"""Real tests: Vibe + mistral-small + a Live Notes test meeting. About 1 cent a run.

    python3 tests/real/run.py SCENARIO --out DIR [--link-file FILE] [--limit S] [--max-cents C]

Starts its own test meeting over HTTP (no key needed) unless --link-file names an agent link.
Teardown always runs and fails loudly if anything is left. Logs go to DIR, never the repo.
"""
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import LOOP_PROMPT, Abort, main  # noqa: E402

AGENT = "vibe-agent"


def token():
    return "T" + uuid.uuid4().hex[:6].upper()


def hook_waiting(run):
    """The hook started and has not returned yet."""
    ev = run.hook_events()
    return bool(ev) and ev[-1]["ev"] == "start"


def arm(run):
    """Link file by hand, the loop by one prompt: the hook alone, without the skill."""
    run.write_link()
    run.start_vibe()
    run.send(LOOP_PROMPT)
    if not run.wait(lambda: run.loops(), 120, "loop stored"):
        raise Abort("the model did not schedule the loop")
    run.check(True, "loop stored")
    if not run.wait(lambda: hook_waiting(run), 60, "hook waiting"):
        raise Abort("hook not waiting")


def report_lines(run, lines):
    """Posted -> hook returned -> model answered, per line, from the hook log and the journal."""
    hook = run.hook_events()
    for tok, posted in lines:
        deny = next((e for e in hook if e["ev"] == "deny" and any(tok in (t or "") for t in e["texts"])), None)
        ans = run.answered(tok)
        run.note("timing", line=tok,
                 post_to_hook_s=round(deny["t"] - posted, 2) if deny else None,
                 hook_to_answer_s=round(ans - deny["t"], 2) if deny and ans else None,
                 turn=deny and deny.get("turn_id"))
    ends = [e for e in hook if e["ev"] in ("accept", "capped")]
    for e in ends:
        nxt = next((seen for _, seen, _, _ in run.completions() if seen > e["t"]), None)
        if nxt:
            run.note("timing", turn_end_to_new_turn_s=round(nxt - e["t"], 2), ended=e["ev"])


def smoke(run):
    """Vibe answers, the hook runs and logs its stdin payload."""
    run.start_vibe()
    run.send("Reply with the word ready.")
    run.check(run.wait(lambda: any(r for _, _, r, _ in run.completions()), 90, "an answer"), "model answered")
    run.check(run.wait(lambda: run.hook_events(), 30, "hook ran"), "hook ran")
    ev = run.hook_events()
    if ev:
        run.note("hook payload", payload=ev[0].get("payload"))
        run.check(bool(ev[0].get("session_id") and ev[0].get("turn_id")), "payload has session_id and turn_id")
    hold = float(os.environ.get("REAL_HOLD_S", "0"))  # to show teardown on a kill
    if hold:
        run.note("holding", seconds=hold)
        run.wait(lambda: False, hold, "hold")


def misbehave(run):
    """The model leaves a loop and a background process; teardown must clean up."""
    run.start_vibe()
    run.send("Do two things, then reply ok. 1) " + LOOP_PROMPT.replace(" Then reply with a single dot.", "")
             + " 2) Use bash to run in the background: sleep 900 &")
    run.check(run.wait(lambda: run.loops(), 120, "loop stored"), "model left a loop")
    run.check(run.wait(lambda: any("sleep 900" in c for _, c in run.ours()), 90, "sleep running"),
              "model left a background process")


def wake4(run):
    """Bug 1: four lines in one turn; all four must reach the model, the 4th in the loop's next turn."""
    arm(run)
    lines = []
    for i in range(1, 4):
        tok = token()
        lines.append((tok, run.post("%s: test line %d %s, no answer needed" % (AGENT, i, tok))))
        if not run.wait(lambda: run.answered(tok), 90, "answer to line %d" % i):
            break
    turn = next((e["turn_id"] for e in run.hook_events() if e["ev"] == "deny"), None)
    # the 4th hook call of that turn: post while it runs (before the fix it takes the line)
    run.wait(lambda: sum(1 for e in run.hook_events() if e["ev"] == "start" and e["turn_id"] == turn) >= 4,
             60, "4th hook call")
    time.sleep(1)
    tok = token()
    lines.append((tok, run.post("%s: test line 4 %s, no answer needed" % (AGENT, tok))))
    run.wait(lambda: run.answered(tok), 150, "answer to line 4")
    for i, (tok, _) in enumerate(lines, 1):
        run.check(run.answered(tok) is not None, "line %d reached the model" % i)
    deny4 = [e for e in run.hook_events() if e["ev"] == "deny" and any(tok in (t or "") for t in e["texts"])]
    run.check(bool(deny4) and deny4[0]["turn_id"] != turn, "line 4 came in a new turn")
    sid = os.path.basename(run.session or "")
    run.check(os.path.exists(os.path.join(run.work, ".vibe", "live-notes", sid + ".cursor")),
              "cursor kept per session")
    report_lines(run, lines)


def typing(run):
    """Bug 2: text typed while the hook waits is handled within max wait + loop + margin."""
    arm(run)
    limit = float(os.environ.get("REAL_TYPE_LIMIT_S", "105"))  # 60 s hook + 30 s loop + 15 s
    tok = token()
    typed = time.time()
    run.send("Reply with the word %s and nothing else." % tok)
    run.wait(lambda: run.answered(tok), limit + 15, "typed text handled")
    ans = run.answered(tok)
    run.note("timing", typed_to_answer_s=ans and round(ans - typed, 1))
    run.check(ans is not None and ans - typed <= limit, "typed text handled within %d s" % limit)
    idle = float(os.environ.get("REAL_IDLE_S", "0"))  # watch empty loop turns, for their cost
    if ans and idle:
        n0 = len(run.completions())
        run.wait(lambda: False, idle, "idle")
        turns = run.completions()[n0:]
        use = [((r or {}).get("result", {}).get("result", {}) or {}).get("usage") or {} for _, _, r, _ in turns]
        tin = sum(u.get("input_tokens", 0) for u in use)
        tout = sum(u.get("output_tokens", 0) for u in use)
        run.note("idle cost", seconds=idle, empty_turns=len(turns),
                 tokens_in_per_turn=tin // max(1, len(turns)), tokens_out_per_turn=tout // max(1, len(turns)),
                 cents_per_idle_minute=round((tin * 0.1e-6 + tout * 0.3e-6) * 100 * 60 / idle, 3))


ALLOWED = ("vibe", "timeout --foreground", "bash -c export", "wait_for_meeting.py")


def strays(run):
    return [c for _, c in run.ours() if not any(a in c for a in ALLOWED)]


def join(run):
    """Bugs 3-5: join with the skill, answer on the page, stop. All checked in Live Notes and files."""
    link_file = os.path.join(run.work, ".vibe", "agent-link")
    run.start_vibe()
    run.send("Join the meeting with the live-notes skill. Agent link: " + run.link)
    joined = run.wait(lambda: run.loops() and any(p.get("name") == AGENT for p in run.pages())
                      and hook_waiting(run), 180, "joined")
    run.check(any(p.get("name") == AGENT for p in run.pages()), "after join: the agent's page exists")
    run.check(bool(run.loops()), "after join: the loop is stored")
    run.check(not strays(run), "after join: no background process (%s)" % strays(run))
    calls = run.tool_calls()
    run.note("tool calls", calls=[(n, a.replace(run.link, "<LINK>")[:160]) for n, a in calls])
    run.check(not any(w in a for _, a in calls for w in ("wait=", "/stream", "follow")), "no wait, stream or follower call")
    run.check(all("live_notes.py" in a for _, a in calls if run.link in a or "railway.app" in a),
              "the link is used only through live_notes.py (no guide fetched)")
    if not joined:
        raise Abort("did not join")
    tok = token()
    run.post("%s, please add the word %s to your page." % (AGENT, tok))
    run.check(run.wait(lambda: tok in run.page_text(AGENT), 150, "page changed"), "a line to the agent changed its page")
    run.wait(lambda: hook_waiting(run), 90, "hook waiting")
    if os.environ.get("REAL_ESC_FIRST", "1") == "1":
        hc_keys(run, "esc")  # until bug 2 is fixed, typing waits for the hook
    run.send("Stop following the meeting.")
    run.wait(lambda: not os.path.exists(link_file) and not run.loops() and AGENT not in run.participants(),
             150, "stopped")
    run.check(not os.path.exists(link_file), "after stop: link file gone")
    run.check(not [f for f in os.listdir(os.path.join(run.work, ".vibe")) if f.startswith("live-notes")],
              "after stop: cursor and state files gone")
    run.check(not run.loops(), "after stop: no stored loop")
    run.check(AGENT not in run.participants(), "after stop: the agent left the meeting")
    run.check(not run.prompts or run.allow_prompts, "no permission prompt")
    run.note("prompts", count=len(run.prompts))


def hc_keys(run, *keys):
    from harness import hc
    hc("keys", run.name, *keys)
    run.note("keys", keys=keys)


if __name__ == "__main__":
    main({"smoke": smoke, "misbehave": misbehave, "wake4": wake4, "join": join, "type": typing})
