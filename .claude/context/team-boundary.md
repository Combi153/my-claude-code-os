---
name: team-boundary
kind: 팀
inject:
  agents: [php-seam-extractor, php-behavior-analyst, php-rule-redteam, equivalence-corpus-author, backend-slice-designer, backend-slice-builder, domain-boundary-auditor, domain-scribe, goal-loop-worker, goal-gauge-author]
  skills: []
  paths: ["${project.root}/**"]
  tools: [Write, Edit]
  priority: 0          # 예산이 차도 이 파일은 마지막까지 남는다
token: CTX-TEAM-BOUNDARY-4b19
---

# 공개 저장소 경계

이 OS 는 공개된다. 이 OS 가 다루는 코드는 공개되지 않는다. 두 문장이 같은 체크아웃 안에서 성립해야 하므로, 경계는 습관이 아니라 규칙으로 존재한다.

## 판정 규칙 하나

**"이 파일이 추적되는가"** 로 갈린다. 추적되면 회사 정보가 한 글자도 들어갈 수 없고, 추적되지 않으면 들어가도 된다. 애매하면 추적되는 쪽으로 가정한다 — 새로 만든 파일은 기본적으로 추적된다.

회사 정보는 코드만이 아니다. 다음은 전부 회사 정보다.

- 경로·디렉터리 이름·호스트·포트·컨테이너 이름
- 테이블·컬럼·계정 이름, 티켓 번호, 사람 이름
- 클래스·메서드·상수처럼 그 서비스에만 있는 심볼 이름
- 위의 것들이 그대로 박힌 로그·리포트·캡처

## 그래서 어떻게 쓰는가

환경값은 **설정에서 읽는다.** 추적되는 파일에는 키 이름만 적는다 — `${legacy.root}`, `${backend.root}` 처럼. 실제 값은 gitignore 된 설정 파일에만 있다.

예시가 필요하면 **자리표시자**로 쓴다: `<service>/dao/<Dao>.php`, `<surface-a>`, `<PREFIX>_BACKEND_{SLICE}`. 진짜 이름을 "예시니까 괜찮다"로 적지 않는다. 예시는 추적된다.

**설정 키가 없으면 멈추고 이유를 말한다.** 좁은 답을 조용히 내지 않는다. 값이 없다는 것과 값이 비어 있다는 것은 다른 사실이고, 도구가 그 둘을 같은 출력으로 덮으면 그 출력을 근거로 쓴 모든 결론이 틀린다.

## 산출물은 어디로 가는가

슬라이스 산출물(원장·설계서·감사 보고)과 도메인 문서는 **회사 정보를 담아도 되는 저장소**에 쓴다 — 설정의 `docs.root` 아래다. 이 OS 저장소가 아니다. 이 OS 저장소에는 그 산출물을 **만드는 방법**만 있다.

OS 를 회사 코드에 돌려서 나온 로그·리포트·캡처는 커밋하지 않는다. 상태 디렉터리는 gitignore 되어 있고, 그것이 규율이 아니라 구조로 지켜지는 방식이다.

## 이 규칙이 어겨졌을 때의 모양

한 번 커밋되면 되돌릴 수 없다. `git` 훅이 스테이징을 막지만, 훅은 마지막 방어선이지 첫 방어선이 아니다. 첫 방어선은 **파일에 쓰기 전에 이 파일이 추적되는지 확인하는 것**이다.
