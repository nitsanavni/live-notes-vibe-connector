# To do

Things we may need. Not ordered, not promised. Add freely.

## Setup

- An install script (Peter, 18 Nov). Earlier the same day Peter said "no
  installer, just put it in the right folder", so decide what the script would
  do beyond what the repo already holds.
- Turn the hook on and off. It should be active only while the agent is
  following a meeting, not all the time (Nitsan). Today it stays quiet when
  there is no `.vibe/agent-link` file or the meeting has ended, but there is no
  switch.
- Turn the loop on and off together with the hook. First try: the skill
  `live-notes` (start writes the link file and schedules the loop with the
  `cron` tool; stop cancels the loop and deletes the link file). Try it in Vibe.
- Combine the invitation with the setup: Vibe knows nothing about Live Notes
  until it has read the agent link. `loop-prompt.md` has a first try.
- The agent link in the repo: Nitsan wanted it committed for now ("it's not a
  secret"); Claude's session refused to commit it. Open.

## The hook

- When nothing is addressed to it, Vibe should answer with a dot only, not
  "not addressed to me, ending my turn" (Peter, 18 Nov). The skill and the
  hook now ask for that; see whether Vibe obeys.

- One link file means one meeting for the whole folder (Nitsan, 18 Nov: "it
  should be per Vibe session instead of a singleton file"). Two Vibe sessions
  in the same folder would share the link and the cursor. Make both per
  session; first find out whether Vibe tells a hook which session it runs in.

- It wakes on every line, so the 3 wakes per turn are used up in seconds.
  Options: wake only on the agent's name; use the service's Save tokens mode;
  use a small model as a waker (the "Jev waker").
- The limit of 3 wakes per turn is a constant in Vibe
  (`_MAX_POST_AGENT_RETRIES`), not a setting. Ask Mistral to make it a setting,
  or live with it through the loop.
- The loop must not fire while the hook is still waiting (Peter: a possible
  race). Vibe's `cron` tool says its prompts "run only while the session is
  live and you are idle", so it should hold back; whether a turn that waits in
  the hook counts as busy is read from the source, not tested. Test it.
- The unit tests print a warning about files that were not closed (seen on
  Peter's machine). Not looked at.
- `test.bat` and `try_hook.bat` were written on Linux and run only on Peter's
  machine.

## In the Live Notes service (not this repo)

- The waker on the server: optional, off by default, and each agent can set
  its own wake phrases through an endpoint, as with the vocabulary. Who pays
  for the model is open.
- Vibe does not handle MCP notifications, and the Live Notes connector sends
  none; a hook was the way around it.

## Later

- A retro at the end of each session.
