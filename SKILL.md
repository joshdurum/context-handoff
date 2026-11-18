---
name: context-handoff
description: >-
  Prevent context rot and save tokens by rotating long sessions into clean new
  chats via a strict <400-word HANDOFF.md, zero-token transcript watcher hooks,
  and an autonomous fresh-session claude -p runner. Use when a conversation gets
  long (>15 turns or >40% context), hits repeated debug loops, pauses work, or
  when automating multi-batch fresh coding sessions.
---

# Context Handoff & Fresh-Session Runner (`context-handoff`)

## Role & Constraints
- **Role:** Context Efficiency & Session Continuity Engineer.
- **Constraints:**
  - Keep `HANDOFF.md` under **400 words** with all 5 required sections from [references/handoff_schema.md](./references/handoff_schema.md).
  - Always record failed fixes in **`## Dead Ends (Do Not Retry)`** so the fresh session never repeats wasted work.
  - Ground state on disk (`git status --short` + test status) before writing or resuming from `HANDOFF.md`.
  - Archive prior `HANDOFF.md` files instead of piling stale notes together.

## Mode A: Interactive Handoff (Antigravity / IDE Chat Rotation)
Run [scripts/build_handoff.py](./scripts/build_handoff.py) from this skill's directory to archive old handoffs, validate the 400-word cap, attach `git status`, and copy a 1-paste boot prompt to the macOS clipboard:
```bash
python3 <skill_dir>/scripts/build_handoff.py --project-dir <repo> --goal "..." --done "..." --dead-ends "..." --next-action "..." --copy-prompt
```
Or validate an edited `HANDOFF.md` directly:
```bash
python3 <skill_dir>/scripts/build_handoff.py --validate <path/to/HANDOFF.md>
```
Tell the user: **"Open a New Chat and paste (`Cmd+V`) to resume cleanly."**

## Mode B: Autonomous Fresh-Session Runner (`claude -p` Loop)
To run tasks across fresh, isolated `claude -p` sessions automatically with circuit breakers and token logging, see [references/handoff_schema.md](./references/handoff_schema.md) for `tasks.json` and run [scripts/loop_runner.py](./scripts/loop_runner.py):
```bash
python3 <skill_dir>/scripts/loop_runner.py --project-dir <repo> --tasks tasks.json --batch-size 2 --max-iterations 5 --max-failures 2
```

## Mode C: Zero-Token Smart-Zone Watcher Hooks
Install [hooks/smart_zone_watcher.py](./hooks/smart_zone_watcher.py) (Antigravity `PreInvocation`) and [hooks/claude_precompact_snapshot.py](./hooks/claude_precompact_snapshot.py) (Claude Code `PreCompact`) via [hooks/hooks.json.example](./hooks/hooks.json.example). Details in [references/token_math_and_hooks.md](./references/token_math_and_hooks.md).
