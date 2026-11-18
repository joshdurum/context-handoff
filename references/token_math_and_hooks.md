# Context Rot, Cache Economics & Hooks

## 1. Why Fresh Chats Beat Bloated Sessions
- **Smart Zone vs. Dumb Zone:** LLM reasoning quality drops long before hitting hard window limits (commonly around ~40% capacity or once stale error traces pile up).
- **The Cold-Cache Trap:** Active sessions reuse Anthropic prefix caches (`0.1x` cost), **only within the ~5-minute TTL**. Stepping away from a 40k-token session lets the cache go cold, triggering a `1.25x` full-history cache rewrite on your next message.
- **Hybrid `agy` + `claude` Architecture:**
  - Every `claude -p` invocation already starts in a clean context window (`--no-session-persistence` for disposable steps, plus `--exclude-dynamic-system-prompt-sections` where supported to improve prefix caching).
  - Long-lived interactive **Antigravity (`agy`)** orchestrator chats accumulate transcript bloat across planning and handoffs—so rotating `agy` via `HANDOFF.md` keeps both orchestrator reasoning sharp and prompts sent to `claude` compact.

## 2. Hook Mechanics
- **Antigravity (`PreInvocation`):** `hooks/smart_zone_watcher.py` reads `invocationNum`, `transcriptPath` bytes, and recent `ERROR` steps (content-rot loop detection: `>=3` errors in the last `6` steps) at `$0` API cost. Once any threshold trips, it emits an `injectSteps` notice once per cooldown window using `metadata.user_markdown`.
- **Claude Code (`PreCompact`):** `hooks/claude_precompact_snapshot.py` reads `transcript_path` on `stdin` before compaction erases details and saves recent user prompts + edited file paths to `.handoffs/precompact_backup.md`.
