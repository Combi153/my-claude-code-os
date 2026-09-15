---
name: legacy-slice
description: |
  레거시 PHP의 백엔드 부분을 슬라이스 단위로 Spring/Kotlin에 이관하고, 이관 전후 값이
  같은지와 도메인 로직이 실제로 다 옮겨갔는지를 각각 다른 방법으로 검증한다.
  이음새 추출 → 원장 → 설계 → 구현 → 이중 실행 배선 → 동등성 → 완전성 감사 → 문서화까지
  오케스트레이션한다.
  "슬라이스 마이그레이션", "PHP 백엔드 옮기기", "이 기능 Spring으로", "마이그레이션 시작",
  "레거시 슬라이스", "이음새 추출", "서비스 함수로 빼줘", "이중 실행", "동등성 검증",
  "완전성 감사", "다 옮겨갔는지 확인" 등에 트리거.
  슬라이스를 고르기만 하려면 slice-scout, 캡처·비교만 하려면 golden-master,
  이중 실행 배선·불일치 보고만 하려면 dual-run, 이미 끝난 슬라이스를 다시 감사하려면
  boundary-audit, 문서만 갱신하려면 domain-doc 을 쓴다.
---

# Legacy slice migration

Move one slice of a legacy PHP service's backend into Spring/Kotlin without changing what the screen does, and prove both halves of that claim.

## Why two oracles

An equivalence oracle answers *does it still produce the same values?* It cannot answer *did the domain logic actually move?* — because when PHP still computes a rule and the backend is never asked, the observable outcome is identical and every check stays green. A slice can be fully green and half migrated.

| 오라클 | 묻는 것 | 방법 | 실패의 의미 |
|---|---|---|---|
| **동등성** | 값이 같은가 | 이음새 안의 **이중 실행**(레거시 본문과 새 경로를 둘 다 실행해 비교) + **HTML 골든 마스터** | 이관이 틀렸다 |
| **완전성** | 다 옮겨갔는가 | **구조 린트** · **본문 해시 고정** · **호출자 전수** + 감사자의 분류·배치 판단 | 이관이 덜 됐다 |

v1 은 이 둘을 서로 다른 높이에 두었다. 관찰은 화면(e2e)에서, 도메인 경계는 페이지 스크립트에서, 교체 이음새는 DAO 에서. 높이가 셋이면 규칙이 이음새 **위**에 있을 수 있고, 그런 규칙은 이중 실행으로 영원히 EQUAL 이다 — 첫 실행의 FAIL 사유가 정확히 그것이었다(호출부의 페이징 산술이 원장에 없는 채 새 경로를 그냥 통과했다).

v2 는 세 높이를 **서비스 함수 하나**로 맞춘다. 페이지마다 이음새 함수를 하나 만들고, 페이지 스크립트에는 `include → 가드 → 파싱 → 서비스 호출 → 바인딩 → 템플릿 include` 만 남긴다. 그러면 "규칙이 이음새 위에 있다"는 상태가 **구조 린트로 기계가 잡는 위반**이 된다.

Both oracles join on the **behavior ledger** — the numbered list of every rule the slice enforces. Read `.claude/skills/legacy-slice/references/ledger-format.md` before Phase 2. 레거시 트리를 읽는 규칙(인코딩 혼재, `0건`과 `없다`의 구분, 미인증 200 응답)은 `.claude/context/legacy-tree.md` 에 있고 주입 훅이 대상 에이전트에 넣어 준다.

## 현재 환경

!`bash "${CLAUDE_PROJECT_DIR:-.}/.claude/skills/legacy-slice/status.sh"`

## 상수

Everything environment-specific lives in `.claude/config/workspace.json` (gitignored). Read it in Phase 0; if a key you need is missing, **stop and say which key** rather than guessing a narrower answer. **This repository is public — never write a path, hostname, port, table name, or identifier from the company checkouts into a tracked file here.** Slice artifacts are written into the backend repository's docs root, not into this one.

### 슬라이스 산출물

`<docs.root>/<docs.slicesDir>/<slice-id>/` 아래에 번호 순으로 쌓인다. **정본은 `references/artifacts.json`** 이고 아래 표는 그 사본이다 — 둘이 갈리면 JSON 이 맞다.

| 파일 | Phase | 쓰는 쪽 |
|---|---|---|
| `00-seam.md` | 1 | `php-seam-extractor` |
| `01-ledger.md` | 2 | `php-behavior-analyst` |
| `02-design.md` | 3 | `backend-slice-designer` |
| `03-dualrun.md` | 5 | `php-swap-engineer` |
| `04-audit.md` | 7 | `domain-boundary-auditor` |
| `05-domain-doc.md` | 8 | `domain-scribe` |

비번호 파일: `meta.json` · `corpus.json` · `pins.json` · `ignore.json` · `captures/<label>/` · `fixtures/`.

**에이전트에게 산출물 파일명을 외우게 하지 마라 — 절대경로를 프롬프트로 넘긴다.** 이름이 에이전트 파일에 박히는 순간 번호 체계가 다시 여러 곳의 사본이 된다.

**존재하는 파일의 최대 번호가 끝난 Phase 다.** 위 환경 블록의 `슬라이스 :` 줄이 그 JSON 을 읽어 슬라이스마다 끝난 Phase 와 다음 Phase 를 찍는다. 이 흐름은 게이트에서 사람을 기다리므로 세션이 끊기는 게 정상이고, 재개할 때 진행 상태를 물어볼 곳이 이것뿐이다. **재개는 다음 Phase 로 들어가고, 들어가기 전에 그렇게 말한다.** 슬라이스를 Phase 1 부터 다시 시작하는 것은 이미 받은 사람 승인을 버리는 일이다.

### 깊이(depth)

`meta.json` 의 `depth`. Phase 0 에서 사용자에게 묻거나 `slice-scout` 의 위험도에서 제안한다. 모든 하위 에이전트에게 이 값을 넘긴다.

| 항목 | shallow | normal | deep |
|---|---|---|---|
| 레드팀 라운드 | 0 | 1 (렌즈: 실행 경로 + 주변부) | 3 (아래 렌즈 셋 전부) |
| Phase 6 migrated 모드 골든 비교 | 안 함 | 함 | 함 |
| Playwright 스모크 spec | 안 함 | 안 함 | 함 (`e2e-run`) |
| corpus 폭 | 진입 URL + 픽스처 필수 행 | + 모든 `필요 픽스처` | + 특수문자·경계값 코퍼스 전부 |

## 루프 지도

Five loops, each closing on a different invariant. Know which one you are in. v1 had four; v2 adds the extraction loop in front, and it is the cheapest of the five.

| 루프 | Phase | 닫히는 조건 | 상한 | 넘으면 |
|---|---|---|---|---|
| **L0 추출** | 1 | `htmlsnap compare` 전부 identical **그리고** `phpseam lint` 위반 0 | 3 | 막는 구간(blocker) 목록과 함께 사람에게 |
| **커버리지** | 2 | 서비스 함수 본문의 모든 문장 범위에 규칙 ID (미커버 0) **그리고** depth 별 레드팀 라운드 소진 | 2 | 미커버 범위를 사람에게 |
| **L1 구현** | 4 | 빌드·단위·아키텍처 규칙 green | 5 | 설계 결함 의심 — Phase 3 으로 |
| **L2 동등성** | 6 | `dualrun-report` 의 예상 밖 불일치 0 (normal 이상: migrated 골든 차이가 전부 `의도수정` 행으로 설명됨) | 5 | 원인 요약 후 사람에게 |
| **L3 완전성** | 7 | 기계 검사 셋 통과 **그리고** 감사 PASS | 3 | 잔여 항목 명시하고 사람에게 |

Quality comes from where the loops are placed, not from their count. L0 and 커버리지 are early and cheap: a rule caught there costs one re-read, the same rule caught in L3 costs a redesign. Spend generously early.

## 게이트

사람 게이트는 둘뿐이다. 나머지는 기계가 막는다.

- **G1 — Phase 1, 편집 전.** 살아있는 코드를 처음 건드리는 지점. 사람이 보는 것: 페이지별 계획(가드·파싱·이동·바인딩의 줄 범위), 서비스 함수 시그니처, 막는 구간과 그 처리(가드로 남김 / 이동 / 범위 제외), 골든 corpus(URL·파라미터·모드), 정규화 규칙, 호출자 전수 결과. **계획이 바뀌지 않는 재진입(같은 파일·같은 함수)은 G1 을 다시 지나지 않는다.**
- **G2 — Phase 3 후.** 설계 승인. 추가로 **교정표**(결함마다 `교정`/`보존`, 구체 입력 예와 레거시 값·교정 값)를 확정한다. 승인은 원장 행에 승인자·일자로 남는다. **Phase 3 을 다시 지나면 G2 도 다시 지난다.**
- **Phase 5 에는 사람 게이트가 없다.** 이음새 래퍼(우리가 만든 파일)만 고치고, 레거시 본문은 `phpseam check` 의 해시로, 페이지 모양은 `phpseam lint` 로 기계가 막는다. 게이트를 여기서 뺀 이유는 사람의 승인이 검사보다 약해서가 아니라, **사람이 볼 수 있는 것을 기계가 더 촘촘히 보게 만들었기 때문**이다. 해시가 0바이트 변경을 보장하고 린트가 모양을 보장하면, 사람이 그 diff 를 다시 읽어 얻는 것이 없다.

Do not proceed on silence at either gate.

---

## Phase 0 — 준비

1. Read `.claude/config/workspace.json`. If missing, tell the user to copy the example and stop.
2. Fix the slice. 사용자가 지목했으면 그것을 쓰고, 아니면 `slice-scout` 를 부른다 — 직접 고르지 마라. 위험도와 의존은 사용자가 아는 것이다.
3. **슬라이스의 단위는 진입점 둘이 아니라 대상 DAO(또는 메서드 집합)를 부르는 페이지 전부다.** 모바일·index·ajax 호출자가 포함된다. 첫 슬라이스에서 진입점 밖 네 곳이 같은 메서드를 불렀고, 모바일은 같은 메서드를 정반대 페이징 의미로 썼다. `phpseam callers <symbol>` 로 전수를 뽑고, 범위를 좁힐 거면 **제외한 호출자를 `00-seam.md` 의 `스왑 위험` 절에 명시**한다.
4. `<docs.root>/<docs.slicesDir>/<slice-id>/` 생성. 이미 있으면 **재개** — 위 환경 블록이 말하는 다음 Phase 로 들어가고 그렇게 말한다.
5. `meta.json` 작성: `{"slice": "<id>", "runId": "v2", "depth": "...", "surface": "...", "dao": "<실제 값>", "pages": [...], "created": "YYYY-MM-DD"}`. 이 파일은 백엔드 저장소 docs 아래에 있으므로 실제 값을 써도 된다. 이 저장소의 추적 파일에는 안 된다.
   **`runId` 는 이 슬라이스가 어느 파이프라인으로 돌았는지다**(`v1` / `v2`). 같은 디렉터리에 v1 산출물이 남아 있는 슬라이스를 재개할 때, 번호만으로는 두 체계를 구별할 수 없다.
6. `local-stack` 으로 스택을 올리고 상태를 확인한다. **compose 프로젝트의 컨테이너 이름이 실제 떠 있는 컨테이너와 일치하는지 반드시 본다** — 위 환경 블록의 `컨테이너 :` 줄이다. 이전 compose 가 남긴 잔여물이 같은 포트로 떠 있으면 모든 캡처가 엉뚱한 스택을 찍고, 그 사실은 어디에도 드러나지 않는다.

## Phase 1 — 이음새 추출 (★G1 · L0 루프)

`Agent(subagent_type: "php-seam-extractor")`. 프롬프트에 넘길 것:

- `mode: 계획`, slice-id, 슬라이스 디렉터리 **절대경로**, `00-seam.md` **절대경로**
- `corpus.json`·`pins.json` **절대경로** (골든 corpus 초안과 본문 해시가 갈 곳)
- 페이지 목록(절대경로), 대상 DAO/메서드, depth
- **"계획만 쓰고 멈춰라 — 파일을 편집하지 마라"**
- `## 요약`(20줄 이내)을 첫 절로 쓸 것, 최종 응답은 300 단어 이내

`추출` 모드로 다시 부를 때는 같은 인자에 `mode: 추출`, **G1 승인 사실**, 승인된 계획의 경로를 더한다.

돌아오면 **G1 을 사람에게 제시한다.** 승인 후 같은 에이전트에 "승인된 계획대로 추출하라"고 다시 지시한다. 그때부터 추출 담당이 L0 를 스스로 돈다:

```
htmlsnap capture (before)  →  phped 편집  →  phpseam lint  →  htmlsnap capture (after)
                           →  htmlsnap compare        (전부 identical 이 될 때까지, 상한 3)
                           →  phpseam pin             (옮긴 레거시 본문의 바이트 해시 고정)
```

**이 단계의 검증은 골든 마스터다. 이중 실행이 아니다.** 아직 새 백엔드가 없고, 여기서 확인할 것은 "PHP 내부 리팩터가 화면을 바꾸지 않았다" 하나다. 캡처가 `logged_out` 이나 `error_page` 플래그를 달면 그 캡처는 기준선이 될 수 없다 — 미인증 응답은 HTTP 200 으로 오고, 로그아웃된 화면끼리는 언제나 identical 이다.

## Phase 2 — 원장 (커버리지 루프)

`Agent(subagent_type: "php-behavior-analyst")`. 넘길 것: `00-seam.md` 절대경로(서비스 함수의 위치와 시그니처가 여기 있다), `01-ledger.md` 절대경로, `references/ledger-format.md` 경로, **슬라이스 디렉터리 절대경로 · slice-id · 표면 · 페이지 목록 · 대상 메서드**, depth.

분석가는 서비스 함수 본문·가드·템플릿을 읽고 원장을 쓰되, **`커버리지` 절**(함수별 줄 범위 → 규칙 ID, 미커버 범위 명시)을 반드시 포함한다. 커버리지 루프가 닫히는 조건이 그 절의 `미커버 0` 이다.

그 다음 depth 만큼 레드팀:

```
for round in 1..(depth 별 라운드 수):
    Agent(subagent_type: "php-rule-redteam")
        ← 원장 경로 · 이음새 경로 · 슬라이스 디렉터리 · 페이지 목록
        ← **이번 라운드 번호와 그 렌즈** · depth
    merge findings into the ledger yourself   (레드팀은 쓰지 않는다)
```

| 라운드 | 렌즈 |
|---|---|
| 1 | 실행 경로 — 서비스 함수 본문 · 쿼리 구성 · 조용한 기본값 |
| 2 | 주변부 — 템플릿 · 환경 분기 · 포함된 commons · 가드로 남긴 구간 |
| 3 | 부재 — 없는 트랜잭션 · 없는 검증 · 없는 인가 · 없는 정렬 절 |

**라운드 번호와 렌즈를 반드시 넘긴다.** 각 라운드는 앞 라운드를 기억하지 못하는 새 인스턴스라, 렌즈가 없으면 같은 검색을 다시 돌고 두 번째 빈손이 첫 번째보다 아무것도 더 말해 주지 않는다.

Merging is yours because the red team must stay independent of the artifact it attacks. 둘은 오케스트레이터만 한다:

- **ID 배정.** 레드팀은 제안 ID 만 낸다. 최종 번호는 병합 시점의 최대값 다음이다. append-only — Phase 7 에서 늦게 도착한 규칙에도 새 번호를 준다.
- **분류 판정.** `references/ledger-format.md` 의 루브릭을 직접 적용한다. 특히 **화면에서만 강제되는 규칙은 `경계` 가 아니라 아직 안 옮겨진 `도메인`** 이다.

원장이 닫히면 `Agent(subagent_type: "equivalence-corpus-author")` 에 원장과 `corpus.json` 절대경로, **슬라이스 디렉터리 절대경로 · slice-id · 표면 키**, depth, 그리고 Phase 5 가 이미 이름을 정했다면 **실험 이름들**을 주어 **`필요 픽스처` 절을 corpus 로 옮기게** 한다. 그 담당이 `관찰` 열의 주인이다 — 심을 수 있는 픽스처는 `이중실행:`/`골든:` 이 되고, 못 심는 것만 `불가:<유형>` 이 된다. 분석가가 미리 `불가` 를 쓰면 심을 수 있었던 것까지 안 심는다.

## Phase 3 — 설계 → ★G2

`Agent(subagent_type: "backend-slice-designer")`. 넘길 것: 원장·`02-design.md` 절대경로, **`00-seam.md` 절대경로**(PHP 쪽이 무엇을 부르고 어떤 모양을 돌려받아야 하는지가 거기 있다), **슬라이스 디렉터리 절대경로 · slice-id**, depth.

**설계자는 `backend.architectureRules` 를 살아있는 파일에서 읽는다.** 첫 실행 뒤 그 규칙이 뒤집힌 적이 있다. 기억이나 요약본으로 대신하지 않는다.

설계서 필수 절:

- **규칙 배치표** — 도메인→fixity, 화면→proxy 뷰모델, 경계→proxy 입력 검증
- **부재 점검표** — 트랜잭션·검증·인가·멱등성·에러 매핑. 각 항목이 새 원장 행이 되거나 "해당 없음 + 이유"가 된다
- **교정표** — 결함마다 `교정`/`보존` + 구체 입력 예 + 레거시 값 + 교정 값
- **표류 의심 지점** — 각각 **원장 행 ID 를 달고 있어야 한다**
- 되받아칠 결정

그리고 **stop and get human approval.** 사람에게 제시할 것: 리소스/API 모양과 그것이 화면 모양이 아닌 이유, 배치표(특히 배치되지 않은 `도메인` 행), 되받아칠 결정, 교정표 전체, 보존하기로 한 결함.

Include every `잔류합의` the designer *proposed*. 설계자는 제안만 하고 승인은 사람만 한다. 승인은 원장 행 자체에 누가·언제로 적는다 — Phase 7 이 그 행을 읽고 근거가 있을 때만 넘긴다. `교정` 도 같다.

**"설계가 표류를 의심한 지점마다 원장 행이 있는지"를 게이트에서 직접 확인한다.** A design that says "this may diverge" has named a rule nobody has written down yet. 원장에 새 ID 로 넣고 Phase 4 로 간다. 코퍼스 담당은 원장만 읽으므로, 설계 문서에만 적힌 의심은 관찰이 될 길이 없고 L2 루프는 그 위를 초록으로 지나간다. 이것이 첫 슬라이스에 L3 재진입 한 번을 통째로 물렸다.

**게이트 직후, 승인된 `교정` 마다 `ignore.json` 항목을 준비하고 원장의 `관찰` 을 `제외:의도수정` 으로 바꾼 뒤 Phase 4 로 간다.** 그대로 두면 Phase 6 에서 의도된 교정이 예상 밖 불일치로 잡히고, 진단표는 그것을 "규칙 오역"으로 읽어 구현자에게 되돌려 보낸다. 되돌려 받은 구현자가 할 수 있는 유일한 일은 승인된 교정을 되돌리는 것이다.

## Phase 4 — 구현 (L1 루프)

`Agent(subagent_type: "backend-slice-implementer")`. 넘길 것: 승인된 설계서·원장 절대경로, **슬라이스 디렉터리 절대경로 · slice-id**, depth.

에이전트는 빌드가 green 이 될 때까지 스스로 고친다. 네 일은 **무엇이** green 이 됐는지 보는 것이다:

- **판정이 BFF 모듈에 들어갔는지** — 리졸버가 거르거나 정렬하거나 기본값을 정하고 있으면 모듈을 잘못 고른 것이다. 반대로 **fixity 의 `domain`·`application` 에 비즈니스 코드가 있는 것은 정상이다.** 거기가 그것이 살 자리다.
- **도메인 규칙이 질의 어댑터에 하드코딩됐는지** — 조건은 `domain` 에서 만들어 완성된 채로 어댑터에 넘어가야 한다. 어댑터가 조건을 *정하고* 있으면 모듈은 맞고 계층이 틀린 것이다.
- **아키텍처 규칙 자체가 바뀌었는지.** A build made green by relaxing its own constraint is a regression disguised as progress.
- **`의도수정`·`불가` 행마다 단위 테스트가 인용됐는지** — 그 행들은 두 오라클 밖이라 이것 말고 보는 게 없다. 인용은 테스트 심볼이어야 한다. "테스트했다"는 문장은 인용이 아니다.

## Phase 5 — 이중 실행 배선 (기계 게이트)

`Agent(subagent_type: "php-swap-engineer")`. 넘길 것: `00-seam.md`·`02-design.md`·`03-dualrun.md` 절대경로, `ignore.json`·**`pins.json`** 절대경로, 원장 경로, **슬라이스 디렉터리 절대경로 · slice-id**, depth.

이음새 래퍼에 실험 스위치를 설치한다(`.claude/templates/MigrationExperiment.php`). 모드는 셋: `legacy`(기본 — 값이 없거나 모르는 값이면 여기), `dual`, `migrated`. Spring 어댑터는 페이지마다 자기 매핑을 갖고 **반환 형태는 원본과 정확히 같아야** 한다. `ignore.json` 은 `의도수정` 행에서 만든다.

끝나면 셋이 모두 통과해야 한다. **실패하면 사람에게 오지 않고 스스로 고친다** — 이것이 Phase 5 의 게이트다.

```
phpseam check --pins pins.json     # 레거시 본문이 0 바이트도 안 바뀌었다
phpseam lint <page.php>            # 페이지가 허용된 모양 밖으로 나가지 않았다
phpseam callers <symbol> --allow-file <이음새 파일들>   # 이음새 밖 호출자가 없다
```

## Phase 6 — 동등성 (L2 루프)

**이 Phase 는 오케스트레이터가 직접 돈다.** 에이전트를 부르지 않는다 — 토글이 공유 가변 상태이기 때문이다.

```
local-stack 으로 토글 = dual  →  애플리케이션에서 되읽기
htmlsnap capture --corpus corpus.json --out captures/dual --toggle-expect dual
dualrun-report --ignore ignore.json
    (normal 이상)
local-stack 으로 토글 = migrated  →  되읽기
htmlsnap capture --corpus corpus.json --out captures/migrated --toggle-expect migrated
htmlsnap compare captures/legacy captures/migrated
    → 차이가 전부 `의도수정` 행으로 설명되는가
```

`dual` 모드에서 페이지는 **항상 레거시 값을 렌더한다.** 캡처는 corpus 를 순회하며 페이지를 두드리는 일이고, 불일치는 화면이 아니라 로그로 간다. 그래서 이 패스는 사용자에게 아무 영향이 없고, 그래서 사람 게이트 없이 돌 수 있다.

**토글을 뒤집는 작업을 둘 이상 동시에 돌리지 마라.** 첫 실행에서 두 에이전트가 서로 다른 저장소를 편집한다는 이유로 병렬 파견됐는데, 둘 다 검증하려고 토글을 뒤집었고 한쪽이 다른 쪽의 진행 중 상태에 대고 스위트를 통째로 돌려 21건이 깨졌다 — 스펙 결함도 이관 결함도 아니었다. Different files is not the same as different state. **토글은 오케스트레이터만 만진다. 에이전트는 상태를 요청하고 설정하지 않는다.**

그리고 **매번 애플리케이션에서 되읽는다.** env 파일에 값을 쓰는 것과 그 값이 PHP 에 도달하는 것은 다른 일이다. `--toggle-expect` 가 없는 캡처는 하지 마라 — 어긋난 토글로 찍은 캡처는 자신 있고 틀린 동등성 결과를 만든다.

진단표. 원인을 정하고 나서 파견한다:

| 증상 | 원인 | 담당 |
|---|---|---|
| 예상 밖 불일치, 값이 다름 | 규칙 누락·오역 (`diff_keys` 로 원장 행 지목) | implementer |
| 예상 밖 불일치, 그 규칙이 원장에 없음 | 새 규칙 | Phase 2 (새 ID) |
| 예상 밖 불일치, 모양(키·타입·빈 값)이 다름 | 어댑터 반환 형태 | swap engineer |
| `의도수정` 인데 예상 밖으로 잡힘 | `ignore.json` 누락 | swap engineer |
| 로그가 비어 있음 | 토글이 PHP 에 도달하지 않음 / 로그 경로 | swap engineer + `local-stack` 되읽기 |
| migrated 골든 차이가 `의도수정` 으로 설명 안 됨 | 화면 규칙 누락 또는 어댑터 | implementer / swap engineer |
| 캡처가 `logged_out`·`error_page` 플래그 | 세션 만료·스택 이상 — 비교 자체가 무효 | 오케스트레이터 (환경 먼저) |

**Never close this loop by weakening the corpus or the ignore list.** corpus 항목을 지우거나 `mode` 를 `full` 에서 `structure` 로 낮추거나 `ignore.json` 에 키를 더 넣으면 불일치는 사라진다. 사라진 것은 불일치이지 원인이 아니다. `ignore.json` 의 모든 항목은 **승인된 원장 행(`ledger` 필드)을 가리켜야** 하고, 가리키지 못하는 항목은 승인이 아니라 은폐다. 관찰이 틀려 보이면 다시 볼 것은 그 뒤의 원장 행이다.

예상 밖 불일치 샘플은 `dualrun-report --as-fixtures` 로 회귀 픽스처가 되게 저장한다. 고치고 나면 그 입력이 다시 깨지는지 물어볼 곳이 그것뿐이다.

## Phase 7 — 완전성 (L3 루프)

**먼저 기계 검사 셋을 돌린다. 하나라도 실패하면 감사자를 부르지 않는다** — 감사자에게 기계가 답할 수 있는 질문을 시키는 것은 비싸고, 그 답이 판단으로 포장되어 돌아온다.

| 검사 | 실패가 뜻하는 것 | 되돌아갈 곳 |
|---|---|---|
| `phpseam lint` (슬라이스 모든 페이지) | 규칙이 이음새 위로 다시 올라왔다 | Phase 1 |
| `phpseam check --pins pins.json` | 레거시 본문이 바뀌었다 | Phase 5 (되돌리기) |
| `phpseam callers <메서드들> --allow-file <이음새들>` | 이음새 밖에서 부르는 곳이 있다 | Phase 1 |
| `phpseam lint --template` | (보고용, exit 0) 템플릿의 제어 구조와 `규칙 의심` 지점 | 감사자에게 넘긴다 |

통과하면 `Agent(subagent_type: "domain-boundary-auditor")` 에 넘긴다: 기계 검사 출력 전체, 원장·설계·**`00-seam.md`**·`04-audit.md` 절대경로, **슬라이스 디렉터리 절대경로 · slice-id**, depth.

감사자의 판정 어휘는 여섯이고 **정본은 감사자 파일 하나**다. 아래 표에 없는 어휘가 돌아오면 그것은 감사 결과가 아니라 두 파일이 갈라졌다는 신호다 — 라우팅하지 말고 그 사실을 보고한다.

| 감사 판정 | 되돌아갈 곳 | 게이트 |
|---|---|---|
| `PASS` | Phase 8 | — |
| `템플릿 규칙 잔존` | Phase 1 | 가드/이동 계획이 바뀌면 G1 다시 |
| `계층 오배치` (proxy·fixity) | Phase 4 | 설계가 바뀌면 Phase 3 + G2 다시 |
| `잔류합의 근거 소멸` | Phase 3 | G2 다시 |
| `무방비` (`불가`·`의도수정` 행에 단위 테스트 없음) | Phase 4 | — |
| `새로 발견된 규칙` | Phase 2 (새 ID) | 설계가 바뀌면 Phase 3 + G2 |

Expect FAIL on a first slice. 가장 흔한 발견은 **이음새 밖 호출부가 계산해서 파라미터로 넘기기만 하는 규칙**이다 — 아무것도 옮겨가지 않았는데 값은 새 경로를 그대로 흐르므로 이중 실행은 영원히 EQUAL 이고 골든 마스터도 동일하다. 감사가 존재하는 이유가 그것이다.

A re-entry re-runs the phases below it, including Phase 6. That is the cost of an incomplete migration, and it is why Phase 1 and Phase 2 deserve the budget.

## Phase 8 — 문서 & 보고

`Agent(subagent_type: "domain-scribe")`. 넘길 것: 원장·감사 절대경로, **영역 문서의 절대경로**, 슬라이스에 남길 **포인터 파일(`05-domain-doc.md`) 절대경로**, 슬라이스 디렉터리 절대경로·slice-id·영역 이름.

**영역 문서 경로는 오케스트레이터가 해석한다: `<docs.root>/<docs.domainDir>/<영역>.md`.** 문서는 슬라이스가 아니라 **영역** 단위라 슬라이스 디렉터리 안에 있지 않다. 이미 있으면 그 경로를 주고 "제자리에서 개정하라"고 말한다 — 같은 영역을 설명하는 문서가 둘이 되는 순간 SSOT 가 죽는다. 슬라이스 디렉터리에는 그 문서를 가리키는 한 줄짜리 포인터만 남는다.

Then report to the user:

- 원장 분류별·이관 상태별 행 수
- **`meta.json` 에 자동 기록할 것**: 루프별 회차(L0·커버리지·L1·L2·L3)와 `불가` 행 수. 다음 슬라이스의 depth 를 정할 때 물어볼 곳이 여기뿐이고, 사람이 기억으로 답하면 비용이 항상 낮게 기억된다
- 두 오라클 결과와 **그것을 만든 명령**
- 예상 밖 불일치 샘플이 회귀 픽스처로 저장된 경로
- 도메인 문서 경로와 그 안의 열린 기획 결정 — 사용자만 답할 수 있는 것들이니 파일에 묻지 말고 꺼내 놓는다
- **토글 최종 상태와 되돌리는 명령**

**토글은 `legacy` 로 두고 끝낸다.** 사용자가 명시적으로 켜 두라고 하지 않은 한, 검토되지 않은 코드 경로를 운영 서비스에 살려 둔 채 세션을 끝내는 것은 오케스트레이터가 내릴 결정이 아니다.

---

## 오케스트레이터 규율

첫 실행에서 비용의 1/3 이 오케스트레이터 자신이었다 — 컨텍스트 × 턴. 이 흐름의 가치는 판단을 어디에 두는가에 있지 오케스트레이터가 무엇을 읽었는가에 있지 않다.

1. **레거시 파일을 직접 읽지 않는다.** 읽어야 할 것 같으면 그것은 에이전트에게 시킬 일이다. 예외는 없다 — 한 파일만 확인하려던 것이 매번 트리 순회가 된다.
2. **산출물을 통째로 읽지 않는다.** 각 산출물 첫 절의 `## 요약`(20줄 이내)만 읽는다. 모든 에이전트가 그 절을 의무적으로 쓴다. 요약에 없어서 판단할 수 없으면, 산출물을 펼치지 말고 **그 에이전트에게 요약을 고치라고 되돌린다.**
3. **에이전트의 최종 응답은 300 단어 이내로 요구한다.** 상세는 산출물 파일에 있다.
4. **게이트에서 세션이 끊기는 것이 정상이다.** 재개는 위 환경 블록의 `슬라이스 :` 줄로 한다. 상태를 대화에 쌓아 두지 마라.
5. **기계가 답할 수 있는 질문을 에이전트에게 시키지 않는다.** 해시·린트·호출자는 `phpseam` 이, 화면 동일성은 `htmlsnap` 이, 불일치 집계는 `dualrun-report` 가 답한다. 에이전트에게 남기는 것은 분류·배치·판단이다.

## 품질 감시

Check these yourself; agents are not trusted to self-report.

- [ ] 원장의 모든 `도메인` 행에 `이관됨:<심볼>`, 또는 **승인자와 이유가 적힌** `의도수정`·`잔류합의` 가 있다
- [ ] 원장에 중복 ID 가 없고, 번호를 재사용한 행이 없다
- [ ] `커버리지` 절에 미커버 범위가 0 이다 (또는 남은 범위가 사람에게 보고됐다)
- [ ] `필요 픽스처` 절의 모든 행이 corpus 항목이 되었거나 `불가:<유형>` 으로 닫혔다
- [ ] `불가`·`의도수정` 행마다 백엔드 단위 테스트 **심볼**이 인용돼 있다
- [ ] `ignore.json` 의 모든 항목이 승인된 원장 행 ID 를 가리킨다
- [ ] `제외:의도수정` 행이 `ignore.json` 에 있고, 그 반대도 참이다
- [ ] 교정한 결함이 레거시 경로에서는 그대로다 (양쪽을 고치면 되돌릴 곳이 없다)
- [ ] `phpseam check` 가 통과한다 — 레거시 본문이 0 바이트도 안 바뀌었다
- [ ] `phpseam lint` 위반이 0 이고, `phpseam callers` 가 이음새 밖 호출자를 내지 않는다
- [ ] 아키텍처 규칙이 이번 슬라이스에서 수정되지 않았다
- [ ] BFF 모듈에 판정하는 코드가 없다
- [ ] 기준선 캡처에 `logged_out`·`error_page` 플래그가 없다
- [ ] 컨테이너를 내리면 캡처가 실패한다 (통과하면 아무것도 검증하지 않는 것)
- [ ] 레거시 파일 인코딩이 편집 전후로 동일하다
- [ ] 토글이 `legacy` 로 돌아와 있다
- [ ] 이 저장소의 추적 파일에 회사 경로·호스트·포트·테이블명·사람 이름이 들어가지 않았다
