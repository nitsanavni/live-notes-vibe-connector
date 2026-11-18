# live-notes-vibe-connector

Wakes a Mistral Vibe agent when someone speaks in a Live Notes meeting. No polling.

A proof of concept. Rough edges: see `TODO.md`.

## Use

1. Clone this repo. Python 3 is needed.
2. Start Vibe in the repo folder and trust the folder.
3. Say: `Join the meeting with the live-notes skill. Agent link: <your link>`
4. To leave, say: `Stop following the meeting.`

Never commit your agent link.

## How it works

- **Hook** (`wait_for_meeting.py`): when Vibe's turn ends, it waits for a meeting line and hands it to Vibe. At most 3 times per turn.
- **Loop**: starts a new turn every 30 seconds, so the hook can wait again.
- **Skill** (`.vibe/skills/live-notes`): joins, starts the loop, leaves.

## Drawings

Click to see them rendered:

- [All drawings](https://htmlpreview.github.io/?https://github.com/nitsanavni/live-notes-vibe-connector/blob/main/docs/drawings/index.html)
- [1. The parts](https://htmlpreview.github.io/?https://github.com/nitsanavni/live-notes-vibe-connector/blob/main/docs/drawings/1-parts.html)
- [2. Join](https://htmlpreview.github.io/?https://github.com/nitsanavni/live-notes-vibe-connector/blob/main/docs/drawings/2-join.html)
- [3. Follow](https://htmlpreview.github.io/?https://github.com/nitsanavni/live-notes-vibe-connector/blob/main/docs/drawings/3-follow.html)
- [4. Leave](https://htmlpreview.github.io/?https://github.com/nitsanavni/live-notes-vibe-connector/blob/main/docs/drawings/4-leave.html)

## Check without Vibe

`try_hook.bat` runs the hook once by hand. `test.bat` runs the unit tests.
