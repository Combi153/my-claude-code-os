---
name: skill-stat
description: 이 프로젝트에서 어떤 Claude 스킬이 몇 번, 어떤 맥락에서 사용됐는지 통계로 보여준다. 사용자가 "스킬 통계", "스킬 사용 현황", "어떤 스킬을 많이 썼는지", "/skill-stat" 등을 요청할 때 사용한다.
---

# skill-stat

Report how the skills in this project are actually being used, from the append-only
log that `.claude/hooks/log-skill-usage.py` writes on every `Skill` tool call.

## Where the data comes from

- Log file: `.claude/skill-usage.jsonl` — one JSON object per skill invocation.
- Fields: `ts`, `skill`, `trigger` (`user` = called as `/name`, `auto` = the model
  chose it), `args`, `context` (the user message that preceded the call), `session`, `cwd`.
- The log only grows from sessions started **after** the hook was registered. If it
  looks empty or short, say so rather than treating it as "the skills are unused".

## Procedure

### Step 1 — Run the aggregator

```bash
python3 .claude/skills/skill-stat/stat.py --recent 8
```

Useful variants — pick the one that matches what was asked:

| Ask | Command |
|---|---|
| Everything (default) | `stat.py` |
| Last week / month | `stat.py --since 7d` · `stat.py --since 30d` |
| Since a date | `stat.py --since 2026-08-01` |
| One skill's history | `stat.py --skill git-commit --recent 20` |
| Just this session | `stat.py --session <session_id>` |
| Raw data to post-process | `stat.py --json` |

Do not re-implement the aggregation with ad-hoc `jq`/`grep` — the script is the
single source of truth for how counts are derived.

### Step 2 — Show the table, then read it

Print the script output as-is inside a code block, then add a short interpretation.
The numbers alone are not the deliverable; the point is what they say about the setup:

- **A skill with 0 or near-0 calls** — either it is not needed, or its `description`
  does not match the words the user actually types. Check the description before
  concluding it is dead weight.
- **`auto` calls dominate** — the description is triggering well.
- **`user` calls dominate** — the model is not picking it up on its own; the
  `description` frontmatter probably needs the user's real phrasing added.
- **One skill used far more than the rest** — a candidate for splitting into
  narrower skills, or for hardening (its failure modes matter most).
- **Repeated `context` phrasings across calls** — those exact phrases belong in the
  skill's `description`.

Keep the interpretation to a few lines. Only raise a concrete suggestion when the
data supports it; when there is too little data, say that instead of inventing a trend.

### Step 3 — Offer the next step, do not take it

If the data suggests a `description` change, name the skill and the phrasing you
would add, and ask before editing. Never edit another skill as part of reporting stats.

## Edge cases

- **Log file missing** — the hook has not run yet. Confirm `.claude/settings.json`
  registers the `Skill` matcher and remind the user that hooks load at session start,
  so a session restart is needed after registering it.
- **Malformed lines** — the script skips them silently. If counts look wrong, check
  the tail of the raw log with `tail -3 .claude/skill-usage.jsonl`.
- **Multiple projects** — the log is per-project by design; numbers from another
  repository are not in here.
