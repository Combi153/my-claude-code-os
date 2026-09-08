---
name: golden-master
description: |
  리팩터 전후에 화면이 바이트로 같은지 확인한다. `htmlsnap` 으로 페이지를 캡처해 골든 마스터를 만들고,
  이음새 추출 뒤나 토글을 바꾼 뒤의 캡처와 비교해 무엇이 달라졌는지 보고한다.
  "화면 스냅샷", "골든 마스터", "HTML 비교", "리팩터 전후 같은지", "캡처 떠줘", "구조만 비교",
  "htmlsnap" 등에 트리거.
  슬라이스 이관 도중의 캡처·비교는 legacy-slice 가 Phase 1·6 에서 알아서 부른다.
---

# Golden master

Prove that a PHP-internal refactor changed nothing a browser can see, by comparing the bytes the server returned before and after.

## 이 오라클이 답하는 것과 답하지 않는 것

It answers one question: **is the rendered page identical?** That is exactly the question seam extraction needs, because extraction moves code without meaning to change output — so any difference at all is a defect, and a byte comparison finds it without anyone having to decide in advance what to assert. That is its advantage over a written test: it has no opinion, so it cannot have a blind spot you chose.

It does not answer whether the backend now computes the rule. A page whose PHP still computes everything renders identically to a page whose backend computes everything. That is the whole reason this OS asks two oracles: equivalence of the values crossing the seam is `dual-run`, and completeness of the move is `boundary-audit`.

It also cannot see what the server did not send — a value computed in JavaScript after load, or a difference that only appears for a session this capture did not use.

## 상수

The tool lives in `.claude/scripts/`; call `htmlsnap` by absolute path. Everything environment-specific comes from `.claude/config/workspace.json`, and a missing key stops the tool with the key's name rather than producing a narrower answer.

| 키 | 무엇에 쓰이는가 |
|---|---|
| `legacy.surfaces.<surface>.localBaseUrl` | 캡처가 두드릴 베이스 URL |
| `legacy.surfaces.<surface>.loggedOutMarker` | 미인증 응답을 알아보는 **본문** 정규식 |
| `legacy.surfaces.<surface>.charset` | 사람이 읽을 diff 를 만들 때만 쓰는 디코딩 (기본 `cp949`) |
| `legacy.snapshot.normalize` | 바이트 정규식 → 치환 목록. 요청마다 바뀌지만 동작과 무관한 값 |
| `legacy.snapshot.errorMarker` | 오류 페이지 본문 표식 |
| `legacy.snapshot.timeoutSeconds` | 요청 하나의 상한 (`--timeout` 이 덮는다) |
| `e2e.storageState.<surface>` | 세션 쿠키를 읽어 올 Playwright storageState 파일 |
| `legacy.dualRun.readbackPath` | `--toggle-expect` 가 현재 모드를 되읽는 경로 |

## 명령

```
htmlsnap capture --corpus corpus.json --out captures/<label> [--session <storageState.json>] [--toggle-expect legacy|dual|migrated] [--timeout 20]
htmlsnap compare captures/<a> captures/<b> [--report <out.md>] [--context 3]
htmlsnap corpus validate corpus.json
```

Exit codes are the ones this OS uses everywhere: `0` clean, `1` a real difference, `2` the tool could not answer — missing config, unreachable surface, a toggle that reads back wrong, an invalid capture on either side. `2` always prints the reason on stderr. **Never report a `2` as a pass.** A capture run that could not run is the failure mode this whole pipeline is built against.

## corpus 형식

```json
{
  "surface": "<surfaces 키>",
  "entries": [
    {"id": "detail-fixed-key", "path": "/<relative>/detail.php", "method": "GET", "params": {"<key>": "<fixed value>"},
     "mode": "full", "rules": ["R-01", "R-07"], "note": "고정 키 상세 — 행이 바뀌지 않는다"},
    {"id": "list-page-1", "path": "/<relative>/list.php", "method": "GET", "params": {"page": "1"},
     "mode": "structure", "rules": ["R-02"], "note": "목록은 데이터 변동 때문에 구조만"}
  ]
}
```

- **`id`** is the capture's filename stem and the key comparison joins on. Renaming one makes the old capture `missing`, not `different` — which reads like a tool error rather than a rename.
- **`mode`** is `full` (every byte after normalization) or `structure` (see below).
- **`rules`** are ledger row IDs this entry is meant to exercise. That is the join back to `01-ledger.md`: a row whose 관찰 value is `골든:<corpus-id>` has to name an entry that exists here.
- **`note`** says why the entry is shaped the way it is — in practice, why it is `structure`.

Run `htmlsnap corpus validate` before the first capture. A mistyped path captures a 404, and a 404 compares identically to itself forever.

## 세션 — 읽어 온다, 새로 만들지 않는다

Capture reads cookies out of a Playwright storageState JSON and sends them as request headers. **It never logs in.**

That limit is deliberate. The e2e harness under `e2e.root` already owns session issuance, and what it owns is not small: login is an https round trip to an SSO host while the local surface serves plain http, a second factor may need a person at the keyboard, and this project has already had the failure where an empty session file was saved and reported as ready. A capture tool that minted its own session would rebuild all three problems and get the third one wrong quietly.

So run the harness once to obtain a session, then point `--session` — or `e2e.storageState.<surface>` — at the file it wrote. With neither set, capture proceeds with no cookies and warns. That is correct for public pages and wrong for every other page, which makes the next section load-bearing.

## 로그아웃 표식 — 상태 코드로 판정하지 않는다

Measured in this tree: an unauthenticated request **does not redirect**. It returns `200` with a script body — a `confirm()` or `alert()` followed by a `location` assignment or `history.back()`. A missing required parameter answers the same way. So `200` is what the success page, the "please log in" page and the "bad parameter" page all return, and any capture tool that judges authentication by status code is wrong on every one of them.

Capture judges by body instead, matching `loggedOutMarker`, and flags the capture `logged_out`. The other two flags are `error_page` (5xx or `errorMarker`) and `timeout`. A flagged capture is still written — you want to see it — but marked **invalid** in the manifest, and **`compare` exits 2 if either side holds one.**

The reason that rule is absolute: a login-notice page is small, stable, and perfectly reproducible, which makes it an excellent golden master and a completely worthless one. Once it becomes the baseline, every later capture matches it, the comparison reports green forever, and nobody has rendered the page under test even once.

When a capture comes back `logged_out`, the thing to fix is the session. Never the marker.

## 바이트로 저장하고, 정규화는 최소로

The runtime sends no charset in the response header, and one surface mixes CP949 and UTF-8 pages, so there is no single decoding that is correct for a whole corpus. Capture therefore stores the raw response as `<id>.raw.html`, applies `legacy.snapshot.normalize` and the entry's mode to produce `<id>.norm.html`, and writes `<id>.json` with status, headers, byte count, both hashes, elapsed time and flags. Comparison runs on the normalized bytes; decoding happens only to print a diff for a person to read, using the surface's `charset`.

Normalization exists for exactly one thing: values that change on every request and carry no behavior — CSRF tokens, a timestamp printed into the markup, a cache-busting query string. **Every normalize rule is a blind spot you are choosing on purpose.** A pattern broad enough to hide a real change hides it silently and permanently, and the check keeps passing while it has stopped looking at anything. Write the patterns narrowly, anchor them, and when a diff is noisy prefer moving that one entry to `structure` over widening the list: the mode is scoped to one entry, the normalize list applies to the whole corpus.

Never add a normalize rule to make a failing comparison pass. It is the same move as weakening an assertion, with less to show for it afterwards.

## 구조 모드와 데이터 변동 전략

The database behind the local stack is remote and shared. Somebody else's write changes a list page between two captures, and that difference is real, unrelated to your edit, and indistinguishable from a regression.

Three defenses, in the order to reach for them:

1. **고정 키 상세는 `full`.** A detail page addressed by a fixed key renders one row that nobody is editing. This is the strongest entry type, and most of the corpus's `rules` coverage should sit here.
2. **목록은 `structure`.** Structure mode keeps tag names, attribute *names*, `id` and `class`, and drops text and other attribute values. What survives is what a refactor would break — the loop shape, how many rows the page decided to render, which classes a conditional turned on — and what disappears is the volatile content. Paging rules stay visible: row count and pager markup are structure, not text.
3. **before/after 는 시간 간격을 최소로.** Capture the before, make the edit, capture the after. Do not take a baseline on Monday and compare against it on Thursday; the gap is the exposure. When a comparison has to span a gap, re-capture the before side first and compare it against the old before — two captures of *unchanged* code that already differ tell you the corpus needs fixing, not the change.

A list entry that keeps failing in `structure` mode is not an argument for a looser normalize rule. It is an argument for finding a fixed-key page that exercises the same ledger rows.

## `--toggle-expect`

In the equivalence phase a capture is taken against a specific toggle mode, and a capture taken in the wrong mode is worse than no capture: it is a confident equivalence result for a code path that never ran.

`--toggle-expect <mode>` makes capture GET `legacy.dualRun.readbackPath` first and read the mode the **application** reports. If it differs, capture exits 2 and writes nothing. The compose env file, the config file, and the value you just wrote are not evidence — only the running process is. `local-stack` owns the write side, and only one actor moves the toggle at a time (`dual-run`).

## 루프에서 어떻게 쓰이는가

| 언제 | 무엇 | 무엇이 닫히는가 |
|---|---|---|
| 이음새 추출 전 | `capture` → `captures/before-<n>/` | 기준선이 생긴다 |
| 이음새 추출 후 (L0) | `capture` → `captures/after-<n>/`, `compare` | 전 항목 identical, 그리고 `phpseam lint` 위반 0 |
| 토글 `dual` | `capture --toggle-expect dual` | 페이지가 여전히 정상 렌더된다는 것만. **여기서의 identical 은 동등성의 증거가 아니다** — 페이지는 설계상 레거시 값을 렌더하므로 항상 같다. 동등성은 `dual-run` 이 답한다 |
| 토글 `migrated` (depth normal 이상) | `capture --toggle-expect migrated`, 레거시 골든과 `compare` | 남은 차이가 전부 원장의 `의도수정` 행으로 설명된다 |

`compare` reports one of four states per id — `identical`, `different`, `missing`, `invalid` — and `--report` writes them as a markdown table next to the diffs.

## 차이가 나왔을 때

| 증상 | 뜻 | 다음 |
|---|---|---|
| L0 에서 한두 항목만 `different` | 그 페이지의 추출이 동작을 바꿨다 | 그 페이지의 이동 계획으로 돌아간다. 정규화로 덮지 않는다 |
| L0 에서 전 항목 `different` | 공통 include 나 머리·꼬리 템플릿을 건드렸다 | 편집 범위를 다시 본다. 한 항목씩 보지 말고 공통 파일부터 |
| `invalid` | 세션 만료, 표면 다운, 또는 오류 페이지 | 세션과 스택을 고치고 다시 캡처한다. 그 캡처는 기준선이 될 수 없다 |
| `missing` | corpus 의 id 가 바뀌었다 | 이름을 되돌린다. 새 id 는 비교 이력을 끊는다 |
| `dual` 에서 `different` | 실험이 화면으로 샜다 (예외·출력·헤더) | 스왑 담당. 이중 실행은 화면에 아무것도 남기지 않아야 한다 |
| `migrated` 에서만 `different` | 화면 규칙 누락이거나 어댑터 반환 형태 | 값이 다르면 구현, 모양(키·타입·빈 값)이 다르면 스왑 담당 |

## 하지 않는 것

- **Do not capture against a shared dev server.** It puts a deploy inside every iteration and other people's data inside every diff. The local stack mounts the working copy, so an edit is live the moment it is written; that is why the loop can run at all.
- **Do not edit the corpus to make a comparison pass.** Narrowing an entry, dropping a param, or switching a failing `full` entry to `structure` mid-loop all convert a finding into a silence. Change the corpus between rounds and say so in `00-seam.md`, or not at all.
- **Do not commit captures to this repository.** They are rendered company pages. They belong in the slice directory under `<docs.root>`, next to the artifacts they justify.
