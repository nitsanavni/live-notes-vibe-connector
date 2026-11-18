# live-notes-vibe-connector

Wakes a Mistral Vibe agent when someone speaks in a Live Notes meeting. No polling.

A proof of concept. Rough edges: see `TODO.md`.

## Use

1. Clone this repo. Python 3 is needed.
2. Start Vibe in the repo folder and trust the folder.
3. Say: `Join the meeting with the live-notes skill. Agent link: <your link>`
4. To leave, say: `Stop following the meeting.`

`.vibe/config.toml` lets Vibe run `python live_notes.py` without asking; nothing else is added.
Never commit your agent link.

## How it works

- **Hook** (`wait_for_meeting.py`): when Vibe's turn ends, it waits up to 60 s for a meeting line and hands it to Vibe. What you type meanwhile waits at most that long. At most 3 times per turn; a 4th line waits for the loop's next turn.
- **Wakes**: only on a line with its name (`vibe-agent` or `vibe`) or addressed to it, and sends the lines before it along; `LIVE_NOTES_WAKE_ON=all` wakes on every line, or give your own words, comma-separated.
- **Loop**: starts a new turn every 30 seconds, so the hook can wait again.
- **Script** (`live_notes.py`): `join <link>`, `publish <file>`, `chat <text>`, `leave`. One command each.
- **Skill** (`.vibe/skills/live-notes`): names those commands, starts and stops the loop. No follower, no polling, no guide.

Drawings: see [docs](docs/).

## Tests

- Fast, no Vibe, no money: `python3 -m unittest` (or `test.bat`). `try_hook.bat` runs the hook once by hand.
- Real, Vibe + Mistral + a test meeting, about 1 cent: `python3 tests/real/run.py SCENARIO --out DIR`.
  It starts and ends its own meeting, checks state (files, loops, journal, Live Notes), and tears
  everything down even when the model does not. Needs `vibe` and `hc`. Scenarios: `--help`.
