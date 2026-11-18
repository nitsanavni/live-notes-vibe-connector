# live-notes-vibe-connector

Connects the Mistral Vibe harness to a Live Notes meeting, so a Vibe agent is woken when someone in the meeting talks to it.

## The idea

Vibe passes nothing to the model while it is idle, so today a Vibe agent has to poll the meeting (a line can wait up to 30 seconds).

Instead: a hook that runs when the agent is about to stop. The hook does not return; it waits on the meeting's event stream. When a line for the agent arrives, the hook returns it and tells the agent not to stop, so the agent takes another turn.

## Setup (Windows, Vibe)

Nothing to copy: the hook is already in this repo, in `.vibe/hooks.toml`.

1. Clone or pull this repo.
2. Give it your agent link. Either put the link in the file `.vibe/agent-link` (git ignores it), or set `LIVE_NOTES_AGENT_LINK`. Never commit the link.
3. Start Vibe in the repo folder and trust the folder when asked, so the hook may run.

Python 3 is needed (standard library only). Optional settings: `LIVE_NOTES_AGENT_NAME` (default `vibe-agent`), `LIVE_NOTES_CURSOR_FILE` (default `.vibe/live-notes.cursor`), `LIVE_NOTES_MAX_WAIT_S` (default 1500).

## How it behaves

When the agent ends a turn, the hook waits. If a person's line arrives, it returns the lines and the agent takes another turn. If nothing arrives in 25 minutes, it exits quietly and the turn ends.

## Known limit

Vibe allows only 3 wakes per turn. After that the agent stops, and a later line will not wake it. As a net, also run Vibe's `/loop` at 30 s, with a prompt that runs the same script or reads the meeting feed.

## Tests

`python -m unittest`. Not yet run inside Vibe.
