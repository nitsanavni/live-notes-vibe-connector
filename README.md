# live-notes-vibe-connector

Connects the Mistral Vibe harness to a Live Notes meeting, so a Vibe agent is woken when someone in the meeting talks to it.

## The idea

Vibe passes nothing to the model while it is idle, so today a Vibe agent has to poll the meeting (a line can wait up to 30 seconds).

Instead: a hook that runs when the agent is about to stop. The hook does not return; it waits on the meeting's event stream. When a line for the agent arrives, the hook returns it and tells the agent not to stop, so the agent takes another turn.

## Status

Nothing built yet. First question: does Vibe have a stop hook that can block and can refuse the stop?
