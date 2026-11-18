# To do

**Next** (seen on 18 Nov, Vibe run in Claude's environment)

- You cannot type to Vibe while the hook waits (up to 25 minutes).
- The skill does not say how to publish a page or answer in the meeting.
- The Live Notes guide says "use the follower", the skill says "do not poll". Likely the hang.
- Fewer wakes: the hook wakes Vibe on every line.
- The cheapest model (`ministral-3b`) cannot follow the skill; `mistral-small` mostly can.

**Then**

- More hooks, so a line from the team reaches Vibe while it is working, not only when its turn ends (Nitsan, 18 Nov: not yet).
- One plugin that holds the hook, the skill and the loop.
- One prompt from the meeting sets everything up and joins.
- Link and cursor per Vibe session, not one file per folder.

**In Live Notes itself**

- The waker on the server: optional, off by default, wake phrases per agent.

**Decide**

- Make this repo public?
- Ask Mistral to make the limit of 3 wakes a setting?
