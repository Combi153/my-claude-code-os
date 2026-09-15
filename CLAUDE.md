# my-claude-code-os

Assignment repository for the 4-week course "나만의 Claude OS 만들기" (Build Your Own Claude OS). Each week: build skills, subagents, hooks, and orchestrators, then open a PR from a personal branch for review.

## This repository is public

The course is unrelated to the company. The OS is meant to be published; company code is not.

`php_legacy/`, `cs-system/`, and `cs-e2e/` live inside this directory and are gitignored. They must stay that way — the first two are company repositories, and `cs-e2e/` is a local repository this OS owns whose config carries internal hostnames.

- Never move content from those three into a tracked file of this repository. This covers code as well as internal domains, issue IDs, and people's names.
- Never commit logs or reports produced by running the OS against company code.

The rule in full, and what a placeholder looks like instead, is `.claude/context/team-boundary.md`.

## Working rules

1. Every Claude OS file (e.g. markdown under `.claude/`) must live inside this project.
2. Write skills (`SKILL.md`) in English. The frontmatter `description` stays Korean — it carries the Korean phrases that trigger the skill.
3. This is a hands-on course. Explain the reasoning while working, so the collaboration itself is something to learn from.

## The OS in this repository

A migration OS: it moves the backend half of a legacy PHP service into Spring/Kotlin one slice at a time, and proves two separate things about each slice — that behavior did not change, and that the domain logic actually moved.

Those need different oracles. An equivalence oracle answers the first. It cannot answer the second, because when PHP still computes a rule and the backend is never asked, the observable outcome is identical and every check stays green. So a slice is done only when equivalence is green **and** a completeness pass says every domain rule left PHP.

v2 puts both oracles at the same height — a **seam service function** per page. 동등성은 그 함수 안의 **이중 실행**(레거시 본문과 새 백엔드를 둘 다 실행해 비교하고, 화면에는 언제나 레거시 값을 돌려준다)과 PHP 내부 리팩터를 지키는 **골든 마스터**가 답한다. 완전성은 **구조 린트 · 본문 해시 고정 · 호출자 전수**가 먼저 답하고, 감사자에게는 분류와 배치의 판단만 남는다. e2e 는 이제 스모크다.

Both oracles join on the **behavior ledger**: the numbered list of rules a slice enforces, each classified 도메인 / 화면 / 경계, each carrying its source, its observation, and its migration state. 계약은 `.claude/context/ledger-contract.md`, 포맷 정본은 `.claude/skills/legacy-slice/references/ledger-format.md`. 도메인 문서도 이 원장에서 나온다 — 그래서 그 문서가 계속 참인 것이고, 그것이 별도 프로젝트가 아니라 작업의 부산물인 이유다.

| 스킬 | |
|---|---|
| `legacy-slice` | 오케스트레이터. Phase 0–8, 루프 5개, 사람 게이트 2개(G1 추출 계획 · G2 설계), 기계 게이트 2개 |
| `slice-scout` | 다음에 옮길 슬라이스 선정 |
| `golden-master` | 화면 HTML 골든 마스터 캡처·비교 |
| `dual-run` | 이음새 이중 실행 배선과 불일치 보고 |
| `boundary-audit` | 도메인 로직이 화면에 남아있는지 감사 (슬라이스별 / 표면 훑기) |
| `domain-doc` | 원장 → 기획자·운영자용 도메인 문서 |
| `local-stack` | 로컬 스택 기동과 마이그레이션 토글 제어 |
| `e2e-run` | 표면 스모크(페이지 기동·토글 되읽기). 동등성 판정은 `dual-run` 이 한다 |
| `php-legacy-io` | 레거시 파일 읽기·검색·편집·문법 검사 (인코딩이 파일마다 다르다) |
| `php-legacy-trace` | 이름이 어디서 정의되는지 추적 (이 언어에는 선언 문법이 없다) |
| `php-legacy-map` | 디렉터리·서비스·런타임 지도의 판독 규칙 |

| 서브에이전트 | Phase |
|---|---|
| `php-seam-extractor` | 1 — 이음새 추출 (계획 / 추출 두 모드) |
| `php-behavior-analyst` | 2 — 행위 원장과 커버리지 표 |
| `php-rule-redteam` | 2 — 원장 반증 (라운드 수는 depth 가 정한다) |
| `equivalence-corpus-author` | 2 — `필요 픽스처` → 골든 corpus, 원장 `관찰` 열 |
| `backend-slice-designer` | 3 — 규칙 배치·부재 점검표·교정표 |
| `backend-slice-implementer` | 4 — Kotlin/Spring 구현 |
| `php-swap-engineer` | 5 — 실험 스위치와 페이지별 어댑터 |
| `domain-boundary-auditor` | 7 — 분류·배치 판정 (판정 어휘 여섯의 정본) |
| `domain-scribe` | 8 — 영역 단위 도메인 문서 |

Models are assigned by role: judgment-heavy roles (분석·반증·설계·감사) run on opus, pattern-following roles (코퍼스·구현·문서) on sonnet. 오케스트레이터는 에이전트에게 산출물 파일명을 외우게 하지 않는다 — 절대경로를 프롬프트로 넘긴다.

The design and the reasoning behind it — decisions, loops, gates, open questions — live in `docs/legacy-migration-os.md`. That document is maintained as the design changes; edit it before changing the skills, not after.

## 도구 · 훅 · 컨텍스트

`.claude/scripts/` 에 도구 열하나. 여섯은 레거시 트리를 답할 수 있게 만들고(읽기·검색·정의 조회·인덱스·왕복 편집·문법 검사), `phpstats` 는 그것들이 실제로 쓰였는지 보고하며, 넷은 v2 의 것이다 — `phpseam`(모양·본문 해시·호출자), `htmlsnap`(캡처·비교), `dualrun-report`(불일치 집계), `ctxstats`(주입 계측). 전부 같은 실패를 막으려고 있다: **답을 찾지 못한 도구가 "답이 없다"고 보고하는 것.** 무엇이고 왜인지는 `docs/php-legacy-tooling.md`, 어떻게 부르는지는 `php-legacy-io`·`php-legacy-trace`.

`.claude/scripts/selftest.py` 는 도구·훅·계측과 교차 검사(감사 어휘 ↔ 라우팅표, 산출물 표 ↔ `artifacts.json`, 실험 헬퍼 상수 ↔ 설정 키, 컨텍스트 주입 대상, 옛 이름 부재)를 한 번에 돌린다. 그중 하나라도 건드렸으면 돌린다. 인자가 없고 검사마다 걸린 시간을 찍는다 — 정확하지만 느린 도구는 우회되고, 그 우회는 로그에 설계 문제처럼 보인다.

Skills and scripts contain no paths, hostnames, ports, table names, or service directory names: they read `.claude/config/workspace.json` (gitignored; `workspace.example.json` is the tracked skeleton), and every path in it points inside this directory, so the OS needs no `--add-dir`. 그 설정을 읽지 못하는 도구는 **좁은 답을 조용히 내지 않고 멈춰서 어느 키가 없는지 말한다.**

훅 다섯이 그 경계와 계측을 강제한다 — `guard-company-content.py`(회사 경로·내용의 스테이징 차단) · `php-encoding-guard.py`(편집 전후 인코딩 대조) · `php-tooling-hook.py`(전용 도구 대 우회, 역할 귀속) · `log-skill-usage.py` · `context-inject.py`(컨텍스트 결정적 주입). 상세는 `docs/legacy-migration-os.md` §6 과 `docs/context-system.md`.

`.claude/context/` 의 파일 일곱은 여러 소비자가 함께 쓰는 판정 규칙이다 — 팀 경계, 레거시 트리 읽는 법, 원장 계약, 이음새 모양, 동등성 오라클, 백엔드 아키텍처, 조용한 실패 목록. 프론트매터가 대상 에이전트·스킬·경로를 적고 `context-inject.py` 가 그것을 보고 넣는다. 파일마다 "먼저 이것을 읽어라" 한 줄을 두는 방식과 다른 점은 하나다 — **읽으라는 지시는 읽었다는 보장이 아니다.**
