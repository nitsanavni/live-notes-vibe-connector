# live-notes-vibe-connector

Connects the Mistral Vibe harness to a Live Notes meeting, so a Vibe agent is woken when someone in the meeting talks to it.

## The idea

Vibe passes nothing to the model while it is idle, so today a Vibe agent has to poll the meeting (a line can wait up to 30 seconds).

Instead: a hook that runs when the agent is about to stop. The hook does not return; it waits on the meeting's event stream. When a line for the agent arrives, the hook returns it and tells the agent not to stop, so the agent takes another turn.

## Setup (Windows, Vibe)

1. Copy `wait_for_meeting.py` into your project folder. Copy the `[[hooks]]` entry from `hooks.toml.example` into your Vibe `hooks.toml`.
2. Set the agent link. Use your own link, and never commit it.

   PowerShell:

   ```
   $env:LIVE_NOTES_AGENT_LINK = "https://HOST/a/YOUR-CODE/"
   ```

   bash:

   ```
   export LIVE_NOTES_AGENT_LINK="https://HOST/a/YOUR-CODE/"
   ```

   Optional: `LIVE_NOTES_AGENT_NAME` (default `vibe-agent`), `LIVE_NOTES_CURSOR_FILE` (default `.vibe/live-notes.cursor`), `LIVE_NOTES_MAX_WAIT_S` (default 1500).
3. Start Vibe in that folder and trust the folder when asked, so the hook may run.
4. Python 3 is needed. The script uses only the standard library.

## How it behaves

When the agent ends a turn, the hook waits. If a person's line arrives, it returns the lines and the agent takes another turn. If nothing arrives in 25 minutes, it exits quietly and the turn ends.

## Known limit

Vibe allows only 3 wakes per turn. After that the agent stops, and a later line will not wake it. As a net, also run Vibe's `/loop` at 30 s, with a prompt that runs the same script or reads the meeting feed.

## Tests

`python -m unittest`. Not yet run inside Vibe.
