---
name: legacy-slice
description: |
  레거시 PHP의 백엔드 부분을 슬라이스 단위로 Spring/Kotlin에 이관하고, 이관 전후 동작이
  같은지와 도메인 로직이 실제로 다 옮겨갔는지를 각각 다른 방법으로 검증한다.
  PHP 파악 → e2e 기준선 → 설계 → 구현 → PHP 스왑 → 동등성 → 완전성 감사 → 문서화까지
  오케스트레이션한다.
  "슬라이스 마이그레이션", "PHP 백엔드 옮기기", "이 기능 Spring으로", "마이그레이션 시작",
  "레거시 슬라이스", "고객센터 마이그레이션", "동등성 검증" 등에 트리거.
  슬라이스를 고르기만 하려면 slice-scout, 이미 끝난 슬라이스를 다시 감사하려면
  boundary-audit, 문서만 갱신하려면 domain-doc 을 쓴다.
---

# Legacy slice migration

Move one slice of a legacy PHP service's backend into Spring/Kotlin without changing
what the screen does, and prove both halves of that claim.

## Why two proofs

An e2e suite answers *does it still behave the same?* It cannot answer *did the domain
logic actually move?* — because when PHP still computes a rule and the backend is never
asked, the observable outcome is identical and every test stays green. A slice can be
fully green and half migrated.

So this skill runs two independent oracles, and a slice is done only when both pass:

| 오라클 | 묻는 것 | 방법 | 실패의 의미 |
|---|---|---|---|
| **동등성** | 동작이 같은가 | 같은 e2e spec을 토글 off/on 양쪽에서 실행 | 이관이 틀렸다 |
| **완전성** | 다 옮겨갔는가 | 스왑 후 두 저장소를 다시 읽어 규칙별로 대조 | 이관이 덜 됐다 |

Both join on the **behavior ledger** — the numbered list of every rule the slice
enforces, produced in Phase 1. Read `references/ledger-format.md` before Phase 1.

## 현재 환경

!`bash "$CLAUDE_PROJECT_DIR/.claude/skills/legacy-slice/status.sh"`

## 상수

Everything environment-specific lives in `.claude/config/workspace.json` (gitignored).
Read it in Phase 0. **This repository is public — never write a path, hostname, table
name, or identifier from the company checkouts into a tracked file here.** Slice
artifacts are written into the backend repository's docs root, not into this one.

## 루프 지도

Four loops, each closing on a different invariant. Know which one you are in.

| 루프 | 어디 | 닫히는 조건 | 상한 | 넘으면 |
|---|---|---|---|---|
| **L0 이해** | Phase 1 | 레드팀이 새 규칙을 못 찾음 (2회 연속) | 3회 | 원장을 사람에게 보이고 판단 요청 |
| **L1 구현** | Phase 4 | 빌드·단위·아키텍처 테스트 green | 5회 | 설계 결함 의심 — Phase 3으로 |
| **L2 동등성** | Phase 6 | 토글 off/on 양쪽 green | 5회 | 원인 요약 후 사람에게 |
| **L3 완전성** | Phase 7 | 감사 PASS | 3회 | 잔여 항목 명시하고 사람에게 |

Quality comes from where the loops are placed, not from their count. L0 is early and
cheap: a rule caught there costs one re-read, the same rule caught in L3 costs a
redesign. Spend generously in L0.

---

## Phase 0 — 준비

1. Read `.claude/config/workspace.json`. If missing, tell the user to copy the example
   and stop.
2. Fix the slice. If the user named one, use it. If not, invoke `slice-scout` — do not
   pick one yourself; the choice depends on risk and dependencies the user knows.
3. Create the slice directory under `<docs.root>/<docs.slicesDir>/<slice-id>/`.
4. Bring the environment up per the status block, using `local-stack`.

## Phase 1 — 이해 (L0 루프)

`Agent(subagent_type: "php-behavior-analyst")` with the slice id, surface, entry
points, and the ledger path.

Then the loop:

```
round = 1
until (red team returns empty twice in a row) or round > 3:
    Agent(subagent_type: "php-rule-redteam")  ← ledger + same entry points
    merge findings into the ledger yourself (the red team does not write)
    round += 1
```

Merging is yours because the red team must stay independent of the artifact it attacks.
When merging a classification challenge, apply the rubric in `references/ledger-format.md`
rather than deferring to either agent — in particular, a rule enforced only on screen
is `도메인` that has not moved, not `경계`.

**Do not skip the second empty round.** One empty result often means the red team
looked in the same places the analyst did; the second round is what makes "we found
nothing" mean something.

## Phase 2 — 기준선 (동등성 오라클을 세운다)

`Agent(subagent_type: "e2e-baseline-author")` with the ledger and the e2e config.

The spec must be green **against the local surface with the toggle off** before you go
on. This green run is the baseline: everything after is measured against it. A spec
that has never been green proves nothing later.

Record which ledger rows came back `불가` — those are invisible to the equivalence
oracle, and Phase 7 has to carry them.

## Phase 3 — 설계 → ★ 게이트 1

`Agent(subagent_type: "backend-slice-designer")` with the ledger.

Then **stop and get human approval.** Present:

- the resource/API shape and why it is not shaped like the screen
- the 규칙 배치표, and specifically any `도메인` row left unplaced
- the decisions the designer flagged for pushback
- known-wrong behavior being deliberately reproduced

Do not proceed on silence. This gate exists because everything after it is expensive to
undo, and because a design reviewed by the person who knows the product catches things
no amount of code reading will.

## Phase 4 — 구현 (L1 루프)

`Agent(subagent_type: "backend-slice-implementer")` with the approved design.

The agent self-corrects until the build is green. Your job is to check *what* went
green: read the diff for domain logic that landed in the data-layer module, and for any
change to the architecture test itself. A build made green by relaxing its own
constraint is a regression disguised as progress.

## Phase 5 — 스왑 → ★ 게이트 2

**Stop and get human approval before any edit to the legacy tree.** This is live
production code. Present:

- the exact methods to be swapped and their ledger IDs
- how to flip the toggle and how to flip it back
- what a failure looks like in production and how it is reverted

Then `Agent(subagent_type: "php-swap-engineer")`.

## Phase 6 — 동등성 (L2 루프)

Run the same spec twice, flipping only the toggle:

```
toggle = legacy   → run spec → must be green   (baseline still holds)
toggle = migrated → run spec → must be green   (equivalence)
```

Run the legacy pass every time, not just once. A green migrated pass means nothing if
the baseline drifted underneath it — live data changes, and a spec that started
depending on today's rows will mislead you in both directions.

On failure, diagnose before dispatching:

| 증상 | 원인 | 담당 |
|---|---|---|
| 두 패스 모두 red | 기준선이 깨짐 — 데이터 변화 또는 취약한 assertion | e2e author |
| off green / on red, 값이 다름 | 도메인 규칙 누락 또는 오역 | implementer (원장 ID 지목) |
| off green / on red, 모양이 다름 | 반환 형태 불일치 (키·타입·빈 값 처리) | swap engineer |
| on 패스가 즉시 실패 | 토글이 PHP에 도달하지 않음 | swap engineer (배선 확인) |
| 순서만 다름 | 정렬 규칙 누락 | implementer |
| 간헐적 실패 | 테스트가 살아있는 데이터에 의존 | e2e author |

**Never fix a failure by weakening the spec.** If an assertion looks wrong, the ledger
row behind it is what to re-examine — the assertion is downstream of a claim about
behavior, and it is the claim that is either right or wrong.

## Phase 7 — 완전성 (L3 루프)

`Agent(subagent_type: "domain-boundary-auditor")`.

This is the check nothing else performs. Expect FAIL on a first slice; the common
finding is a rule computed in the page script *before* the swapped method is called,
which the swap leaves completely untouched and the e2e suite cannot see.

Route each finding and re-enter at that phase:

| 감사 판정 | 되돌아갈 곳 |
|---|---|
| 미이관 / 부분이관 | Phase 4 (설계에 있었다면) 또는 Phase 3 (없었다면) |
| 잘못된 위치 | Phase 4 |
| 호출부 잔존 / 매핑 잔존 | Phase 5 |
| 새로 발견된 규칙 | Phase 1 — 원장에 추가하고 아래로 다시 흐른다 |
| 무방비 | Phase 4 (백엔드 단위 테스트 추가) |

A re-entry re-runs the phases below it, including Phase 6. That is the cost of an
incomplete migration, and it is why L0 deserves the budget.

## Phase 8 — 문서 & 보고

`Agent(subagent_type: "domain-scribe")` with the ledger and the audit.

Then report to the user:

- ledger row counts by classification and final 이관 state
- both oracle results, with the commands that produced them
- the domain document path and its open questions — some are product decisions only
  the user can make, so surface them rather than burying them in a file
- the toggle's current state, and the command to roll back

Leave the toggle **off** unless the user explicitly asked to leave it on. Ending a
session with an unreviewed code path live in a production service is not the
orchestrator's call to make.

---

## 품질 감시

Check these yourself; agents are not trusted to self-report.

- [ ] 원장의 모든 `도메인` 행에 `이관됨:<심볼>` 또는 사람이 승인한 `잔류합의`가 있다
- [ ] `불가` 행마다 백엔드 단위 테스트가 인용돼 있다
- [ ] 아키텍처 테스트가 이번 슬라이스에서 수정되지 않았다
- [ ] e2e에 요청 가로채기·직접 fetch·하드코딩 반환이 없다
- [ ] 컨테이너를 내리면 e2e가 실패한다 (통과하면 아무것도 검증하지 않는 것)
- [ ] 레거시 원본 메서드가 이름만 바뀌고 내용은 그대로다
- [ ] 레거시 파일 인코딩이 편집 전후로 동일하다
- [ ] 이 저장소의 추적 파일에 회사 경로·호스트·테이블명이 들어가지 않았다
