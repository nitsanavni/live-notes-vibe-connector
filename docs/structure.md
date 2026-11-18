Hand-drawn versions of these four drawings: [drawings/index.html](drawings/index.html).

# How Vibe joins, follows and leaves a meeting

Four drawings, high level. The same parts appear in each.

## 1. The parts

```mermaid
flowchart LR
  subgraph PC["Peter's machine"]
    P([Peter])
    V["Vibe (the agent)"]
    S["skill: live-notes"]
    H["hook: wait_for_meeting.py"]
    C["loop (cron tool)"]
    L[".vibe/agent-link (file)"]
  end
  subgraph LN["Live Notes service"]
    F["meeting feed"]
    PG["agent's page"]
  end
  M([People in the meeting])

  P -- "join the meeting" --> V
  V -- reads --> S
  S -- writes --> L
  S -- starts --> C
  H -- needs --> L
  H -- "waits for lines" --> F
  H -- "hands lines over" --> V
  C -- "starts a new turn" --> V
  V -- answers --> PG
  M -- talk --> F
  M -- read --> PG
```

## 2. Join

```mermaid
sequenceDiagram
  actor P as Peter
  participant V as Vibe
  participant LN as Live Notes
  P->>V: "join the meeting" + agent link
  V->>V: skill: write .vibe/agent-link
  V->>LN: GET agent link
  LN-->>V: connection instructions
  V->>LN: publish page as vibe-agent
  V->>V: cron: schedule the loop, every 30 s
  V-->>P: "I follow the meeting"
  Note over V: turn ends, the hook starts to wait
```

## 3. Follow

```mermaid
sequenceDiagram
  participant M as Meeting
  participant H as Hook
  participant V as Vibe
  participant C as Loop
  Note over V: a turn ends
  V->>H: Vibe runs the hook
  H->>M: wait for new lines (up to 25 min)
  M-->>H: a line
  H-->>V: "do not stop", with the lines
  V->>M: answer on the page
  Note over H,V: at most 3 times in one turn
  Note over V: after the 3rd, the turn really ends and nobody waits
  C->>V: within 30 s, a new turn: "nothing to do"
  Note over V: that turn ends, and the hook waits again
```

The loop fires only while Vibe is idle. While the hook waits, the turn is not
over, so the loop stays quiet.

## 4. Leave

```mermaid
sequenceDiagram
  actor P as Peter
  participant V as Vibe
  P->>V: "stop following"
  V->>V: cron: cancel the loop
  V->>V: delete .vibe/agent-link and the cursor file
  V-->>P: "stopped"
  Note over V: turn ends, the hook runs, finds no link, does nothing
```

## What is tested

Only the hook has run in Vibe. The skill, the loop next to the hook, and
leaving are written but not tried.
