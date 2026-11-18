# context-handoff — Project Instructions & Verification Gates

## Stack Overview
- **Primary Stack:** Python 3 (standard library only, zero external dependencies), Markdown (`SKILL.md`), JSON (`tasks.json`, `hooks.json`).
- **Target Ecosystem:** Hybrid Antigravity (`agy` orchestrator) + Claude Code (`claude -p` fresh-session executor), standalone GitHub-ready skill repo.

## Key Files (Read Before Editing)
- [SKILL.md](./SKILL.md) — Core skill instructions loaded on trigger.
- [references/handoff_schema.md](./references/handoff_schema.md) — Strict `<400`-word `HANDOFF.md` and `tasks.json` schemas.
- [references/token_math_and_hooks.md](./references/token_math_and_hooks.md) — Context rot, cache TTL economics, and hook integration notes.

## Working Rules
- Keep `SKILL.md` under 180 lines; keep `HANDOFF.md` strictly under 400 words.
- Keep all scripts pure Python stdlib with built-in circuit breakers (`max_iterations`, `max_failures`, `max_budget_usd`) so loops can never run away.

## Verification Gates
Run these exact commands before marking any change complete:
- **Test:** `python3 -m unittest discover -s tests -v`
- **Syntax Check:** `python3 -m compileall -q scripts hooks tests`
