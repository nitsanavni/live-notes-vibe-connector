# To do

**Next** (seen on 18 Nov, Vibe run in Claude's environment)

- Lines heard before a wake, in an earlier hook run, are not sent along (only those of the same run).
- Windows: `.vibe/config.toml` allows the script for POSIX bash only, not Git Bash or PowerShell (not tested).
- `mistral-small` often tries its `run_typescript` tool before `bash` on join: 2 wasted calls.
- The cheapest model (`ministral-3b`) cannot follow the skill; `mistral-small` mostly can.

**Then**

- More hooks, so a line from the team reaches Vibe while it is working, not only when its turn ends (Nitsan, 18 Nov: not yet).
- One plugin that holds the hook, the skill and the loop.
- One prompt from the meeting sets everything up and joins.
- The link per Vibe session too: `join` runs in a shell that does not know the session id, so the link stays one file per folder.

**In Live Notes itself**

- The waker on the server: optional, off by default, wake phrases per agent.
- Serve this kit from the agent link, so an agent without the repo gets it with one download.

**Decide**

- The hook's longest wait (`LIVE_NOTES_MAX_WAIT_S`, now 60 s). Typed text waits up to that. Each silent minute costs one empty turn: about 10,600 tokens in, 2 out, 0.1 cent (18 Nov).
- Ask Mistral to make the limit of 3 wakes a setting?
