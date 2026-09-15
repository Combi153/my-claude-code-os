#!/usr/bin/env python3
"""계측 훅 케이스. 가짜 프로젝트·가짜 트리를 향하게 해 실로그를 건드리지 않는다.

    python3 selftest_hook.py <훅 경로>

가짜 트리의 디렉터리 이름은 이 파일이 스스로 정한다. 대상 체크아웃의 실제 이름을
쓰면 이 파일이 회사 정보를 담게 되고, 그러면 추적될 수 없다. 가짜여도 검사의
가치는 같다 — 훅은 이름이 아니라 경로 형태와 명령 위치로 판정하기 때문이고,
그것이 이 케이스들이 애초에 확인하려는 것이다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = sys.argv[1] if len(sys.argv) > 1 else None
if not HOOK or not os.path.isfile(HOOK):
    sys.exit("사용법: selftest_hook.py <php-tooling-hook.py 경로>")

BASE = tempfile.mkdtemp(prefix="phphook-")
PROJ = os.path.join(BASE, "proj")
CHECKOUT = os.path.join(BASE, "checkout")
MARKER = "src/tree"                       # 가짜. 실제 이름을 적지 않는다
SVC = "svc/one"
TREE = os.path.join(CHECKOUT, MARKER)

os.makedirs(os.path.join(PROJ, ".claude", "config"), exist_ok=True)
os.makedirs(os.path.join(PROJ, ".claude", ".state", "index"), exist_ok=True)
os.makedirs(os.path.join(PROJ, ".claude", "scripts"), exist_ok=True)
os.makedirs(os.path.join(TREE, SVC), exist_ok=True)

json.dump({"legacy": {"root": CHECKOUT, "treeRoot": TREE, "treeMarker": MARKER,
                      "ours": {SVC: "one"}, "services": {SVC: "one"},
                      "primaryService": SVC}},
          open(os.path.join(PROJ, ".claude", "config", "workspace.json"), "w"))

S = os.path.join(PROJ, ".claude", "scripts")
for name in ("phpv", "phpgrep", "phpwhere", "phped", "phplint", "phpindex",
             "phpseam", "htmlsnap", "dualrun-report", "ctxstats"):
    open(os.path.join(S, name), "w").write("#!/usr/bin/env python3\n")
SRC = os.path.join(TREE, SVC, "page.php")
open(SRC, "w").write("<?php echo 1;")
DOC = os.path.join(CHECKOUT, "CLAUDE.md")
open(DOC, "w").write("phpgrep phpv 를 이야기하는 문서\n")
IDX = os.path.join(PROJ, ".claude", ".state", "index", "one.json")
open(IDX, "w").write("{}")
LOG = os.path.join(PROJ, ".claude", ".state", "tooling.jsonl")
SESS = "hooktest"


def run(tool, payload, event="PreToolUse", session=SESS, extra=None):
    body = {"tool_name": tool, "tool_input": payload, "cwd": BASE,
            "session_id": session, "hook_event_name": event,
            "transcript_path": f"/x/{session}.jsonl"}
    body.update(extra or {})
    subprocess.run([sys.executable, HOOK], input=json.dumps(body),
                   capture_output=True, text=True,
                   env={**os.environ, "CLAUDE_PROJECT_DIR": PROJ}, timeout=60)


def lines():
    if not os.path.isfile(LOG):
        return []
    with open(LOG, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


CASES = [
    # (설명, tool, input, 기대 기록 도구, 넛지 기대)
    ("따옴표로 감싼 경로 호출",
     "Bash", {"command": f'"{S}/phpgrep" "한글낱말"'}, ["phpgrep"], False),
    ("도구 이름 나열은 호출이 아니다",
     "Bash", {"command": f"{S}/phpv phpgrep phped phplint phpwhere phpindex"},
     ["phpv"], False),
    ("도구 스크립트를 읽는 명령",
     "Bash", {"command": f"cat {S}/phpgrep"}, [], False),
    ("인용부호 안 도구 이름 검색",
     "Bash", {"command": f"grep -n 'phpgrep\\|phpv' {DOC}"}, [], False),
    ("전용 + 우회를 한 명령에",
     "Bash", {"command": f'{S}/phpgrep "x" ; grep -n "y" {SRC}'},
     ["phpgrep", "raw-grep"], True),
    ("트리 밖 경로는 세지 않는다",
     # 경로를 조립한다. 소스 확장자로 끝나는 경로 리터럴은 이 저장소의 콘텐츠
     # 가드가 잡으므로(그것이 그 패턴의 일이다), 가짜 경로여도 리터럴로 적을 수
     # 없다. 예외를 두는 쪽이 아니라 이쪽을 고치는 것이 맞다 — 가드의 커버리지를
     # 테스트 편의로 줄이면 정작 막아야 할 것이 지나간다.
     "Bash", {"command": "cat " + os.path.join(BASE, "outside", "other.php")},
     [], False),
    ("env 접두사 호출",
     "Bash", {"command": f"env -u PHP_LEGACY_ROOT {S}/phpwhere SomeName"},
     ["phpwhere"], False),
    ("python3 접두사 호출",
     "Bash", {"command": f"python3 {S}/phpv {SRC}"}, ["phpv"], False),
    ("맨 grep 우회",
     "Bash", {"command": f'rg -n "someKey" {SRC}'}, ["raw-grep"], True),
    ("맨 읽기 우회",
     "Bash", {"command": f"sed -n '1,40p' {SRC}"}, ["raw-read"], True),
    ("정의형 phpgrep 은 넛지",
     "Bash", {"command": f"{S}/phpgrep '$someVar ='"}, ["phpgrep"], True),
    ("SQL 조건 검색은 정의형이 아니다",
     "Bash", {"command": f"{S}/phpgrep \"WHERE seq = 59\""}, ["phpgrep"], False),
    ("Read 로 마크다운은 세지 않는다",
     "Read", {"file_path": DOC}, [], False),
    ("Read 로 PHP 소스는 우회",
     "Read", {"file_path": SRC}, ["Read"], True),
    ("Read 로 인덱스 JSON — 체크아웃 밖이어도 잡는다",
     "Read", {"file_path": IDX}, ["read-index"], True),

    # v2 의 도구 넷. 목록에 없는 동안 이 호출들은 전용으로도 우회로도 세어지지
    # 않고 통째로 빠졌고, 빠진 기록은 "도구를 안 썼다"와 같은 모양으로 도착한다.
    ("phpseam 은 전용 도구다",
     "Bash", {"command": f"{S}/phpseam lint {SRC}"}, ["phpseam"], False),
    ("htmlsnap 서브명령이 mode 로 기록된다",
     "Bash", {"command": f"{S}/htmlsnap capture --corpus c.json --out {BASE}/c"},
     ["htmlsnap"], False),
    ("dualrun-report 는 하이픈이 있어도 전용 도구다",
     "Bash", {"command": f"{S}/dualrun-report --json"}, ["dualrun-report"], False),
    ("ctxstats 도 전용 도구다",
     "Bash", {"command": f"{S}/ctxstats --days 1"}, ["ctxstats"], False),
]

print(f"{'':2} {'케이스':<40} {'기록':<26} {'넛지':<6} 판정")
print("-" * 96)
ok = 0
for i, (desc, tool, inp, want_tools, want_nudge) in enumerate(CASES, 1):
    before = len(lines())
    run(tool, inp)
    rows = lines()[before:]
    got_tools = [r["tool"] for r in rows]
    got_nudge = any(r.get("nudge") for r in rows)
    passed = got_tools == want_tools and got_nudge == want_nudge
    ok += passed
    print(f"{i:>2} {desc:<40} {str(got_tools):<26} {str(got_nudge):<6} "
          + ("통과" if passed else f"FAIL 기대={want_tools}/{want_nudge}"))

# 서브명령 정규식이 v2 도구의 낱말을 알아야 `mode` 가 빈 값이 되지 않는다.
extra_cases = []
before = len(lines())
run("Bash", {"command": f"{S}/phpseam callers SomeName"})
_rows = lines()[before:]
_mode = _rows[0].get("mode") if _rows else None
extra_cases.append(_mode == "callers")
print(f"{len(CASES) + 1:>2} {'phpseam 서브명령이 mode 에 남는다':<40} "
      f"{str(_mode):<26} {'':<6} "
      + ("통과" if _mode == "callers" else "FAIL 기대='callers'"))

# ------------------------------------------------------------ 귀속 케이스
print("-" * 96)
attrib_cases = []


def attrib_of(rows):
    return [(r.get("agent"), r.get("agents")) for r in rows]


def one(desc, want, extra=None):
    before = len(lines())
    run("Bash", {"command": f"{S}/phpv {SRC}"}, extra=extra)
    got = attrib_of(lines()[before:])
    passed = got == want
    attrib_cases.append(passed)
    print(f"{len(CASES) + len(extra_cases) + len(attrib_cases):>2} "
          f"{desc:<40} {str(got):<26} "
          + ("      통과" if passed else f"      FAIL 기대={want}"))


one("서브에이전트 밖 → 부모로 귀속", [(None, 0)])

run("Task", {"subagent_type": "php-behavior-analyst"})
one("Task 하나 열림 → 그 에이전트로 귀속", [("php-behavior-analyst", 1)])

run("Task", {"subagent_type": "php-rule-redteam"})
one("Task 둘 열림 → 모호하다고 적는다", [(None, 2)])

run("Task", {"subagent_type": "php-rule-redteam"}, event="PostToolUse")
one("하나 닫힘 → 남은 하나로 귀속", [("php-behavior-analyst", 1)])

run("Task", {"subagent_type": "php-behavior-analyst"}, event="PostToolUse")
one("전부 닫힘 → 다시 부모", [(None, 0)])

# 다른 세션의 Task 가 이 세션의 귀속을 오염시키지 않는가
run("Task", {"subagent_type": "domain-scribe"}, session="othersess")
one("다른 세션의 Task 는 섞이지 않는다", [(None, 0)])

# 훅 입력이 스스로 에이전트를 말하면 그것이 정본이다. `Task` 등록은 폴백이다.
one("입력의 agent_type 으로 귀속", [("php-seam-extractor", 1)],
    extra={"agent_type": "php-seam-extractor", "agent_id": "ag-01"})

run("Task", {"subagent_type": "php-behavior-analyst"})
one("입력이 있으면 Task 등록 상태보다 우선", [("php-seam-extractor", 1)],
    extra={"agent_type": "php-seam-extractor", "agent_id": "ag-01"})
run("Task", {"subagent_type": "php-behavior-analyst"}, event="PostToolUse")

total = len(CASES) + len(extra_cases) + len(attrib_cases)
passed = ok + sum(extra_cases) + sum(attrib_cases)
shutil.rmtree(BASE, ignore_errors=True)
print("-" * 96)
print(f"{passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
