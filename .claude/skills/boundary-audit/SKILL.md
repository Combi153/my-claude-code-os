---
name: boundary-audit
description: |
  레거시 PHP에 도메인 로직이 남아있는지 감사한다. 슬라이스 원장이 있으면 규칙별로 대조하고,
  없으면 화면 코드 전체를 훑어 백엔드가 책임져야 할 로직을 찾아낸다.
  "도메인 로직 남아있나", "PHP에 로직 남았는지", "경계 감사", "화면에 로직 있나",
  "감사해줘", "이관 완료됐나", "PHP가 화면만 하고 있나" 등에 트리거.
  슬라이스 이관 도중의 감사는 legacy-slice 가 Phase 7 에서 알아서 부른다.
---

# Boundary audit

Check that the legacy screen is doing only screen work.

**Read `.claude/context/legacy-tree.md` before you search anything.** Half this
tree is CP949, and on those files a bare `grep` prints nothing and exits 1 — the same answer it
gives when the rule genuinely is not there. An audit is a claim about absence, so this is the one
job where a blind search is worse than no search: it manufactures the exact finding you were
hired to produce. A PASS built on a silent grep is worse than a FAIL.

This runs in two modes. Pick by whether a ledger exists for the target.

## 모드 A — 슬라이스 감사 (원장 있음)

Rule-by-rule verification of one migrated slice. **기계 검사를 먼저 돌리고, 그 출력을 감사자에게 넘긴다.**

Three of the questions this audit used to put to a reader are now decidable by a program, and a program answers them the same way every time:

```
phpseam lint <page.php>                                # 슬라이스의 모든 페이지 — 허용 모양 밖의 문장
phpseam check --pins pins.json                         # 옮긴 레거시 본문이 바이트로 그대로인가
phpseam callers <symbol> --allow-file <이음새 파일>...    # 이음새 밖에서 부르는 곳
phpseam lint --template <tpl.php>                      # 템플릿 제어 구조 보고 (막지 않는다)
```

If any of the first three fails, **do not dispatch the auditor.** Route instead: a lint violation goes back to seam extraction (and through the plan gate again if the guard or move plan changes); a changed pin goes back to the swap step to restore the body; a caller outside the seam goes back to extraction, because a caller nobody wired is a page still on the old path.

The order is about cost and about trust. The machine checks are cheap, total, and repeatable; the auditor is expensive, samples rather than enumerates, and reasons. Spending judgment on a shape a linter already reports is waste — and a PASS from a reader who never knew a caller had been missed is a PASS nothing can be built on.

When they pass, dispatch `Agent(subagent_type: "domain-boundary-auditor")` with **the machine-check output**, the ledger, the design, and both repositories, and relay its verdict. Send the template report with it: `phpseam lint --template` blocks nothing, it counts control structures and marks conditions carrying comparisons or arithmetic as 규칙 의심 — candidates for the one judgment no machine here can make, which is whether a conditional in a template is layout or a domain rule.

Use this after a slice lands, and again whenever the legacy tree is touched near it —
a bug fix made in the legacy path has a way of quietly reintroducing a rule that was
supposed to have left.

### 판정 어휘

Six verdicts, and no others. The canonical list lives in `.claude/agents/domain-boundary-auditor.md`; this table is a copy, and the routing it feeds is Phase 7 of `legacy-slice`.

| 판정 | 뜻 | 어디로 |
|---|---|---|
| `PASS` | 원장의 도메인 규칙이 전부 새 백엔드에 있고, PHP 의 새 경로에는 없다 | 문서화 |
| `템플릿 규칙 잔존` | 템플릿이나 페이지가 아직 도메인 규칙을 결정한다 | 이음새 추출 (가드·이동 계획이 바뀌면 계획 게이트를 다시) |
| `계층 오배치` | 규칙은 옮겨갔지만 설계가 정한 계층에 있지 않다 | 구현 (설계가 바뀌어야 하면 설계 단계와 그 게이트) |
| `잔류합의 근거 소멸` | `잔류합의` 행의 근거가 더 이상 성립하지 않는다 | 설계 단계와 그 게이트 |
| `무방비` | `불가`·`의도수정` 행에 단위 테스트가 없다 | 구현 |
| `새로 발견된 규칙` | 원장에 없는 규칙을 찾았다 | 원장 단계 (새 ID) |

A verdict written in any other phrasing has no row in the routing table, so nothing happens next — the finding is real and the pipeline stops anyway. That gap has cost this OS an audit result once already, which is why the vocabulary is closed rather than indicative.

## 모드 B — 표면 훑기 (원장 없음)

A standing sweep of a surface, asking one question: **what is this screen deciding that
it should be asking the backend?**

This mode has no ledger to check against, so it produces candidates, not verdicts.
Its value is that it finds rules nobody has enumerated yet — including in parts of the
service that have not been migrated at all.

### 무엇을 찾는가

Seven search lenses — **not** a second classification scheme. Mode B produces classified
candidates, not the six verdicts of 모드 A: the vocabulary here is
the ledger's `도메인` / `화면` / `경계`, defined in
`.claude/skills/legacy-slice/references/ledger-format.md`. These are only the shapes domain logic
takes when it sits in a page or a template, so that grep has something to look for.

Anything found through a lens is `도메인` unless the ledger rubric's judgment question
says otherwise. Keeping one vocabulary is what lets a finding here become a ledger row
later, instead of a note in a private dialect that someone has to translate by hand.

Domain logic in a page or template looks like:

- **조건부 가시성** — a conditional deciding whether a row, tab, or section appears at
  all, based on data rather than on layout. Deciding *what exists* is domain; deciding
  *how it looks* is screen.
- **기본값 결정** — resolving a default from environment, session, or data. Especially
  when the same default also appears in the PHP data-access layer: duplicated defaults
  are the most common way a migration ends up half done.
- **계산** — arithmetic on counts, indices, positions, prices, or dates. Any formula.
- **재구성** — loops that filter, group, sort, or reshape a result set after it comes
  back from the PHP data-access layer. Ordering counts: a fixed arrangement, a pinned
  position, or a dropped tail is a domain rule wearing a template loop's clothes.
- **상태 판정** — mapping a stored code to a status name, or deciding which transitions
  are allowed.
- **권한 판정** — deciding what this user may see or do.
- **검증** — input rules with no backend counterpart. If the backend accepts what the
  screen rejects, the rule lives only here, and any other client bypasses it.

**권한 판정 is the lens least likely to be reached by searching for its shape.** Measured in this
tree, permission decisions travel two ways that have no name to grep for: a global integer set as
the side effect of a bootstrap include and compared with `>` somewhere else, and a lookup done by
`eval` on a path assembled from strings. Read a surface's bootstrap include chain once, by hand,
before trusting a sweep to have covered this lens.

What is *not* a finding: CSS class selection, markup structure, label text, date
*display* formatting, widget choice, and routing.

### 절차

1. Read `.claude/config/workspace.json` for the surface roots.
2. Enumerate entry pages and templates. Search for the shapes above, then read the hits —
   search finds candidates, reading decides. **이 단계에 배정된 도구는 검색과 정의 조회다**
   (`.claude/scripts/`, 절대경로로 부른다). `phpgrep` 을 쓴다: 맨 `grep` 은 한 인코딩만
   덮고 다른 인코딩의 파일 전부에 대해 에러가 아니라 0을 답하며, 이 모드는 부재를
   주장하므로 그 0 이 깨끗한 표면으로 읽힌다.

   그리고 화면에 남은 값의 **출처**는 `phpwhere` 로 본다 — 특히 `--tpl`. 템플릿 변수는
   정의문이 없어서 검색으로는 출처를 찾을 수 없고, 출처를 모르면 그 값이 백엔드에서 온
   것인지 화면이 계산한 것인지 가릴 수 없다. 그 구분이 이 감사의 판정 자체다.
3. For each finding, record `파일:줄`, the rule in one sentence written the way the
   ledger writes rules (observable behavior, not implementation), a proposed 분류 from
   the ledger's three values, and whether the same rule also appears in the PHP
   data-access layer. A finding recorded this way lifts into a ledger unchanged.
4. Rank by risk: duplicated rules first (they break migrations), then permission and
   validation (they are security-relevant), then the rest.

### 출력

Write to `<docs.root>/boundary-sweep-<surface>.md` and report the top findings. **이 파일이 슬라이스 산출물의 번호 체계(`00-`~`05-`) 밖에 있는 것은 의도다** — 표면 훑기는 슬라이스에 속하지 않고, 슬라이스 디렉터리 안에 번호를 달고 앉으면 `status.sh` 가 그것을 끝난 Phase 로 읽는다.

For each, say what it would take to move it — most will be small, and a few will reveal
that a whole slice needs planning. Feed those into `slice-scout`.

Say how you searched, with the encodings, next to the finding count. A sweep reported as
"found 4" and a sweep reported as "found 4 across N files — M CP949, K UTF-8, both passes" are
different claims, and only the second one can be trusted by whoever reads it next.

**Do not fix anything in either mode.** The audit's value is that it is independent of
the work it judges. Report, and let the migration path handle repair.
