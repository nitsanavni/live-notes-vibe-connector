# The loop prompt

The hook wakes Vibe at most 3 times in one turn. After that the turn ends and
nobody is waiting on the meeting. The loop starts a new turn, and at the end of
that turn the hook waits again.

Paste this into Vibe, as one line:

```
/loop every 30 seconds Check the Live Notes meeting. Read the new lines. If a line is addressed to you, answer it on your meeting page. If not, do nothing and end your turn.
```

30 seconds is the shortest interval Vibe allows.

To see the loops that run: `/loop list`

To stop: `/loop cancel all`

## Not tested yet

- What Vibe does when the loop fires while the hook is still waiting at the end
  of a turn. It may queue the prompt, or it may cut the wait short.
- The words after "every": Vibe reads them as plain language ("every 30
  seconds", "every two minutes"). If it refuses, try "every thirty seconds".
