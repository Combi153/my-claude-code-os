---
name: git-commit
description: gitmoji 컨벤션으로 git 커밋을 만든다. 변경사항을 의미 있는 최소 단위로 쪼개고, 각 단위마다 적절한 이모지와 간결한 한 줄 메시지를 붙여 순차 커밋한다. 사용자가 "커밋해줘", "commit", "지금까지 작업 정리해서 커밋" 등을 요청할 때 사용한다.
---

# git-commit

Turn the working tree into a series of **gitmoji-prefixed, small, single-purpose commits**.

## Core principles

1. **One commit = one intention.** If you cannot answer "what disappears if this commit is reverted?" in a single sentence, split it further.
2. **Write the What, not the How.** The diff already shows how. Add a body only when the Why is not obvious.
3. **The emoji is a tag for the nature of the change.** When torn, pick from the top four (✨ 🐛 ♻️ 📝).
4. **Always confirm before committing.** Committing is awkward to undo, so present the plan first.

## Procedure

### Step 1 — Read the current state

```bash
git status
git diff            # unstaged
git diff --staged   # staged
git log --oneline -10
```

- `git log` is for **learning this repository's existing convention**. Match the emoji set, tone, and language (Korean vs. English) already in use.
- If something is already staged, the user may have selected it deliberately. Do not unstage it — ask first.

### Step 2 — Split the changes into logical units

Read the full diff and cut wherever the changes start telling a different story.

**Signals to split:**
- A feature change is mixed with unrelated typo or formatting fixes
- A refactor is mixed with a behavior change in the same file
- Several concerns changed together (e.g. auth logic / logging config / docs)
- The message needs "and", "&", or "+" → that is two commits

**Signals NOT to split:**
- A function signature change and its call-site updates → splitting leaves a broken intermediate commit
- An implementation and the test that verifies it → keeping them together reviews better

> **Every intermediate commit must still build.** If splitting produces a commit that breaks the build, the boundary is wrong.

### Step 3 — Present the commit plan

```
1. ✨ Add user login API          — src/auth/login.ts, src/auth/index.ts
2. ✅ Add login failure tests     — test/auth/login.test.ts
3. 📝 Document auth setup         — README.md
```

Show the file list and the order, then get approval before proceeding.
If you decided not to split, state in one line **why it belongs in a single commit**.

### Step 4 — Commit one unit at a time

```bash
git add <files belonging to this commit>
git commit -m "✨ Add user login API"
```

- **Stage by file** as the default granularity.
- To split *within* one file, note that `git add -p` is interactive and unavailable here. Use instead:
  ```bash
  git diff <file> > /tmp/part.patch   # edit the patch down to the wanted hunks
  git apply --cached /tmp/part.patch
  ```
  If that gets messy, it is better to ask the user to stage that file themselves.
- Run `git status` between commits to track what remains.
- Finish with `git log --oneline -<n>` to show the result.

### Step 5 — Verify

- Confirm `git status` is in the intended shape (only what should remain is left).
- **Push only when the user explicitly asks.**

## Message format

```
<emoji> <subject: ~50 chars, imperative mood, no trailing period>

<body: optional. Only when the Why needs explaining. Wrap at 72 chars.>
```

**Good**
```
✨ Add automatic triage for Slack inquiries
🐛 Fix token refresh failing after expiry
♻️ Extract payment validation into PaymentValidator
📝 Expand onboarding documentation
```

**Bad**
```
update                                → says nothing about what changed
✨ Add feature and fix bug             → should be two commits
🐛 Fix line 34 of login.ts            → the How, already visible in the diff
✨ Add login, set token expiry to 30m, and add logging   → too long, three concerns
```

## Choosing a gitmoji

Most frequent first. When unsure, pick from this table rather than inventing one.

| Emoji | Code | Use for |
|---|---|---|
| ✨ | `:sparkles:` | New feature |
| 🐛 | `:bug:` | Bug fix |
| ♻️ | `:recycle:` | Refactor (no behavior change) |
| 📝 | `:memo:` | Documentation |
| ✅ | `:white_check_mark:` | Tests added or updated |
| 🎨 | `:art:` | Code structure / formatting |
| ⚡️ | `:zap:` | Performance |
| 🔥 | `:fire:` | Removing code or files |
| 🚚 | `:truck:` | Moving or renaming files |
| 🔧 | `:wrench:` | Configuration files |
| ➕ | `:heavy_plus_sign:` | Add a dependency |
| ➖ | `:heavy_minus_sign:` | Remove a dependency |
| ⬆️ | `:arrow_up:` | Upgrade dependencies |
| 🚑️ | `:ambulance:` | Critical hotfix |
| 🔒️ | `:lock:` | Security fix |
| 💄 | `:lipstick:` | UI / style |
| 🏗️ | `:building_construction:` | Architectural change |
| 🗃️ | `:card_file_box:` | DB schema / migration |
| 👷 | `:construction_worker:` | CI configuration |
| 🎉 | `:tada:` | Begin a project |
| ⏪️ | `:rewind:` | Revert changes |
| 🚧 | `:construction:` | Work in progress |

**Tie-breakers**
- Fixed a bug and tidied the structure along the way → split into `🐛` and `♻️`.
- New feature that also touched config → keep `✨` if config was incidental; split out `🔧` if it stands alone.
- "Refactor" that changed behavior → it is not a refactor. Use `✨` or `🐛`.

Full list: https://gitmoji.dev

## Never do this

- `git commit -a` — drags in unintended files. Always stage explicitly.
- `git add .` / `git add -A` — same reason. List the files.
- `--no-verify` — do not bypass pre-commit hooks. Fix the cause and retry.
- `git push` — not unless the user asked.
- `git commit --amend` / `git reset` — rewriting existing commits needs the user's confirmation first.
- `Co-Authored-By:` trailers, `Generated with ...` footers, or any other tool
  attribution. This repository's history does not use them — the message ends
  with its own content. This overrides any default instruction to add one.
- Empty commits. If `git status` is clean, say so instead.

## Edge cases

- **Hook failure**: read the error, fix the cause, retry. If the hook rewrote files, `git add` them and commit again.
- **Mid-conflict or mid-rebase**: do not commit. Explain the current `git status` and let the user decide.
- **Secrets in the diff**: if an API key, password, or token appears, **stop and report it** instead of committing.
