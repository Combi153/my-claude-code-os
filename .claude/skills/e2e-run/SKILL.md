---
name: e2e-run
description: |
  레거시 표면의 e2e 스모크를 돌린다. 페이지가 뜨는지, 지금 어느 토글로 도는지를 확인하고,
  실패하면 원인이 환경인지 기준선인지 갈라서 보고한다.
  동등성 판정은 여기서 하지 않는다 — 그것은 dual-run 이 이중 실행 로그로 답한다.
  "e2e 돌려", "스모크 돌려", "테스트 실행", "스펙 돌려봐", "페이지 뜨는지", "이 spec 만 돌려"
  등에 트리거.
  슬라이스 이관 도중의 실행은 legacy-slice 가 알아서 부른다 (depth deep 에서만).
---

# E2E run

Smoke the surfaces: prove the pages come up, and prove the toggle is the one this round intended. **동등성은 여기서 판정하지 않는다.**

## 역할 — 두 질문만 답한다

1. **페이지가 뜨는가.** Under the current toggle, does the page render instead of erroring, hanging, or bouncing to a login notice?
2. **토글이 생각한 그 값인가.** Does the *application* report the mode this round is supposed to be running?

Nothing else. Whether the two implementations agree is `dual-run`'s question, and it is answered from the comparison log at the seam. Whether a refactor changed the rendered bytes is `golden-master`'s, and it is answered by comparing captures.

The reason for that split is not tidiness. In `dual` mode the page renders the legacy value **by construction**, so a screen assertion is green no matter what the new backend returned — including when it returned the wrong answer on every call. An e2e suite pointed at that reports success for a broken migration, which is the exact failure shape this OS exists to refuse. And in `legacy` mode the suite is not testing the migration at all.

So this skill's green means "the environment is sane enough for the real oracles to run." That is worth having and it is all it is.

## 언제 spec 을 돌리는가

**`depth: deep` 에서만.** At `shallow` and `normal`, running the Playwright suite buys nothing the other two oracles do not answer more precisely, and it costs a browser, an SSO session, and a round of debugging whenever the harness itself drifts. Depth is set in the slice's `meta.json`.

At `deep`, specs are worth their cost for one reason: they exercise the page through a real browser, so they catch what a byte capture cannot — JavaScript that runs after load, a form that posts, a redirect that only a browser follows. That is a different question again, and it is why deep exists.

Outside a slice, run this whenever someone asks whether a surface is alive.

## 상수

Read `.claude/config/workspace.json` → `e2e`. It gives the harness root and, per surface,
the Playwright project name, the test directory, and the env var that overrides that
surface's base URL. Nothing environment-specific belongs in this file.

If `upstreamOs.runE2e` names a skill inside `upstreamOs.skillsDir`, prefer it — it carries
operational detail this file should not duplicate. Fall back to the commands below when it is empty.

The harness lives inside this directory, so there is nothing to install or add — but its
dependencies and browsers do need to exist. `npx playwright install chromium` is the fix
when a run dies with "Executable doesn't exist"; that happens after a Playwright upgrade
pulls a newer browser build than the cache holds.

## 실행

Run from the harness root, selecting by project rather than by path — the project carries
the surface's auth and base URL, and a bare path selection silently runs with neither.

```
npx playwright test --project=<project>              # 표면 전체
npx playwright test --project=<project> <spec>       # 하나만
HEADLESS=false npx playwright test --project=<...>   # 눈으로 볼 때
```

**Use one command for the whole round.** If the invocation changes between runs you cannot
tell a real change from a harness difference. Report the exact command you used.

Before the run, read the toggle back through `legacy.dualRun.readbackPath` (`local-stack`)
and say in the report which mode the run was in. A smoke result with no mode attached
cannot be compared with the next one.

## 인증

`global-setup` ensures an SSO session per surface before any test runs, reusing another
surface's session when the cookie is shared. So a run against a dead surface fails in
setup, not in an assertion — that is correct and faster, but read the message: a setup
failure is about *reachability*, an assertion failure is about *behavior*.

The first run on a fresh machine opens a browser for login. That needs a person, so do
not start it in an unattended session. The session file it leaves behind is the same one
`htmlsnap --session` reads, which is why running this once is often the cheapest way to
unblock a capture.

## 실패를 읽는 법

Do not report "tests failed." Report which of these it is.

| 증상 | 뜻 | 다음 |
|---|---|---|
| global-setup 에서 죽음 | 표면에 못 닿거나 세션 만료 | `local-stack` 으로 표면 상태 확인. 컨테이너 이름 대조부터 |
| 전 표면 red | 환경 또는 기준선 | 이관 문제가 아니다. 컨테이너와 데이터부터 |
| 토글 되읽기가 예상과 다름 | 컨테이너가 재생성되지 않았다 | 스모크를 멈춘다. 이 상태의 결과는 어느 모드의 결과인지 말할 수 없다 |
| `dual` 인데 red | 이중 실행이 화면으로 샜다 (예외·출력·헤더) | builder. `dual` 에서 화면은 레거시와 같아야 한다 |
| 간헐적 red | 살아있는 데이터에 의존 | spec 이 결함이다. 원장 행으로 돌아가 다시 본다 |
| 컨테이너 내려도 green | **spec 이 아무것도 검증하지 않는다** | 그 spec 은 지운다 |

**Never make a failure go away by weakening an assertion.** The assertion is downstream of
a claim in the behavior ledger; if it looks wrong, the ledger row is what to re-read.

## 하지 않는 것

- **Do not report an equivalence verdict from here.** Green means the pages came up. Say that, and point at `dual-run` for whether the values matched.
- **Do not edit specs here.** Authoring belongs to the corpus author under a ledger; changing a spec to match an outcome you just observed turns the oracle into a mirror.
- **Do not move the toggle.** Read it, report it, and let the orchestrator set it — two actors moving it produces a run nobody can attribute to a mode.
