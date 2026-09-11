#!/usr/bin/env python3
"""PreToolUse(Bash|Read|Task) + PostToolUse(Task) — nudge toward the legacy tools,
record use, and attribute it to the pipeline stage that made the call.

Never blocks. Three jobs:

  nudge   A `phpgrep` whose pattern is definition-shaped (`$X =`, `function foo`,
          `class Foo`, `define('X'`) returns zero whenever the real definition is
          written as `$X[key] = value`, and that zero reads as "does not exist".
          Say so and point at `phpwhere`. Also catch reading the index JSON by hand.

  log     Append one line per call that touches the legacy checkout to
          <project>/.claude/.state/tooling.jsonl. The point is not a call count -
          it is whether the purpose-built tool was used or bypassed: `phpv` vs the
          Read tool, `phpgrep` vs raw grep, `phpwhere` vs a definition-shaped grep.
          `phpstats` reads it back.

  attribute  Track which subagent is running, so a call can be attributed to the
          pipeline stage that made it. `session_id` cannot do this - a subagent
          gets the same one as its parent, which is why the stage-by-stage tool
          assignment in docs/php-legacy-tooling.md §5 was unverifiable. Registered
          on Task for both PreToolUse and PostToolUse to open and close the record.

Nothing that touches the legacy checkout is named here: this file is tracked and
the repository is public. `legacy.root` and `legacy.treeRoot`/`legacy.ours` come
from .claude/config/workspace.json, which is gitignored. Without that config the
nudging and logging do nothing — attribution still runs, because it is about this
session rather than about the checkout. Every failure path is swallowed: a broken
logger must never break a tool call.
"""
import json
import os
import re
import shlex
import sys
import time

MAX_LOG = 5 * 1024 * 1024

# A definition here is `$변수` (optionally subscripted) followed by `=`, not any `=`
# at all. Measured: matching a bare `=` fires on SQL conditions (`WHERE col = `),
# HTML attributes (`name="x"`) and config strings (`iconv=UTF-8`) — 4 of 12
# representative cases wrong. Requiring the `$` brings that to 0.
DEF_SHAPED = re.compile(
    r"(\\?\$[A-Za-z_]\w*(?:\[[^\]]*\])?\s*(?:\\s\*)?=(?![=>])"
    r"|\bfunction\s|\bclass\s|\binterface\s|\btrait\s|\bdefine\s*\\?\s*\()")
NAME_IN_PATTERN = re.compile(r"\$?([A-Za-z_]\w{2,})")
# v2 의 도구 넷이 여기 없는 동안, 그 도구를 부른 명령은 우회로도 전용으로도
# 세어지지 않고 통째로 빠졌다 — 그리고 빠진 기록은 낮은 사용률로 보인다.
OUR_TOOLS = ("phpv", "phpgrep", "phped", "phplint", "phpindex", "phpwhere",
             "phpstats", "phpseam", "htmlsnap", "dualrun-report", "ctxstats",
             "ctxevolve")
STOP = {"function", "class", "interface", "trait", "define", "scope", "all",
        "tests", "web", "php", "inc"}
# 인덱스는 2026-09-08 에 `.claude/.state/index/` 로 옮겼다. 옛 경로만 보는 동안
# 인덱스를 직접 읽는 것이 조용히 통과했다.
INDEX_REF = re.compile(r"\.claude/\.state/index/\S*\.json")

RE_HEREDOC = re.compile(r"<<-?\s*'?\"?(\w+)'?\"?.*?^\1", re.S | re.M)


def strip_heredocs(cmd):
    """A heredoc body is data, not a command. Writing a file whose *content*
    mentions `.claude/index/x.json` is not an attempt to read the index."""
    return RE_HEREDOC.sub("", cmd)


PREFIX_CMDS = {"env", "s" "udo", "time", "nohup", "command", "exec"}
SOURCE_EXT = (".php", ".inc")
READ_CMDS = ("cat", "head", "tail", "less", "more", "sed", "awk", "nl")
GREP_CMDS = ("rg", "grep", "egrep", "fgrep", "ag", "ack")


def _segments(cmd):
    """Split a command line where a new command can begin."""
    cmd = re.sub(r"\d?>&\d", " ", cmd)          # 2>&1 의 & 는 구분자가 아니다
    return re.split(r"&&|\|\||[;\n|&]", cmd)


def _leading_command(seg):
    """(basename of argv0, remaining argv) for one segment, prefixes stripped.

    A tool name counts only when it stands where a command stands. Quoting is
    not the test: `"$S/phpgrep" 'x'` is an ordinary call and used to be dropped
    entirely, while `phpv phpgrep phped ...` merely lists names and used to be
    logged as seven calls. Both errors were silent and pointed opposite ways.
    """
    try:
        toks = shlex.split(seg, posix=True)
    except ValueError:
        toks = seg.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if re.match(r"^[A-Za-z_]\w*=", t):        # VAR=value
            i += 1
            continue
        base = os.path.basename(t)
        if base in PREFIX_CMDS:
            i += 1
            while i < len(toks) and (toks[i].startswith("-")
                                     or re.match(r"^[A-Za-z_]\w*=", toks[i])):
                i += 2 if toks[i] in ("-u", "--unset") else 1
            continue
        if re.match(r"^python[\d.]*$", base):
            i += 1
            continue
        return base, toks[i + 1:]
    return None


def _targets_source(seg, root_abs, cwd_in_tree):
    """Does this segment actually touch source in the tree?

    경로로 판정한다. 트리 디렉터리의 basename 을 문자열로 찾으면 트리 밖에 있는
    같은 이름의 디렉터리도 트리로 잡힌다.
    """
    if INDEX_REF.search(seg):
        return True
    if root_abs and re.search(re.escape(root_abs) + r"/\S+\.(php|inc)\b", seg):
        return True
    if cwd_in_tree and re.search(r"\S+\.(php|inc)\b", seg):
        return True
    return False


def config(project_dir):
    cfg = os.path.join(project_dir, ".claude", "config", "workspace.json")
    try:
        with open(cfg, encoding="utf-8") as fh:
            return json.load(fh).get("legacy") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def service_of(path, tree_root, ours):
    """Short name of the owner dir this path sits in, or None."""
    if not tree_root or not ours:
        return None
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(tree_root))
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    for prefix, name in ours.items():
        if rel == prefix or rel.startswith(prefix + "/"):
            return name
    return None


def _agents_path(project_dir):
    return os.path.join(project_dir, ".claude", ".state", "open-agents.json")


def open_agents(project_dir, sess):
    """Subagent types currently running in this session, oldest first.

    상태 파일에 남는다. 훅은 호출마다 새 프로세스이므로 메모리로는 이어지지 않는다.
    """
    try:
        with open(_agents_path(project_dir), encoding="utf-8") as fh:
            return [r["type"] for r in json.load(fh).get(sess, [])]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def mark_agent(project_dir, sess, kind, opening):
    """Record a Task starting or finishing. Never raises.

    닫을 때는 같은 종류의 **가장 오래된** 항목을 지운다. 같은 에이전트를 병렬로 둘
    돌리면 어느 것이 끝났는지 구분할 수 없는데, 그 경우 남는 개수는 어느 쪽을
    지워도 같다. 개수가 맞으면 "몇 개가 열려 있는가"라는 판정은 보존된다.
    """
    try:
        p = _agents_path(project_dir)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            with open(p, encoding="utf-8") as fh:
                state = json.load(fh)
            if not isinstance(state, dict):
                state = {}
        except (OSError, ValueError):
            state = {}
        rows = [r for r in state.get(sess, []) if isinstance(r, dict)]
        if opening:
            rows.append({"type": kind, "ts": int(time.time())})
        else:
            for i, r in enumerate(rows):
                if r.get("type") == kind:
                    del rows[i]
                    break
            else:
                if rows:
                    del rows[0]
        # 세션이 끝나도 상태 파일은 남는다. 하루 넘은 항목은 버려서 파일이 자라거나
        # 죽은 항목이 영원히 "열려 있음"으로 남는 것을 막는다.
        cut = int(time.time()) - 86400
        state[sess] = [r for r in rows if r.get("ts", 0) >= cut]
        state = {k: v for k, v in state.items() if v}
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception:
        pass


def transcript_mark(payload):
    """Short fingerprint of transcript_path, or ''.

    서브에이전트가 별도 transcript 를 쓰는 환경이라면 이 값이 부모와 갈린다.
    실제로 갈리는지는 모아 본 로그가 답하므로, 판정하지 않고 기록만 한다.
    """
    tp = payload.get("transcript_path") or ""
    if not tp:
        return ""
    base = os.path.basename(tp)
    return os.path.splitext(base)[0][-8:]


def log(project_dir, rec):
    """Append one record to the project's gitignored state dir.

    체크아웃 안이 아니라 여기다. 체크아웃 안에 두면 체크아웃이 다시 만들어질 때
    로그가 함께 사라지고, 계측은 오래 두고 값을 재야 의미가 있다. `phpstats` 가
    같은 경로를 읽는다.
    """
    if not project_dir:
        return
    try:
        d = os.path.join(project_dir, ".claude", ".state")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "tooling.jsonl")
        if os.path.exists(p) and os.path.getsize(p) > MAX_LOG:
            os.replace(p, p + ".1")
        rec["ts"] = int(time.time())
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def emit(message):
    try:
        json.dump({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": message,
        }}, sys.stdout)
    except Exception:
        pass
    sys.exit(0)


def classify(cmd, root_abs, cwd_in_tree):
    """Every tool call in one command, as [(tool, mode, arg), ...].

    A general-purpose tool counts as a bypass only when it actually targets
    source in the tree - appending to a doc is not a bypass of `phpv`. Dedicated
    and general calls are both collected: returning early on the first dedicated
    hit erased the bypass sitting in the same command, and every such erasure
    moved the ratio the same way.
    """
    out = []
    for seg in _segments(cmd):
        head = _leading_command(seg)
        if not head:
            continue
        base, args = head
        clean = []
        for a in args:                       # a redirect is not an argument
            if a.startswith(">") or a.startswith("<"):
                break
            clean.append(a)
        if base in OUR_TOOLS:
            sub = ""
            if clean and re.match(
                    r"^(--?[\w-]+|open|save|discard|status|replace"
                    r"|lint|pin|check|callers|fields|capture|compare|corpus)$",
                    clean[0]):
                sub = clean[0]
            out.append((base, sub, " ".join(clean)[:60]))
            continue
        if not _targets_source(seg, root_abs, cwd_in_tree):
            continue
        if base in GREP_CMDS:
            out.append(("raw-grep", "", ""))
        elif base in READ_CMDS and not re.search(r"(^|[^>])>>?\s*\S", seg):
            out.append(("raw-read", "", ""))
    return out


def service_for(cmd, cwd, tree_root, ours):
    """Which service a call touched. A path in the command wins over cwd.

    cwd 로만 보면 이 OS 의 호출은 거의 전부 귀속되지 않는다. 체크아웃보다 한 단계
    위에서 돌고 `cd` 를 쓰지 않기 때문이다. 실측으로 기록의 76%가 비어 있었다.
    """
    if tree_root and cmd:
        m = re.search(re.escape(os.path.abspath(tree_root)) + r"/\S+", cmd)
        if m:
            svc = service_of(m.group(0), tree_root, ours)
            if svc:
                return svc
    return service_of(cwd, tree_root, ours)


def attribution(payload, project_dir, sess):
    """Which pipeline stage made this call, and where that answer came from.

    훅 입력이 스스로 `agent_type`/`agent_id` 를 말해 주면 **그것이 정본이다.**
    `Task` 등록 상태는 그 필드가 없는 환경을 위한 폴백으로만 남는다 — 등록은
    세션 공유 `session_id` 위에 세워져 있어서 같은 종류를 병렬로 둘 돌리면 어느
    쪽인지 말할 수 없고, 그 모호함을 `agents` 수로만 표시할 수 있었다.

    `src` 를 함께 적는다. 두 경로의 정확도가 다르므로, 뒤에 로그를 읽을 때
    어느 쪽으로 붙은 귀속인지 구별할 수 없으면 둘의 차이도 잴 수 없다.
    """
    kind = payload.get("agent_type") or ""
    aid = payload.get("agent_id") or ""
    if kind or aid:
        return {"agent": kind or None, "agent_id": aid or None,
                "agents": 1, "src": "input", "tp": transcript_mark(payload)}
    # 열린 것이 없으면 부모다. 하나면 그것이 답이다. 둘 이상이면 **모호하다고
    # 적는다** — 하나를 골라 적으면 틀린 귀속이 사실처럼 로그에 남고, 그 로그를
    # 근거로 단계별 배정을 판정하게 된다.
    agents = open_agents(project_dir, sess)
    return {"agent": agents[0] if len(agents) == 1 else None,
            "agents": len(agents), "src": "task",
            "tp": transcript_mark(payload)}


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    sess = (payload.get("session_id") or "")[:8]

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    event = payload.get("hook_event_name") or ""

    # ---- 귀속: 어느 서브에이전트가 돌고 있는지 기록한다 --------------------
    # 설정보다 먼저 온다. 이것은 레거시 체크아웃과 무관한 일이고, 설정이 없어서
    # 계측이 꺼져 있는 세션에서도 귀속 상태는 맞게 유지되어야 한다.
    if tool == "Task":
        kind = ti.get("subagent_type") or ti.get("agent_type") or "?"
        mark_agent(project_dir, sess, kind, opening=(event != "PostToolUse"))
        return
    if event == "PostToolUse":
        return          # 나머지 도구의 PostToolUse 는 이 훅의 일이 아니다

    legacy = config(project_dir)
    root = legacy.get("root")
    if not root:
        return
    attrib = attribution(payload, project_dir, sess)
    root_abs = os.path.abspath(root)
    tree_root = legacy.get("treeRoot")
    ours = legacy.get("ours") or {}
    # 도구는 이 프로젝트에 있다. 넛지가 가리키는 경로가 틀리면 넛지는 없는 것보다
    # 나쁘다 — 매번 그럴듯한 문장으로 잘못된 방향을 가리키고, 그것이 틀렸다는
    # 신호가 아무 데도 없다.
    scripts_hint = os.path.join(project_dir, ".claude", "scripts")
    index_dir = os.path.join(project_dir, ".claude", ".state", "index")

    # ---- Read tool on a file in the checkout = bypassing phpv ---------------
    if tool == "Read":
        fp = ti.get("file_path") or ""
        if not fp:
            return
        ap = os.path.abspath(fp).replace("\\", "/")
        # 인덱스 검사가 체크아웃 검사보다 먼저 온다. 인덱스는 이제 이 프로젝트의
        # 상태 디렉터리에 있어서 체크아웃 밖이고, 순서가 반대이면 인덱스를 직접
        # 읽는 것이 조용히 통과한다.
        if ap.startswith(index_dir.replace("\\", "/") + "/"):
            log(project_dir, {"tool": "read-index", "mode": "", "svc": None,
                              "arg": os.path.basename(fp), "nudge": 1,
                              "sess": sess, **attrib})
            emit("인덱스 JSON 은 직접 읽지 않는다. 파일 하나가 수 MB 다. "
                 f"`{scripts_hint}/phpwhere <이름>` / `--tpl` / `--entry` 로 조회하라.")
        if not ap.startswith(root_abs):
            return
        svc = service_of(fp, tree_root, ours)
        # 소스만 우회로 센다. 마크다운과 설정 파일은 `phpv` 가 대신할 수 있는
        # 대상이 아니어서, 그것까지 세면 읽기 비율이 대신할 길 없는 읽기에 눌린다.
        if not ap.lower().endswith(SOURCE_EXT):
            return
        log(project_dir, {"tool": "Read", "mode": "", "svc": svc,
                   "arg": os.path.basename(fp), "nudge": 1, "sess": sess,
                   **attrib})
        emit("이 트리는 파일마다 인코딩이 다르다. Read 는 CP949 파일의 한글을 "
             "깨진 글자로 보여주고, 그 손실은 화면에 아무 표시도 남기지 않는다. "
             f"`{scripts_hint}/phpv <파일>` 로 읽어라.")
        return

    if tool != "Bash":
        return
    cmd = strip_heredocs(ti.get("command") or "")

    # 관심사인지는 `classify` 가 정한다. 전에는 그 앞에 "체크아웃 경로가 명령에
    # 있는가"라는 게이트가 있었는데, 도구가 체크아웃 안에 있던 동안에는 도구를
    # 절대경로로 부르는 것이 그 조건을 저절로 만족했다. 2026-09-08 에 도구를 이
    # 저장소로 옮기자 그 우연이 끊기고, **전용 도구 호출이 통째로 기록되지 않게
    # 됐다.** 인자에 트리 경로가 들어가는 호출(`phpv <파일>`)만 남고, 이름이나
    # 패턴을 넘기는 호출(`phpwhere <이름>`, `phpgrep <낱말>`)이 전부 빠졌다 —
    # 그리고 그 빠진 쪽이 하필 이 계측이 재려던 것이었다.
    #
    # 전용 도구는 대상 트리만 다루므로, 명령 위치에서 그것이 불렸다는 사실 자체가
    # 관심사라는 뜻이다. 우회 쪽은 `classify` 안의 `_targets_source` 가 여전히
    # 트리를 향하는지 확인한다 — 그러지 않으면 모든 `grep` 이 기록된다.
    cwd_in_tree = os.path.abspath(cwd).startswith(root_abs)
    calls = [c for c in classify(cmd, root_abs, cwd_in_tree)
             if c[0] != "phpstats"]
    if not calls:
        return          # a stats lookup does not record itself
    svc = service_for(cmd, cwd, tree_root, ours)
    what, mode, arg = calls[0]

    # ---- nudges -------------------------------------------------------------
    # 낼 넛지를 정하기만 하고, 기록을 모두 마친 뒤에 내보낸다. `emit` 은 프로세스를
    # 끝내므로 기록보다 먼저 부르면 같은 명령의 나머지 호출이 통째로 사라진다.
    # 그러면 넛지가 걸린 명령일수록 기록이 적어져, 지표가 조용히 기운다.
    nudge_msg = None
    marked = None           # calls 안에서 nudge=1 로 표시할 도구
    marked_mode = None      # 그 줄의 mode 를 덮어쓸 값
    extra = []              # 호출과 별개로 남길 줄

    if INDEX_REF.search(cmd) and any(c[0] == "raw-read" for c in calls):
        extra.append(("read-index", "", arg))
        nudge_msg = ("`.claude/index/*.json` 은 직접 읽지 않는다. 파일 하나가 수 MB 라 "
                     "컨텍스트만 소모한다. `phpwhere <이름>` 으로 조회하라.")

    elif any(c[0] == "phpwhere" for c in calls) and not os.path.isdir(index_dir):
        marked = "phpwhere"
        nudge_msg = (f"인덱스가 아직 없다. 먼저 `{scripts_hint}/phpindex --all` 을 "
                     f"돌려라 (약 10초).")

    else:
        # Only what phpgrep itself received. A different command's long option
        # (`grep --include='*.md'`) must not reach the definition test.
        grep_args = " ".join(a for t, _, a in calls if t == "phpgrep")
        if grep_args and DEF_SHAPED.search(grep_args):
            names = [n for n in NAME_IN_PATTERN.findall(grep_args)
                     if n not in STOP]
            hint = f"`phpwhere {names[0]}`" if names else "`phpwhere <이름>`"
            marked, marked_mode = "phpgrep", "def-shaped"
            nudge_msg = ("정의를 찾는 검색으로 보인다. 이 트리에서 grep 은 정의를 못 찾는 "
                         "경우가 많다 — 실제 정의가 `$X[상수] = 값` 형태면 `$X =` 검색은 "
                         f"0건이 나오고, 그 0건은 '없다'가 아니다. {hint} 를 먼저 써라. "
                         "phpgrep 은 '누가 쓰는가'를 물을 때 쓴다.")

        # 우회한 쪽에도 알린다. 넛지가 전용 도구를 이미 쓰는 호출에만 걸려 있으면,
        # 도구를 아예 모르는 호출자는 아무 신호도 받지 못한 채 한 줄 기록되고 끝난다.
        # 그 상태에서도 넛지 수는 0 이므로, 지표가 "규칙이 붙었다"와 "도구가 한 번도
        # 쓰이지 않았다"를 구분하지 못한다.
        elif any(c[0] == "raw-grep" for c in calls):
            marked = "raw-grep"
            nudge_msg = ("이 트리는 파일마다 인코딩이 다르다. 한 인코딩으로 한글을 찾으면 "
                         "다른 인코딩의 파일이 통째로 빠지는데, 에러가 아니라 0건으로 "
                         f"돌아온다. `{scripts_hint}/phpgrep <검색어>` 는 두 인코딩을 "
                         "모두 훑고 무엇을 뒤졌는지 매번 출력한다.")

        elif any(c[0] == "raw-read" for c in calls):
            marked = "raw-read"
            nudge_msg = ("이 트리는 파일마다 인코딩이 다르다. 범용 읽기는 CP949 파일의 "
                         "한글을 깨진 글자로 보여주고, 그 손실은 아무 표시도 남기지 "
                         f"않는다. `{scripts_hint}/phpv <파일>` 로 읽어라.")

    # ---- record, then speak -------------------------------------------------
    done = False
    for t, md, a in calls:
        n = 0
        if not done and t == marked:
            n, done = 1, True
            md = marked_mode or md
        log(project_dir, {"tool": t, "mode": md, "svc": svc, "arg": a,
                   "nudge": n, "sess": sess, **attrib})
    for t, md, a in extra:
        log(project_dir, {"tool": t, "mode": md, "svc": svc, "arg": a,
                   "nudge": 1, "sess": sess, **attrib})
    if nudge_msg:
        emit(nudge_msg)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
