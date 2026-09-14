---
name: legacy-migrate
description: |
  레거시 PHP의 백엔드 부분을 페이지 하나씩 Spring/Kotlin에 이관하고, 이관 전후 값이
  같은지와 도메인 로직이 실제로 다 옮겨갔는지를 각각 다른 방법으로 검증한다.
  교체 지점 추출 → 규칙 목록 → 설계 변경분 → 실패하는 테스트 → 구현·배선 → 자동 검사 →
  완전성 판정까지 오케스트레이션한다.
  "페이지 마이그레이션", "PHP 백엔드 옮기기", "이 기능 Spring으로", "마이그레이션 시작",
  "교체 지점 추출", "서비스 함수로 빼줘", "이중 실행", "동등성 검증",
  "완전성 판정", "다 옮겨갔는지 확인" 등에 트리거.
  옮길 페이지를 고르기만 하려면 page-picker, 캡처·비교만 하려면 page-baseline,
  이중 실행 배선·불일치 보고만 하려면 dual-run, 이미 끝난 페이지를 다시 판정하려면
  domain-leftover, 문서만 갱신하려면 domain-doc 을 쓴다.
---

# Legacy page migration

Move one swap point's worth of a legacy PHP backend into Spring/Kotlin without changing what the screen does, and prove both halves of that claim. Why there are two separate checks, and the rule list's column contract, are in the injected context. The design rationale is `docs/legacy-migration-os.md` (section 1.6 is v3); the canonical format is `references/rules-format.md`.

The static completeness checks each see one layer, so adding a layer adds a blind spot. **Fake-value injection is layer-independent** — if replacing the wrapper's legacy return value with a fake value in `migrated` mode leaves the screen unchanged, that value came from the backend.

## Current state

!`bash "${CLAUDE_PROJECT_DIR:-.}/.claude/skills/legacy-migrate/status.sh"`

## The unit of work and its outputs

**The unit of work is one swap-point function, which is one page.** The caller sweep is still mandatory, but it is **input to the area API design**, not a work list — each page swaps at its own swap point, so moving one page leaves every other caller running the legacy body.

Every environment value comes from `.claude/config/workspace.json`. **If a key is missing, stop and say which one.** This repository is public, so no tracked file carries a company path, host, port, table name or person's name. Outputs are written under `<docs.root>`.

| Where | What |
|---|---|
| Page | `state.json` · `00-swap-point.md` · `01-rules.jsonl` · `02-design-changes.md` · `04-completeness.md` · `questions.md` · `observations.json` · `body-hashes.json` · `ignore.json` · `captures/` · `regressions/` |
| Area (shared by several pages) | The area design · the domain document · per-role round records |

The canonical list is `references/artifacts.json`. **Do not make agents memorise filenames — pass absolute paths in the prompt.** Progress is held by `state.json`'s `phase`, and the state block above prints that along with loop rounds, caps and the toggle. A session ending at an approval point is normal, so resume from that line, and say so before entering one.

`depth` lives in `state.json` and is passed to every subagent. **Recheck rounds default to 0**; turn one on when a later phase finds a rule missing from the list and can show the evidence.

## Loops and approval points

| Loop | Phase | Closes when | Cap |
|---|---|---|---|
| L0 extraction | 1 | Every capture identical **and** zero lint violations | 3 |
| Coverage | 2 | Every statement range in the body carries a rule ID | 2 |
| L1 implementation | 4b | Build and architecture rules green **and the Phase 4a tests pass unedited** | 5 |
| L2 equivalence | 5 | `pagecheck` stages 3–6 pass | 5 |
| L3 completeness | 6 | Every automatic check passes **and** the verdict is PASS | 3 |

**The caps are values in `state.json` and `pagecheck` increments them. On reaching one, stop and report to a person — this is a different device from an approval point and it is never delegated.**

There are three places a person stops the run, each one page long: **the asking phase** (0.5) · **the plan approval** (Phase 1, before any edit) · **the design approval** (after Phase 3). Do not proceed on silence at any of them. A re-entry that does not change the plan does not pass the plan approval again; a re-entry through Phase 3 passes the design approval again.

---

## Phase 0 — preparation

1. Read `workspace.json`. If it is missing, say to copy the example and stop.
2. Pick the page. If the user named one, use it; otherwise call `page-picker` — do not pick one yourself.
3. Take the **caller sweep** with `phpmove callers <symbol>`. Callers you are not moving this time go in the `Swap risk` section of `00-swap-point.md` — a caller using the same method under the exact opposite contract has actually occurred.
4. Create the page directory and `state.json` (the format is in section 1.6 of the design document). If they exist already, **resume**.
5. `pagecheck <page-dir> --stage 1,2` — four environment checks and the **run-to-run difference measurement**. Exit 3 means "the check could not run" and is not a pass.

**`ignore.json` starts from that run-to-run difference.** A list guessed before anyone knows the real diff paths hides real defects. Entries added later **must point at an approved rule ID**.

## Phase 0.5 — asking (★ human)

The design needs information the code does not contain. Pull the open questions out of the page into `questions.md` and get answers from a person. Ask three things: **who uses this feature and why · which of the observed behaviours is intent versus defect, where only a person knows · which rules may stay on the screen.** Answers accumulate per area, so the second page in the same area asks fewer questions.

Write anything unanswered explicitly as `모른다` and **do not enter Phase 3 in that state.** Without that block, a guess goes in, and a guess is written into the rule list as fact.

## Phase 1 — swap-point extraction (★ plan approval · L0)

`Agent(subagent_type: "php-swap-extractor")`, `mode: plan`. Pass: the page's absolute path · the target methods · the **absolute paths** of the page directory, `00-swap-point.md`, `observations.json`, `body-hashes.json` and the round record · depth · **"write the plan only and stop, do not edit any file"**. Require `## Summary` of 20 lines as the first section and a final response under 300 words.

**Put the plan in front of a person** — the edit plan's line ranges (guard, parse, move, bind) · the function signature · the blockers and their handling · the observation list · the normalization rules · the caller sweep. After approval, instruct the same agent again with `mode: extract` and it runs L0 by itself.

```
htmlsnap capture (before) → phped edit → phpmove lint → capture (after)
                          → htmlsnap compare   (until identical, cap 3)
                          → phpmove hash       (record the moved body's byte hash)
```

**This phase's check is the baseline capture.** There is no backend yet and there is exactly one thing to confirm: that a refactor inside PHP did not change the screen. A capture flagged `logged_out` or `error_page` cannot be a baseline — an unauthenticated response arrives as 200, and two logged-out screens are always identical.

## Phase 2 — the rule list (coverage)

`Agent(subagent_type: "php-behavior-analyst")`. Pass: the absolute paths of `00-swap-point.md`, `01-rules.jsonl`, `references/rules-format.md`, `questions.md` and the round record · the page · the target methods · depth.

One JSONL line is one rule and each column has one owner. The analyst writes `rule`, `class`, `src` and `range`, and leaves `obs` as `대기`. Coverage closes when **every statement range in the body carries a rule ID**.

**Classification and ID assignment are the orchestrator's job** (append-only). The rubric is the canonical format, and in particular a rule enforced only on the screen is not `경계` but `도메인` that has not moved. Fill `obs` after the observation list is settled — anything whose required input can be planted becomes `이중실행:` or `기준캡처:`, and only what cannot be planted becomes `불가:<kind>`. **Writing `불가` early stops inputs being planted that could have been.**

## Phase 3 — the design change set → ★ design approval

`Agent(subagent_type: "backend-designer")`. Pass: the absolute paths of the rule list, `02-design-changes.md`, `00-swap-point.md`, `questions.md`, **the area design** and the round record · depth.

**The designer reads the area design and writes only what these rules change in it.** Resource shape, error mapping, authorization and layer placement live in the area document and barely move by the second page in the same area. When one must move, revise the area document in place and record that fact in the change set. **Read `backend.architectureRules` from the living file** — those rules have been reversed once already after the first run.

Four sections are mandatory: **rule placement** · **absence check** (transactions, validation, authorization, idempotency, error mapping, a slow or failing call to another service — each resolving to a new rule row or "not applicable, with a reason") · **the correction table** (per defect: correct or preserve, a concrete input, the legacy value and the corrected value) · **suspected mismatches** (each carrying a rule ID). Decisions to push back on go in too.

**A person reads at the design approval**: the resource shape and why it is not the screen's shape · placement (especially any unplaced `도메인` row) · the whole correction table · defects being deliberately preserved · the decisions to push back on. Approval lands on the rule row as approver and date, and Phase 6 reads that row and only passes it when the reason is there. **At the approval point, check yourself that every suspected mismatch has a rule row** — a suspicion recorded only in the design has no way to become an observation, and the checks pass green straight over it.

For every approved correction, prepare an `ignore.json` entry and change `obs` to `제외:의도수정`. Leave it and an intended correction is caught as an unexpected mismatch, and the only thing the implementer receiving it back can do is undo the approved correction.

## Phase 4a — the failing tests

`Agent(subagent_type: "backend-test-author")`. Pass: the absolute paths of the approved design change set, the rule list, the backend repository root and the round record · `page-id` · depth. It writes no production code.

**The agent that writes an assertion is never the agent that makes it pass** (D-32). **Keep two things from the return**: the unresolved references it names, which is how 4b's red is told apart from red the builder caused, and the **test file paths**, on which 4b's closing condition is measured. A row it could not turn into an assertion goes back to Phase 2 or to the asking phase, not into 4b.

## Phase 4b — implementation and wiring (L1 · automatic checks)

**One** `Agent(subagent_type: "backend-builder")` does the backend implementation and the swap-point wiring together. Pass: the absolute paths of the approved design change set, the rule list, `00-swap-point.md`, `ignore.json`, `body-hashes.json`, the regression inputs, **the Phase 4a test files** and the round record · depth.

They were merged because nobody was reading the schema's fields and the adapter's requested fields together, and that gap was unwatched. Independence of judgment is carried by the separation from the completeness checker, and that separation is enforced through tool permissions.

Five things must pass before it ends. **A failure is the agent's to fix; it does not come to a person.**

```
build · unit tests · architecture rules
phpmove check --hashes body-hashes.json          # legacy body, zero bytes changed
phpmove lint <page.php>                          # page inside the allowed shape
phpmove callers <symbol> --allow-file <swap>     # no callers outside the swap point
phpmove fields --adapter <adapter> --rules <rules>   # the schema comes from config
```

**Then run `git -C <backend.root> diff --stat --` on the Phase 4a test files yourself.** A green build has two possible causes — the code became right, or the assertion became easier — and only that diff separates them, so a non-empty one means the loop did not close. An expectation the builder argues is genuinely wrong goes to the rule row and its approver, never to the agent whose build it blocks.

What you look at otherwise is **what** went green. Whether a decision got into the BFF (a resolver that filters, sorts or sets a default means the wrong module was chosen) · whether a domain rule was hardcoded into a query adapter (conditions must arrive at the adapter already complete) · **whether the architecture rules themselves changed** (a build made green by loosening a constraint is a regression disguised as progress) · whether the rule IDs reported as passing cover every row Phase 4a said it had written a test for.

## Phase 5 — automatic checks (L2)

```
pagecheck <page-dir> --stage 3..7
```

Dual · migrated · **fake-value injection** · legacy body execution · restore. **The orchestrator reads only the numbers.** Only this script touches the toggle, and it reads the value back from the application every time — writing a value and that value reaching PHP are different things. Exit 0 pass · 1 red · 3 **the check could not run**. Do not read 3 as a pass.

If it is red, **read `references/routing.md`, settle on a cause, then dispatch.** That file holds the symptom–cause–owner table and the rule against weakening a check. Freeze samples of unexpected mismatches with `dualrun-report --as-regressions` and **pass that path to the next builder dispatch.**

## Phase 6 — completeness (L3)

Call `Agent(subagent_type: "domain-placement-checker")` only when `pagecheck` is green. Asking a checker a question a machine can answer is expensive, and the answer comes back dressed as judgment. Pass: the full automatic-check output and the `phpmove lint --template` output (for reporting; exit 0) · the absolute paths of the rule list, the design change set, `00-swap-point.md`, `04-completeness.md` and the round record · depth.

There are six verdict words and **the canonical list is the checker's file alone**. A word not in that table is not a verdict but a signal that the two files have drifted — do not route it, report that fact. Where each verdict goes back to, and the rules for re-passing an approval point, are in **`references/routing.md`**.

## Phase 7 — closing

1. **Round records.** Confirm each agent left `{lesson, trigger, evidence, scope}` in its role's record. An entry without `evidence` is not an entry — there is a measurement showing that unevidenced self-reflection makes the harness worse. **Do not read the contents.** Only check that the file appeared.
2. **Context change set.** From the evidenced entries, propose a change set against `.claude/context/*.md` as `{Add, Merge, Revise, Skip}`, and **a person approves it via `git diff`.** Do not rewrite wholesale. Prose that a mechanism replaces is deleted in the same change set.
3. **Zero unresolved OS defects.** Do not carry a tool or hook defect found this round into the next unit. A defect the checks caught becomes a regression input; an OS defect becomes a selftest case. Carrying one forward postpones the learning that makes rounds shorter.
4. Call the scribe **every N pages**. Pass `Agent(subagent_type: "domain-scribe")` the rule list, the completeness report and **the absolute path of the area domain document**, and have it revise that document in place — the moment two documents describe the same area, the single source of truth is dead.
5. Report to the user: row counts by classification and by migration state · the results of both checks, equivalence and completeness, with **the commands that produced them** · the six axes in `state.json` · the regression input path · open product decisions from the domain document · **the toggle's final state and the command to revert it**.

**End with the toggle on `legacy`.** Leaving an unreviewed code path live at the end of a session is not the orchestrator's decision to make.

---

## Orchestrator discipline

1. **Do not read legacy files yourself.** If it feels like you must, that is work for an agent. **One exception**: you may read to confirm a specific question an agent did not answer, but **leave what you read as an artifact.** The problem is not the reading, it is the evaporation.
2. **Do not read an artifact whole.** Read only the first section's `## Summary`, 20 lines. If the summary cannot support a judgment, do not open the artifact — send it back to that agent to fix the summary.
3. **Require every agent's final response to be under 300 words.**
4. **A session ending at an approval point is normal.** Resume from the state block. Do not accumulate state in the conversation.
5. **Do not ask an agent a question a machine can answer.** Hashes, lint, callers and fields are answered by `phpmove`; screen identity by `htmlsnap`; the check procedure by `pagecheck`. What is left for an agent is classification, placement and judgment.
6. **Break a new check deliberately before trusting it.** Watch it go red, then put it back.
