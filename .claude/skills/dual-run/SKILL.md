---
name: dual-run
description: |
  레거시 본문과 새 백엔드 호출을 한 요청에서 둘 다 실행해 비교하고, 화면에는 항상 레거시 값을 돌려준다.
  실험 헬퍼를 설치하고 토글을 세 모드로 다루며, 비교 로그를 `dualrun-report` 로 읽어 예상 밖 불일치만 남긴다.
  "이중 실행", "듀얼 런", "불일치 보고", "비교 로그", "dual 모드", "실험 로그", "왜 로그가 비어 있어"
  등에 트리거.
  슬라이스 이관 도중의 배선은 legacy-slice 가 Phase 5·6 에서 알아서 부른다.
---

# Dual run

Run both implementations on the same request, compare their results, log the difference, and return the legacy value.

## 이 오라클이 답하는 것

The seam is a PHP service function per page. Inside it, the legacy body and the Spring call both run, their results are compared, and **the legacy result is what the page gets**. So the user's screen is the legacy screen no matter what the new backend returns, and every real request becomes a test case with production-shaped input that nobody had to invent.

This is precisely what a screen-level oracle cannot do. While PHP still computes a rule and the backend is never asked, the page looks right and every capture matches. When the backend computes it differently but the template rounds the difference away, the page still looks right. A dual run compares the values **at the seam**, before the template gets a chance to hide them.

The cheapest demonstration is a legacy path that returns a hardcoded constant where a real count belongs. No screen test can see it — the number renders, the page is valid. One dual-run line shows both values side by side.

## 세 모드

| 값 | 무엇이 실행되는가 | 무엇이 반환되는가 |
|---|---|---|
| `legacy` | 레거시 본문만 | 레거시 값 |
| `dual` | 둘 다 (순서 무작위) | **레거시 값** |
| `migrated` | 새 백엔드 호출만 | 새 값 |

The environment variable and the three values are in `workspace.json` → `legacy.switch`. **Absent, empty, or unrecognized reads as `legacy`.** That default is the safety property, not a convenience: a container that lost its environment, a typo, or a mode name from a later version all serve the reviewed path instead of an unreviewed one.

Order matters inside `dual`: the two sides run in random order so that neither one is systematically warmed by the other, and the comparison never depends on which ran first.

In `dual`, an exception from the candidate side is caught, recorded, and the legacy value returned — the user sees nothing. In `migrated` it propagates. `migrated` is not a safe mode; it is the mode where you find out.

## 읽기 전용 슬라이스에만 배선한다

A dual run executes both sides. On a read that costs one duplicated query. On a write it means the row is inserted twice, the mail goes out twice, the counter moves twice — under a toggle that nobody was looking at when it happened.

So wire dual run **only around read paths**. For a write slice the honest plan is a different one — a shadow write to a separate store, or a straight cut with a rollback — not a dual run with a flag that suppresses half of itself. If a service function both reads and writes, split it during extraction and record the split in `00-seam.md`; a function that was left mixed is a `스왑 위험` row, not a thing to wire and hope about.

## 헬퍼 설치

The template is `.claude/templates/MigrationExperiment.php` in this repository. It is PHP 5.6 syntax and holds no environment values, which is why it can be tracked here at all. The builder copies it into the legacy tree beside `legacy.switch.helperPath`.

```php
MigrationExperiment::run($name, $envVar, $control, $candidate, $ignoreKeys = array(), $context = array())
```

- **`$name`** is the experiment name, and it is the join key in the log and in `ignore.json`. One experiment per service function per page — not per DAO method. Two pages calling the same method are two experiments, because they are two contracts.
- **`$control`** is the legacy body, **`$candidate`** the adapter call. Both are closures returning the same shape.
- **`$context`** carries at least the calling page. Two callers can use the same method with opposite meanings — measured here, one surface's pager and another's pass the same argument to mean different things — and a log without the caller erases that difference into one confusing pile.

The template file is pure ASCII, so copying it is safe with ordinary tools. Every later edit to the *installed* copy goes through `phped` like any other legacy file: the moment someone adds a Korean comment, a plain write re-encodes the file around it.

## 로그

One JSON line per `dual` call, appended to the file named by the environment variable in `legacy.dualRun.logEnvVar` (`MIGRATION_EXPERIMENT_LOG`); that variable is set to the host path in `legacy.dualRun.logPath`.

```json
{"ts": "<ISO8601>", "experiment": "<name>", "mode": "dual", "input": {"...": "..."},
 "control_sha": "...", "candidate_sha": "...", "equal": false, "diff_keys": ["items[0].title", "total"],
 "control": {"...": "..."}, "candidate": {"...": "..."}, "truncated": false,
 "control_ms": 12, "candidate_ms": 40, "page": "<script path>"}
```

A line over 64KB keeps the hashes and drops the bodies with `truncated: true`, so a large result set costs a bounded amount of disk and still tells you whether the two sides agreed.

### 마운트 확인 — 설정 파일에 줄이 있다고 동작하는 것이 아니다

The PHP that writes this log runs inside a container. `legacy.dualRun.logPath` is a **host** path, so it exists inside the container only if the compose file mounts it **and** the running container was created after that mount was added. A compose file edited without recreating the container is the ordinary case, not the exotic one.

Its symptom is an empty log. So is "the toggle never reached PHP". So is "no request was made". So is "everything matched and there was nothing to write". Four different states, one appearance — which is the failure shape this OS exists to refuse.

Verify by reading back, before trusting any round:

1. Set the toggle to `dual` and read the mode back **from the application** (`local-stack`, `legacy.dualRun.readbackPath`). The file you just wrote is not the answer. **되읽기 페이지는 모드 토큰을 하나만 출력해야 한다** — 세 모드 이름 중 둘이 같은 본문에 보이면 `--toggle-expect` 는 어느 쪽이든 매치시킬 수 있고, 그러면 어긋난 토글로 찍은 캡처가 통과한다.
2. Request one corpus entry.
3. Check that the log file **on the host** grew.

If it did not grow, ask in this order: is the mount in the compose file; was the container recreated after that; does the env var carrying the log path exist inside the container; is the directory writable by the container's user. All four fail silently and each looks like the other three, so check them in order rather than guessing.

`dualrun-report` exits `2` with the reason when the log is missing or unparseable. **That is not "no mismatches."**

## `ignore.json` 은 `의도수정` 행에서 만든다

```json
{"rules": [
  {"experiment": "<name>", "keys": ["total"], "ledger": "R-17",
   "reason": "의도수정: 값이 없을 때 상수를 반환하던 결함을 교정"}
]}
```

Every entry names a ledger row whose 이관 value is `의도수정(승인자, 일자)`. That row exists only because a person approved the correction at the design gate, with the concrete input, the legacy value and the corrected value written down. So the rule is short: **if you cannot write the ledger ID, the entry does not belong in this file.**

Adding a key because a mismatch is noisy converts a finding into a permanent silence inside a file nobody re-reads. The ledger link is what makes that impossible to do by accident — the mismatch has to have been approved before it can be ignored, and the approval is dated and attributed.

`keys` are paths into the compared structure, in the same notation `diff_keys` prints, so the report's own output tells you what to write. Keep them as narrow as the finding: `total` and `items[*].total` are different claims.

## `dualrun-report` 읽는 법

```
dualrun-report [--log <path>] [--ignore ignore.json] [--since <ISO>] [--experiment <name>] [--as-fixtures <out.json>] [--json]
```

Per experiment it prints four counts:

| 값 | 뜻 |
|---|---|
| equal | 두 값이 같았다 |
| 불일치 | 달랐다 — 아래 둘의 합 |
| 예상 | `ignore.json` 이 설명한다. 승인된 결함 교정 |
| **예상 밖** | 아무도 설명하지 않았다. 이 숫자가 0 이어야 한다 — **다만 그것만으로 루프가 닫히지는 않는다.** 종료 조건 전체는 `slicecheck` 의 단계 3~6 이고(migrated 골든·독 주입·레거시 본문 실행까지), 정본은 오케스트레이터의 루프 표다. 실제로 이중 실행이 "예상 밖 0" 을 보고한 상태에서 골든이 결함 둘을 잡은 회차가 있었다 |

Unexpected mismatches are grouped by their `diff_keys` signature, each group carrying a count and three sample inputs, plus the ledger hint when one exists. Read the signature before the samples: twenty mismatches under one signature are one defect, and the samples only tell you which input reaches it.

Pass `--since` set to the start of the current round. Without it the report folds in yesterday's runs against yesterday's code, and a defect you already fixed keeps reappearing — which costs a round of the loop to notice.

Exit: `0` no unexpected mismatch, `1` there are some, `2` the log could not be read.

## 예상 밖 불일치 → 회귀 픽스처

Before fixing anything, save the samples:

```
dualrun-report --since <round start> --as-fixtures fixtures/<round>.json
```

Each entry is `{experiment, input, control, candidate}` — an input already known to produce different answers from the two implementations, with both answers attached.

This is the cheapest test data the pipeline produces and the easiest to throw away. It came from a real request, it already distinguishes the two implementations, and it outlives the toggle. The implementer turns it into a unit test, and the ledger row for that rule then carries a 관찰 value that survives after the dual run is switched off. A mismatch fixed without a fixture leaves nothing behind, and the next regression is found by the same expensive route.

## 진단표

**정본은 `.claude/skills/legacy-slice/references/routing.md` 다.** 여기 사본을 두지 않는다 — v2 에서 이 표가 네 곳에 복사되어 이미 갈라져 있었고, 갈라진 뒤에는 어느 쪽이 맞는지 아무도 모른다. 증상에서 담당으로 가는 판정, 그리고 오라클을 약하게 만들어 루프를 닫지 말라는 규칙이 거기 있다.

## 토글은 한 주체만 직렬로 만진다

The toggle is one environment variable read by a container, not a per-request parameter. Two actors moving it at once produce a capture taken in a mode nobody chose and a log with two modes interleaved inside one timestamp range — and neither of those leaves a trace saying so, which makes the whole round unattributable after the fact.

So during the equivalence phase the orchestrator is the only actor that writes the toggle, one mode at a time, reading it back from the application after every change. A subagent that needs a different mode asks for it instead of setting it. If a person is using the same local stack for something else, that has to be known before the round starts.

Leave the toggle at `legacy` when the session ends.

## 하지 않는 것

- **Do not read equivalence off the screen while in `dual`.** The page renders the legacy value by construction, so it looks right even when every candidate value is wrong. A screen comparison in `dual` proves only that the experiment did not leak into the output.
- **Do not fix a mismatch by changing the control side.** The legacy body is the definition of correct until a ledger row, approved at the gate, says otherwise. Editing it to agree with the candidate destroys the baseline and the record of what the system used to do.
- **Do not leave `migrated` running unattended,** and do not leave it on at the end of a session. It is the one mode where a wrong candidate reaches a person.
