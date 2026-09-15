---
name: slice-scout
description: |
  레거시 서비스에서 다음에 옮길 슬라이스를 고른다. 소유한 데이터인지, 외부 의존이 얼마인지,
  읽기 위주인지, 실패했을 때 피해 범위가 얼마인지를 실제 코드에서 확인해 후보를 순위 매긴다.
  "뭐부터 옮기지", "다음 슬라이스", "마이그레이션 대상 고르기", "어디부터 시작",
  "슬라이스 후보" 등에 트리거. 슬라이스가 정해진 뒤의 실제 이관은 legacy-slice 가 한다.
---

# Slice scout

Pick what to migrate next, from evidence in the code rather than from intuition about
which feature matters most.

## 첫 슬라이스는 도메인 가치를 고르는 게 아니다

The first slice's real output is the reusable groundwork: the domain service wired
through all four of its layers, the BFF seam in front of it, the swap pattern, the
toggle, the equivalence loop, and the auth path between the legacy runtime and the new
backend. Every later slice inherits all of it. So the first pick
should be *small, low-risk, and structurally complete* — it should touch each part of
the architecture once — rather than important.

Later slices can optimize for value, because the groundwork is paid for.

## 슬라이스의 단위 — 진입점이 아니라 호출자 전부

A slice is **every page that calls the target data-access method set** — not the one or two entry pages someone had in mind. Mobile pages, index pages, and ajax endpoints count. Measured in this tree: five methods on one data-access class were called from four more places outside the pages under consideration, and one of those callers passed the same argument with the *opposite* paging meaning.

This belongs in scouting, not only in the migration, because it is what the candidate actually costs. Each caller gets its own seam function and its own mapping onto the same backend API, so a candidate with six callers is six extractions, six lint passes and six corpus entries — not one. A ranking that counted one is off by a factor.

So count callers before ranking: `phpgrep` over the method names (both `->name(` and `::name(`), and `phpseam callers <symbol>` where the seam tooling is already in place — that command answers exactly this question and, unlike grep, distinguishes "no callers" from "the search failed".

Narrowing the scope is allowed and it has a place to be written down: every caller you exclude goes into the slice's `스왑 위험` section (`00-seam.md`) with the reason. An excluded caller nobody recorded is a page still running the old path while the audit reports the slice complete.

## 판정 기준

Check each candidate against these, in the code, and cite what you found.

**1. 우리가 소유한 데이터인가 (가장 중요)**
Some data is already federated — the legacy code fetches it over REST from another
system rather than owning a table. There is no backend to bring over for those; they
stay a call to someone else's API. Read the data-access layer and separate *tables we
read and write* from *endpoints we call*. A candidate that turns out to be federated is
not a migration target at all, and finding that out early saves the whole slice.

**2. 외부 의존의 수**
Each outbound integration the slice coordinates is a thing that can fail for reasons
unrelated to your migration. A first slice with several of them tests the integrations,
not your architecture.

**3. 읽기 위주인가**
Read paths fail visibly and revert cleanly. Write paths bring transactions, state
transitions, and the possibility of leaving bad rows behind. Read first.

**4. 표면을 몇 개 지나는가**
A slice whose data is written on one surface and read on another exercises the real
contract of the domain in one go, and it lets one spec prove both. That is worth more
than a slice confined to a single surface — as long as it stays small.

**5. 격리도**
Does it share tables with the busiest part of the service? Shared tables mean shared
blast radius and coupled schedules.

**6. 이미 정리된 코드인가**
Parts of a legacy tree are often already refactored — separated service/DAO/model
layers, or a newer directory that is the one actually in use. Those port with far less
guesswork. Check which files the routes actually reach; a directory can look canonical
and be dead.

**7. 죽은 코드인가**
Editors, integrations replaced by something else, batches marked for handover. Confirm
before proposing — a candidate that is unreachable should be proposed for *deletion*,
not migration.

**8. 이음새를 뽑아낼 수 있는가**

Every slice now starts by extracting a service function out of each page, so the difficulty of that extraction *is* the cost of the slice. Three things make it hard, and all three can be counted before committing:

- **가드 유형 수** — how many distinct kinds of early exit the page performs before the real work starts: an auth notice, a missing-parameter notice, a maintenance redirect, a permission check. Each kind is a separate decision about whether it stays in the page as a guard or moves inside the function, and each one is a line in the extraction plan that a person has to approve.
- **중간 출력** — does the page print markup or send headers *before* the data work finishes? A page that emits, then queries, then emits again cannot have its middle lifted out without deciding what happens to the output on both sides. Output buffering may be hiding this: the page works today and the ordering is still load-bearing.
- **전역 의존** — values the page's logic reads that a bootstrap include set, rather than values it was passed. Each becomes a parameter of the service function, and the ones whose source nobody can find are the ones that stall the extraction. `phpwhere` answers this; a search does not, because there is no declaration to find.

A page that is a guard block, a parse block, one query and a template include extracts in an afternoon. A page that interleaves output with logic across several hundred lines may not be extractable whole at all — and that is worth discovering *before* it is chosen, not in the middle of the first loop.

**9. 템플릿 로직 밀도**

Count the control structures in the templates the candidate renders — `if`, `foreach`, `switch`, ternaries — and how many of those conditions carry a comparison or arithmetic. `phpseam lint --template` reports exactly that and marks the suspicious ones 규칙 의심.

Density is not disqualifying; it is a prediction. Those conditions are where the completeness audit will later find `템플릿 규칙 잔존`, so a dense candidate has a longer ledger, an extraction that keeps having to decide what is layout and what is a rule, and an audit loop that runs more rounds. A sparse template over a fat page script is a far cheaper slice than the reverse.

**토크나이저 플래그 하나가 이 숫자를 뒤집는다.** These templates use the short open tag, and a tokenizer run without it swallows those blocks into HTML text — reporting *fewer* control structures, which reads as a clean, cheap candidate. Use the tool rather than counting by hand or with grep: it sets the flag, and it refuses to answer when the flag did not take.

## 절차

0. Read `.claude/context/legacy-tree.md`. Most of the criteria above turn on
   a count or a reachability check — 외부 의존, 표면 수, 공유 테이블, 6·7 의 "실제로 닿는가",
   그리고 8·9 의 가드·전역·템플릿 세기 —
   and much of this tree is CP949, where a bare `grep` returns nothing and exits 1. A count
   taken blind comes back low, and a low count here does not look like an error: it looks like a
   good candidate. Criterion 7 inverts worst — unreached and unsearchable are the same answer, so
   a live file gets proposed for deletion. The ranking is wrong and nothing says so.

   **이 단계에 배정된 도구는 검색과 정의 조회다** (`.claude/scripts/`). 건수는 `phpgrep`
   으로 세고, **진입점이 실제로 무엇에 닿는지는 `phpwhere --entry <파일>` 로 본다.** 후자가
   기준 6·7 의 답을 바로 준다 — include 사슬 전체와 그중 요청을 끝낼 수 있는 것까지
   한 번에 나오므로, 의존 범위를 세느라 파일을 하나씩 열지 않아도 된다. 이 파일시스템에서
   파일을 하나 여는 데 고정 지연이 붙으므로 그 차이가 크다.
1. Read `.claude/config/workspace.json` for the legacy roots and surfaces.
2. Inventory: entry pages per surface, the data-access layer, tables touched, outbound
   calls. Keep it to file-level evidence; do not read every line yet.
3. **호출자를 전수로 센다.** For each candidate, list every page that reaches the target
   methods — mobile, index and ajax included — because that list is the slice, and its
   length is most of the cost.
4. Score each candidate against the nine criteria with citations.
5. Rank, and recommend one — with the argument for it *and* the strongest argument
   against it. A recommendation with no counter-argument has not been thought about.
6. Propose a `depth` for the recommended candidate (below), and the two or three
   candidates after it, so the user can see the intended sequence.

## depth 제안

Each candidate carries a suggested `depth` — `shallow`, `normal`, or `deep`. The orchestrator
asks for one at Phase 0, and an unargued default is how a risky slice ends up with a cheap process.

| 제안 | 언제 |
|---|---|
| `shallow` | 읽기 전용, 호출자 한둘, 가드 한 종류, 템플릿 로직 희박, 틀려도 화면 하나에 그친다 |
| `normal` | 기본값. 호출자가 여럿이거나, 표면을 둘 지나거나, 결함 교정이 예상될 때 |
| `deep` | 권한·과금·상태 전이가 걸렸거나, 템플릿 로직이 빽빽하거나, 브라우저에서만 보이는 동작(JS·폼 전송·리다이렉트)이 후보 안에 있을 때 |

Say which criterion drove the suggestion. A depth with no reason attached is the first thing
someone in a hurry overrides.

## 출력

Write to `<docs.root>/slice-candidates.md` and report the ranking. For the recommended
candidate include the caller list and the suggested depth with its reason. Include a
"제외" section for candidates that are federated or dead, with the evidence — that
section prevents the same candidate being re-evaluated every quarter.

**Do not start the migration.** Choosing is the whole job here. Hand off to
`legacy-slice` once the user confirms.
