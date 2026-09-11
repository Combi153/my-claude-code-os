#!/usr/bin/env python3
"""계측 훅과 공개 저장소 가드의 케이스. 가짜 프로젝트·가짜 트리를 향하게 해
실로그를 건드리지 않는다.

    python3 selftest_hook.py <php-tooling-hook.py 경로>

가드 훅(`guard-company-content.py`)은 같은 디렉터리에서 찾는다. 그쪽 케이스는
**임시 git 저장소를 실제로 만들어** 거기서 진짜로 커밋·푸시한 상태에서 훅을 부른다.
인덱스가 비어 있는 순간이 그 가드의 결함이 살던 자리이므로, 그 순간을 흉내내지 않고
실제로 만든다.

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
             "phpstats", "phpseam", "htmlsnap", "dualrun-report", "ctxstats"):
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


# ------------------------------------------------------ 공개 저장소 가드 케이스
# 같은 디렉터리의 `guard-company-content.py`. 이 가드가 트리거하는 명령은 셋인데
# 검사 대상은 인덱스 하나뿐이었고, 인덱스가 비어 있는 두 명령(`commit -am` 과
# `push`)이 한 줄도 검사되지 않은 채 통과했다. 그래서 아래 케이스는 전부 **실패
# 경로**를 밟는다 — 인덱스가 비는 순간, 기준을 정할 수 없는 순간, 설정이 없는 순간.
# 해피 패스는 대조군으로만 둔다(인덱스만 보는 `commit -m` 이 통과하는 것).
print("-" * 96)
GUARD = os.path.join(os.path.dirname(os.path.abspath(HOOK)),
                     "guard-company-content.py")
guard_cases = []

GBASE = os.path.join(BASE, "guard")
REPO = os.path.join(GBASE, "repo")
OTHER = os.path.join(GBASE, "other")
REMOTE = os.path.join(GBASE, "remote.git")
NOUP = os.path.join(GBASE, "noupstream")
IGNORED_DIR = "company-checkout"        # 가짜. 실제 이름을 적지 않는다
HOST = "gate.internal.invalid"          # 예약 TLD. 실제 호스트가 아니다
ISSUE = "TICKET-4471"                   # 가짜 트래커
CFG = os.path.join(REPO, ".claude", "config", "redaction.json")
PATTERNS = {"patterns": [{"name": "internal-hostname",
                          "regex": r"\b[a-z0-9-]+\.internal\.invalid\b"},
                         {"name": "issue-id", "regex": r"\bTICKET-\d+\b"}],
            "allowPaths": [".claude/config/redaction.json"]}


def git_in(repo, *args):
    p = subprocess.run(["git", "-c", "user.email=t@example.invalid",
                        "-c", "user.name=selftest", "-c", "commit.gpgsign=false",
                        "-C", repo, *args],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 실패: {p.stderr.strip()}")
    return p


def init_repo(d, bare=False):
    os.makedirs(d, exist_ok=True)
    subprocess.run(["git", "init", "-q"] + (["--bare"] if bare else []) + [d],
                   capture_output=True, text=True, timeout=60)
    git_in(d, "symbolic-ref", "HEAD", "refs/heads/main")   # 버전 무관하게 main


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def guard(command, project=REPO):
    body = {"tool_name": "Bash", "tool_input": {"command": command},
            "hook_event_name": "PreToolUse", "cwd": project}
    return subprocess.run([sys.executable, GUARD], input=json.dumps(body),
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "CLAUDE_PROJECT_DIR": project})


def gtext(p):
    """훅이 사람에게 보이려는 문장. stdout 의 JSON 을 풀고 stderr 를 붙인다."""
    out = ""
    try:
        out += json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
    except Exception:
        out += p.stdout or ""
    return out + (p.stderr or "")


def gcase(desc, p, want_rc, needles=(), absent=(), in_stdout=()):
    text = gtext(p)
    ok = (p.returncode == want_rc
          and all(n in text for n in needles)
          and all(n not in text for n in absent)
          and all(n in (p.stdout or "") for n in in_stdout))
    guard_cases.append(ok)
    no = len(CASES) + len(extra_cases) + len(attrib_cases) + len(guard_cases)
    print(f"{no:>2} {desc:<40} {'exit ' + str(p.returncode):<26} {'':<6} "
          + ("통과" if ok else
             f"FAIL 기대 exit={want_rc} 필요={list(needles) + list(in_stdout)} "
             f"금지={list(absent)} :: " + " ".join(text.split())[:180]))


if not os.path.isfile(GUARD):
    # 훅이 없는 것은 건너뜀이 아니다. 가드가 사라진 저장소가 초록으로 찍히면
    # 이 파일이 막으려는 실패 모양을 이 파일이 스스로 만든다.
    guard_cases.append(False)
    print(f"{len(CASES) + len(extra_cases) + len(attrib_cases) + 1:>2} "
          f"{'가드 훅이 같은 디렉터리에 있다':<40} {'없음':<26} {'':<6} FAIL {GUARD}")
else:
    init_repo(REPO)
    init_repo(OTHER)
    init_repo(NOUP)
    init_repo(REMOTE, bare=True)
    write(os.path.join(REPO, ".gitignore"),
          f"/{IGNORED_DIR}/\nhandoff/\n/.claude/config/redaction.json\n")
    write(CFG, json.dumps(PATTERNS, ensure_ascii=False))
    write(os.path.join(REPO, "docs", "clean.md"), "# 깨끗한 문서\n본문 한 줄.\n")
    git_in(REPO, "add", ".gitignore", "docs/clean.md")
    git_in(REPO, "commit", "-q", "-m", "baseline")
    git_in(REPO, "remote", "add", "origin", REMOTE)
    git_in(REPO, "push", "-q", "-u", "origin", "main")

    # (1) 인덱스 — 예전에도 걸리던 경로. 대조를 위해 남긴다
    # 줄마다 첫 매치만 보고한다(줄당 break). 그래서 두 패턴이 각각 보고되는지
    # 보려면 두 줄이어야 한다 — 한 줄에 몰아넣으면 뒤 패턴의 보고를 확인할 수 없다.
    write(os.path.join(REPO, "docs", "leak.md"),
          f"운영 호스트는 {HOST} 이다.\n관련 티켓은 {ISSUE} 이다.\n")
    git_in(REPO, "add", "docs/leak.md")
    gcase("git add: 인덱스의 유출을 막는다", guard("git add docs/leak.md"), 2,
          ["인덱스", "issue-id"])
    git_in(REPO, "reset", "-q")
    os.remove(os.path.join(REPO, "docs", "leak.md"))

    # (2)~(4) 인덱스는 비어 있고 유출은 작업 트리에만 있다
    write(os.path.join(REPO, "docs", "clean.md"),
          f"# 깨끗한 문서\n운영 호스트 {HOST} 를 적었다.\n")
    gcase("commit -m: 인덱스만 커밋되므로 통과 (대조군)",
          guard('git commit -m "x"'), 0, absent=["internal-hostname"])
    gcase("commit -am: 작업 트리를 검사해 막는다",
          guard('git commit -am "x"'), 2, ["작업 트리", "internal-hostname"])
    gcase("복합 명령 뒤쪽의 git 도 따로 본다",
          guard('echo hi && git commit -am "x"'), 2, ["작업 트리"])

    # (5) 유출을 **지우는** 변경은 막지 않는다. 추가된 줄만 읽는다는 성질이
    #     작업 트리 검사에도 그대로 붙어 있는지 본다.
    git_in(REPO, "add", "docs/clean.md")
    git_in(REPO, "commit", "-q", "-m", "leak lands")
    write(os.path.join(REPO, "docs", "clean.md"),
          "# 깨끗한 문서\n호스트 줄을 지웠다.\n")
    gcase("commit -am: 유출을 지우는 변경은 막지 않는다",
          guard('git commit -am "지움"'), 0, absent=["internal-hostname"])

    # (6) push — 커밋은 이미 있고 인덱스는 비어 있다
    gcase("push: 원격에 없는 커밋을 검사해 막는다", guard("git push"), 2,
          ["origin/main..HEAD", "internal-hostname"])

    # (7) 기준을 정할 수 없을 때. 통과시키지 않고 이유를 말한다
    write(os.path.join(NOUP, "note.md"), f"티켓 {ISSUE}\n")
    git_in(NOUP, "add", "note.md")
    git_in(NOUP, "commit", "-q", "-m", "x")
    gcase("push: 기준을 못 정하면 막고 무엇이 없는지 말한다",
          guard("git push", project=NOUP), 2,
          ["기준", "@{upstream}", "origin/main", "통과가 아닙니다"],
          absent=["redaction.example.json"])

    # (8)~(9) 설정이 없을 때. 내용 검사는 막고, 경로 검사는 그대로 돈다
    os.rename(CFG, CFG + ".bak")
    gcase("redaction 설정이 없으면 막는다", guard("git add docs/clean.md"), 2,
          ["한 줄도", "redaction.example.json"])
    write(os.path.join(REPO, IGNORED_DIR, "note.md"), "회사 내용 한 줄\n")
    git_in(REPO, "add", "-f", IGNORED_DIR + "/note.md")
    gcase("설정이 없어도 경로 검사는 돈다",
          guard("git add -f " + IGNORED_DIR + "/note.md"), 2,
          ["회사 경로", IGNORED_DIR, "redaction.example.json"])
    git_in(REPO, "reset", "-q")
    os.rename(CFG + ".bak", CFG)

    # (10)~(11) 설정은 있지만 아무것도 보지 못하는 상태
    write(CFG, json.dumps({"patterns": []}))
    gcase("패턴이 0개면 막는다", guard("git add docs/clean.md"), 2,
          ["0개", "redaction.example.json"])
    write(CFG, json.dumps({"patterns": [{"name": "half-open",
                                         "regex": "[unclosed"}]}))
    gcase("패턴 컴파일 실패는 이름을 말하고 막는다",
          guard("git add docs/clean.md"), 2, ["half-open", "컴파일"])
    write(CFG, json.dumps(PATTERNS, ensure_ascii=False))

    # (12) 공개하지 않는 명령은 트리거가 아니다
    gcase("git status 는 트리거가 아니다", guard("git status"), 0,
          absent=["공개 저장소 가드"])

    # (13) 다른 저장소를 향한 명령. 판정하지 않았다는 사실이 **Claude 가 보는
    #      자리**(stdout 의 additionalContext)에 남아야 한다 — exit 0 의 stderr 는
    #      그쪽에 닿지 않으므로, stderr 만으로는 검사한 것과 구별되지 않는다.
    write(os.path.join(OTHER, "note.md"), f"{HOST}\n")
    git_in(OTHER, "add", "note.md")
    gcase("다른 저장소 대상이면 판정하지 않았다고 말한다",
          guard(f"git -C {OTHER} commit -am x"), 0,
          ["판정하지 않았습니다"], in_stdout=["additionalContext"])

    # (14) `-C` 를 확정할 수 없으면 막는다. 셸 변수는 훅에 펼쳐지지 않은 채로 오고,
    #      그 저장소가 이 공개 저장소일 수도 있다 — 모르는 상태를 통과로 내보내지
    #      않는 것이 이 가드가 이미 한 번 고친 결함이다.
    gcase("-C 가 셸 변수면 확정할 수 없다고 막는다",
          guard('git -C "$REPO" commit -am x'), 2,
          ["확정할 수 없습니다", "절대경로를 리터럴로", "통과가 아닙니다"])

total = len(CASES) + len(extra_cases) + len(attrib_cases) + len(guard_cases)
passed = ok + sum(extra_cases) + sum(attrib_cases) + sum(guard_cases)
shutil.rmtree(BASE, ignore_errors=True)
print("-" * 96)
print(f"{passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
