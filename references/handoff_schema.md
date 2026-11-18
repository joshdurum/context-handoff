# `HANDOFF.md` & `tasks.json` Schemas

## 1. Strict `HANDOFF.md` Schema (Max 400 Words)

Keep `HANDOFF.md` under 400 words so a fresh chat boots in the **Smart Zone** (`<1,500` total tokens with `AGENTS.md`). Every `HANDOFF.md` must contain these 5 exact headings:

```markdown
# Session Handoff

## Goal
1-2 sentences stating the concrete target for the project.

## Verified Done
- Exact items confirmed by passing tests or files on disk.

## Dead Ends (Do Not Retry)
- Failed fixes, incompatible APIs, or rejected ideas so the next session never repeats them (write `None yet` if empty).

## Active Files
- `path/to/file.py` — short role description

## Next Exact Action
1 concrete next task, batch, or verification command to run first.
```

## 2. `tasks.json` Schema (For Autonomous `loop_runner.py`)

Store backlog tasks in JSON rather than Markdown checklists so automated loops cannot rewrite or merge criteria accidentally.

```json
{
  "project": "adhd-capture-mvp",
  "tasks": [
    {
      "id": "T1",
      "title": "Build SQLite capture store",
      "prompt": "Create store.py with init_db(), add_note(text), and list_notes() using stdlib sqlite3.",
      "verify_cmd": "python3 -c \"import store; store.init_db(':memory:')\"",
      "status": "pending",
      "attempts": 0
    },
    {
      "id": "T2",
      "title": "Add unit tests for capture store",
      "prompt": "Create test_store.py testing add_note and list_notes, then run unittest.",
      "verify_cmd": "python3 -m unittest test_store.py -v",
      "status": "pending",
      "attempts": 0
    }
  ]
}
```

### Task Status Transitions
- `"pending"` -> eligible for the next fresh `claude -p` session.
- `"done"` -> both `claude -p` exited `0` and `verify_cmd` (if set) exited `0`.
- `"blocked"` -> hit `max_failures` consecutive failures (circuit breaker trips; error recorded in `HANDOFF.md` under `Dead Ends`).
