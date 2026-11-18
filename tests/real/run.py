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
    report_lines(run, lines)


if __name__ == "__main__":
    main({"smoke": smoke, "misbehave": misbehave, "wake4": wake4})
