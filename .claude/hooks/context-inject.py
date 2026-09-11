#!/usr/bin/env python3
"""컨텍스트 결정적 주입 훅 (SubagentStart · PreToolUse)

`.claude/context/*.md` 의 프론트매터가 라우팅 표다. 세 트리거로 발동한다.

  agent   SubagentStart — 시작하는 서브에이전트 이름이 `inject.agents` 에 있으면 주입
  skill   PreToolUse(Skill) — 호출된 스킬 이름이 `inject.skills` 에 있으면 주입
  path    PreToolUse(Read|Edit|Write|Bash) — 인자의 절대경로가 `inject.paths` 글롭에
          맞으면 주입. 경로 글롭 안의 `${key}` 는 workspace.json 에서 치환한다

왜 훅인가. LLM 에게 "필요하면 읽어라"로 맡기면 느리고(초 단위) 비결정적이다 — 그리고
빠뜨렸다는 사실이 아무 데도 남지 않는다. 훅은 ms 단위이고, 결정적이고, **주입한 것을
로그로 남기므로 주입 자체를 테스트할 수 있다.** 이 파일이 존재하는 이유가 마지막 항목이다.

예산과 우선순위. 한 번에 넣는 양에는 상한(`MAX_INJECT_BYTES`)이 있고, 넘치면 파일
단위로 자른다. 자르는 순서는 프론트매터의 `inject.priority` 가 정한다(작을수록 먼저
담고, 없으면 `DEFAULT_PRIORITY`). **잘린 파일 이름은 주입된 블록 머리에 남는다** —
받는 에이전트가 자기가 무엇을 못 받았는지 알아야 하고, stderr 는 그쪽에 닿지 않는다.

중복 억제. 같은 세션·같은 에이전트에 같은 파일을 두 번 주입하지 않는다. 컨텍스트는
쓸수록 썩는 유한 자원이고, 같은 문단을 반복해 넣는 것은 그 자원을 태우면서 아무것도
더 알려주지 않는다. 상태는 `.claude/.state/context-injected.json` 에 남는다 — 훅은
호출마다 새 프로세스라 메모리로는 이어지지 않는다.

**이 훅은 어떤 경우에도 도구 실행을 막지 않는다.** 실패하면 조용히 exit 0 하고 이유만
stderr 로 흘린다. 컨텍스트를 못 넣은 것은 불편이고, 도구를 막는 것은 사고다.

설정이 없으면 **경로 트리거만** 꺼진다. 에이전트·스킬 트리거는 설정을 읽지 않으므로
계속 돈다. 그 사실은 세션마다 한 번 stderr 에 적는다 — 조용히 좁아진 동작이 이 저장소가
반복해서 기록한 실패 모양이다.

`CONTEXT_INJECT_OFF=1` 로 세션을 시작하면 주입하지 않는다. A/B 비교의 B 쪽이다 —
같은 스킬을 컨텍스트 없이 돌리기 위한 스위치이고, 꺼졌다는 사실은 stderr 로 말한다.

`--check` 로 부르면 훅이 아니라 검사기로 돈다(라우팅 표 검증). 그때만 0 이 아닌 코드를
낸다: 0 깨끗, 1 이름 어긋남(--strict), 2 프론트매터를 읽을 수 없음.
"""
import fnmatch
import json
import os
import re
import sys
import time

# ---------------------------------------------------------------- 상수(스위치)

# SubagentStart 의 출력 형식은 문서에 명시돼 있지 않다. 두 형식을 모두 구현해 두고
# 실측(docs/context-system.md 의 프로브 절차)으로 고른다. 프로브 전에는 "모른다"가
# 정답이므로, 어느 쪽이 맞는지 코드가 단정하지 않는다.
#   "json"   -> {"hookSpecificOutput": {"hookEventName": "SubagentStart", ...}}
#   "stdout" -> 평문을 그대로 stdout 에
SUBAGENT_OUTPUT = "json"

# 위 둘 다 서브에이전트에 닿지 않을 때의 폴백. PreToolUse(Task) 에서 도구 입력을
# 통째로 돌려주며 `prompt` 끝에 컨텍스트를 덧붙인다. 기본은 꺼둔다 — 켜면 프롬프트가
# 길어지고, SubagentStart 가 동작하는 환경에서는 같은 내용이 두 번 들어간다.
TASK_FALLBACK = False

# 한 번에 주입할 수 있는 최대 바이트. 넘으면 파일 단위로 자른다(문단 중간에서 자르지
# 않는다). 컨텍스트를 아끼자고 만든 장치가 컨텍스트를 태우면 안 된다.
MAX_INJECT_BYTES = 24 * 1024

# 예산이 찼을 때 **무엇을 먼저 버리는가**. 프론트매터의 `inject.priority` 가 그것을
# 정한다 — 작을수록 먼저 담고, 없으면 이 값이다.
#
# 예산 안에 넣는 순서를 파일 이름에 맡기면 알파벳이 정책이 된다. 감사자에게 들어가는
# 파일 여섯은 예산의 9할을 쓰고 있었고, 그 순서에서 마지막인 것은 공개 저장소 경계
# 파일이었다 — 즉 예산이 넘칠 때 가장 먼저 버려지는 것이 하필 "회사 내용을 추적
# 파일에 쓰지 말라"는 규칙이었다. 우선순위는 그 결과를 이름이 아니라 판단으로
# 정하기 위해 있다.
DEFAULT_PRIORITY = 50
MAX_LOG = 5 * 1024 * 1024
STATE_TTL = 86400
COUNTS = "__counts"
BASH_PATH_LIMIT = 60

PATH_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit")
RE_ABS_PATH = re.compile(r"(?<![\w=])(/[A-Za-z0-9._/\-]{3,})")
RE_SUBST = re.compile(r"\$\{([A-Za-z0-9_.]+)\}")


def warn(msg):
    try:
        sys.stderr.write("context-inject: " + msg + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- 프로젝트·설정

def project_dir(payload=None):
    """이 OS 체크아웃. `.claude/context/` 를 가진 최초 조상."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        d = os.path.abspath(os.path.expanduser(env))
        if os.path.isdir(os.path.join(d, ".claude", "context")):
            return d
    here = os.path.dirname(os.path.abspath(__file__))
    for start in (here, (payload or {}).get("cwd") or os.getcwd()):
        d = os.path.abspath(start)
        while True:
            if os.path.isdir(os.path.join(d, ".claude", "context")):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return None


def load_config(project, override=None):
    """workspace.json 전체. `(dict, 문제 이유 or None)`.

    `legacy` 절만 읽는 기존 도구들과 달리 여기서는 전체가 필요하다 — 경로 글롭이
    `${backend.root}` 처럼 다른 절도 가리키기 때문이다.
    """
    path = override or (os.path.join(project, ".claude", "config", "workspace.json")
                        if project else None)
    if not path:
        return {}, "프로젝트를 찾지 못해 설정 경로를 알 수 없다"
    if not os.path.isfile(path):
        return {}, f"{path} 가 없다 — 경로 트리거만 꺼진다"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return {}, f"{path} 를 읽을 수 없다: {exc}"
    return (data if isinstance(data, dict) else {}), None


def resolve(spec, cfg, project):
    """`${a.b}` 를 설정 값으로 바꾼다. 못 바꾸면 None(= 이 글롭은 쓸 수 없다).

    `${project.root}` 만은 설정이 아니라 이 체크아웃 자신이다. 이 OS 의 경계 규칙은
    설정 없이도 걸려야 하므로 예외를 둔다.
    """
    missing = []

    def one(m):
        key = m.group(1)
        if key == "project.root":
            if not project:
                missing.append(key)
                return ""
            return project
        cur = cfg
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                missing.append(key)
                return ""
            cur = cur[part]
        if not isinstance(cur, str) or not cur:
            missing.append(key)
            return ""
        return cur

    out = RE_SUBST.sub(one, spec)
    return None if missing else out


# ---------------------------------------------------------------- 프론트매터

def parse_front(text, name):
    """`---` 프론트매터의 최소 YAML. 실패하면 ValueError 로 이유를 말한다."""
    if not text.startswith("---"):
        raise ValueError(f"{name}: 프론트매터가 `---` 로 시작하지 않는다")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError(f"{name}: 프론트매터가 닫히지 않았다")
    head = text[text.find("\n", 3) + 1:end]
    body = text[end + 4:].lstrip("\n")

    def value(raw):
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
        if raw.startswith(("'", '"')):
            q = raw[0]
            j = raw.find(q, 1)
            return raw[1:j] if j > 0 else raw[1:]
        raw = raw.split(" #")[0].strip()
        return raw

    meta, cur_map, cur_list = {}, None, None
    for line in head.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        s = line.strip()
        if s.startswith("- "):
            if cur_list is None:
                raise ValueError(f"{name}: 목록 항목이 키 없이 나왔다 — {s!r}")
            cur_list.append(value(s[2:]))
            continue
        if ":" not in s:
            raise ValueError(f"{name}: 키가 아닌 줄 — {s!r}")
        key, raw = s.split(":", 1)
        key, raw = key.strip(), raw.strip()
        if indent == 0:
            cur_map, cur_list = None, None
            if raw == "":
                meta[key] = {}
                cur_map = meta[key]
            else:
                meta[key] = value(raw)
        else:
            if cur_map is None:
                raise ValueError(f"{name}: 들여쓴 키의 부모가 없다 — {s!r}")
            if raw == "":
                cur_map[key] = []
                cur_list = cur_map[key]
            else:
                cur_map[key] = value(raw)
                cur_list = None
    for req in ("name", "kind", "token"):
        if not meta.get(req):
            raise ValueError(f"{name}: `{req}` 가 없다")
    inject = meta.get("inject")
    if not isinstance(inject, dict):
        raise ValueError(f"{name}: `inject` 절이 없다")
    for k in ("agents", "skills", "paths", "tools"):
        v = inject.get(k, [])
        if isinstance(v, str):
            v = [v] if v else []
        if not isinstance(v, list):
            raise ValueError(f"{name}: `inject.{k}` 가 목록이 아니다")
        inject[k] = v
    # 우선순위는 정수다. 숫자가 아니면 여기서 말한다 — 조용히 기본값으로 바꾸면
    # 오타 하나가 그 파일을 예산 경계로 밀어내고, 밀려난 사실이 아무 데도 남지 않는다.
    prio = inject.get("priority", DEFAULT_PRIORITY)
    try:
        inject["priority"] = int(str(prio).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{name}: `inject.priority` 가 정수가 아니다 — {prio!r}")
    meta["inject"] = inject
    meta["body"] = body
    return meta


def load_context(project):
    """`(항목 목록, 오류 목록)`. 하나가 깨져도 나머지는 산다."""
    items, errors = [], []
    d = os.path.join(project, ".claude", "context") if project else None
    if not d or not os.path.isdir(d):
        return items, [f"{d} 가 없다"]
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md") or fn.startswith("_"):
            continue
        p = os.path.join(d, fn)
        try:
            with open(p, encoding="utf-8") as fh:
                meta = parse_front(fh.read(), fn)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
            continue
        meta["file"] = fn
        meta["path"] = p
        items.append(meta)
    return items, errors


# ---------------------------------------------------------------- 상태·로그

def state_path(project):
    return os.path.join(project, ".claude", ".state", "context-injected.json")


def read_state(project):
    try:
        with open(state_path(project), encoding="utf-8") as fh:
            s = json.load(fh)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(project, state):
    try:
        p = state_path(project)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + f".{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, p)
    except Exception:
        pass


def prune(state, now):
    for sess in list(state.keys()):
        if sess.startswith("__"):
            continue
        rows = state.get(sess)
        if not isinstance(rows, dict):
            del state[sess]
            continue
        for k, ts in list(rows.items()):
            if not isinstance(ts, (int, float)) or ts < now - STATE_TTL:
                del rows[k]
        if not rows:
            del state[sess]
    counts = state.get(COUNTS)
    if isinstance(counts, dict):
        for sess, row in list(counts.items()):
            if not isinstance(row, dict) or row.get("ts", 0) < now - STATE_TTL:
                del counts[sess]
        if not counts:
            del state[COUNTS]
    elif COUNTS in state:
        del state[COUNTS]
    return state


def bump(state, sess, matched, injected, now):
    """트리거가 맞은 횟수와 실제로 주입한 횟수. 둘의 차이가 중복 억제량이다.

    억제된 호출은 로그에 줄을 남기지 않는다 — 로그는 "무엇이 주입됐는가"여야 하고,
    억제가 그 로그의 대부분을 차지하면 로그가 자기 목적을 잃는다. 그래서 수치는
    상태 파일의 예약 키에 센다. `ctxstats` 가 이 둘로 억제율을 낸다.
    """
    row = state.setdefault(COUNTS, {}).setdefault(sess or "-", {"matched": 0,
                                                                "injected": 0,
                                                                "ts": now})
    row["matched"] = row.get("matched", 0) + matched
    row["injected"] = row.get("injected", 0) + injected
    row["ts"] = now


def log(project, rec):
    try:
        d = os.path.join(project, ".claude", ".state")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "context-injections.jsonl")
        if os.path.exists(p) and os.path.getsize(p) > MAX_LOG:
            os.replace(p, p + ".1")
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- 매칭

def short(name):
    return name.split(":")[-1].strip()


def match_agent(items, agent_type):
    if not agent_type:
        return []
    a = short(agent_type)
    return [it for it in items
            if a in [short(x) for x in it["inject"]["agents"]]]


def match_skill(items, skill):
    if not skill:
        return []
    s = short(skill)
    return [it for it in items
            if s in [short(x) for x in it["inject"]["skills"]]]


def candidate_paths(tool, tool_input):
    """도구 입력에서 판정에 쓸 절대경로들."""
    out = []
    if tool in PATH_TOOLS:
        for key in ("file_path", "notebook_path", "path"):
            v = tool_input.get(key)
            if isinstance(v, str) and v.startswith("/"):
                out.append(v)
    elif tool == "Bash":
        cmd = tool_input.get("command")
        if isinstance(cmd, str):
            for m in RE_ABS_PATH.finditer(cmd):
                out.append(m.group(1))
                if len(out) >= BASH_PATH_LIMIT:
                    break
    return out


def match_path(items, paths, tool, cfg, project):
    hit = []
    if not paths:
        return hit
    for it in items:
        tools = it["inject"].get("tools") or []
        if tools and tool not in tools:
            continue
        for spec in it["inject"]["paths"]:
            glob = resolve(spec, cfg, project)
            if not glob:
                continue
            if any(fnmatch.fnmatch(p, glob) for p in paths):
                hit.append(it)
                break
    return hit


# ---------------------------------------------------------------- 조립·출력

def render(items, trigger, errors=()):
    """`(주입할 텍스트, 실제로 담은 항목)`.

    **우선순위 순으로 담고, 잘린 것을 블록 안에 적는다.** 예산이 차면 그 뒤는 전부
    잘린다 — 남은 자리에 더 작은 뒤 파일을 끼워 넣으면 우선순위가 뒤집힌다.

    잘렸다는 사실은 stderr 만으로는 부족하다. exit 0 한 훅의 stderr 는 받는
    에이전트에 닿지 않으므로, 그쪽에서는 "이 파일은 원래 안 오는 것"과 구별할 수
    없다. 그래서 블록 머리에 한 줄로 남긴다 — 무엇을 못 받았는지 알면 직접 읽을 수
    있고, 모르면 없는 규칙처럼 행동한다.
    """
    parts, kept, cut = [], [], []
    used = 0
    for it in sorted(items, key=lambda x: (x["inject"]["priority"], x["file"])):
        block = (f"\n<context name=\"{it['name']}\" kind=\"{it['kind']}\" "
                 f"token=\"{it['token']}\">\n{it['body'].rstrip()}\n</context>")
        b = len(block.encode("utf-8"))
        if cut or (used + b > MAX_INJECT_BYTES and kept):
            cut.append(it["file"])
            continue
        parts.append(block)
        used += b
        kept.append(it)
    head = ["# 자동 주입된 컨텍스트 — `.claude/context/` "
            f"(트리거: {trigger} · 세션·에이전트당 파일 1회)"]
    if cut:
        warn(f"{', '.join(cut)} 은 이번 주입에서 잘렸다(예산 {MAX_INJECT_BYTES}B)")
        head.append(f"# 예산({MAX_INJECT_BYTES}B)이 차서 넣지 못한 파일: "
                    + ", ".join(cut)
                    + " — 이 내용은 받지 못했으므로, 필요하면 "
                      "`.claude/context/<파일>` 을 직접 읽어라.")
    if errors:
        head.append("# 읽지 못한 컨텍스트 파일이 있다(프론트매터 오류): "
                    + " / ".join(str(e) for e in errors))
    return "\n".join(head + parts), kept


def emit_pre(text, updated_input=None):
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "additionalContext": text}}
    if updated_input is not None:
        out["hookSpecificOutput"]["updatedInput"] = updated_input
    json.dump(out, sys.stdout, ensure_ascii=False)


def emit_subagent(text):
    if SUBAGENT_OUTPUT == "stdout":
        sys.stdout.write(text)
    else:
        json.dump({"hookSpecificOutput": {"hookEventName": "SubagentStart",
                                          "additionalContext": text}},
                  sys.stdout, ensure_ascii=False)


# ---------------------------------------------------------------- 검사기

def check(argv):
    strict = "--strict" in argv
    project = project_dir()
    if not project:
        warn("프로젝트를 찾지 못했다")
        return 2
    items, errors = load_context(project)
    for e in errors:
        print(f"오류  {e}")
    if errors:
        return 2
    if not items:
        print("오류  컨텍스트 파일이 하나도 없다")
        return 2
    tokens, dup = {}, []
    for it in items:
        if it["token"] in tokens:
            dup.append(f"{it['file']} 과 {tokens[it['token']]} 의 token 이 같다")
        tokens[it["token"]] = it["file"]
    agents = {os.path.splitext(f)[0]
              for f in os.listdir(os.path.join(project, ".claude", "agents"))
              if f.endswith(".md")} if os.path.isdir(
                  os.path.join(project, ".claude", "agents")) else set()
    sk_root = os.path.join(project, ".claude", "skills")
    skills = {n for n in (os.listdir(sk_root) if os.path.isdir(sk_root) else [])
              if os.path.isfile(os.path.join(sk_root, n, "SKILL.md"))}
    unknown = []
    for it in items:
        for a in it["inject"]["agents"]:
            if short(a) not in agents:
                unknown.append(f"{it['file']}: 에이전트 `{a}` 가 없다")
        for s in it["inject"]["skills"]:
            if short(s) not in skills:
                unknown.append(f"{it['file']}: 스킬 `{s}` 가 없다")
    cfg, problem = load_config(project)
    for it in items:
        for spec in it["inject"]["paths"]:
            if resolve(spec, cfg, project) is None:
                unknown.append(f"{it['file']}: 경로 글롭 `{spec}` 의 키를 설정에서 못 찾았다")
    print(f"컨텍스트 {len(items)}개 · 토큰 {len(tokens)}개"
          + (f" · 설정 문제: {problem}" if problem else ""))
    # 우선순위 순으로 찍는다. 예산이 찰 때 잘리는 순서가 이 순서이고, 그것을 눈으로
    # 확인할 수 있는 자리가 여기밖에 없다.
    for it in sorted(items, key=lambda x: (x["inject"]["priority"], x["file"])):
        n = len(it["body"].splitlines())
        print(f"  {it['file']:<30} {it['kind']:<4} {it['token']:<26} "
              f"우선 {it['inject']['priority']:>3} · 본문 {n}줄")
    for d in dup:
        print(f"오류  {d}")
    for u in unknown:
        print(f"경고  {u}")
    if dup:
        return 2
    if unknown and strict:
        return 1
    return 0


# ---------------------------------------------------------------- 본체

def main():
    if "--check" in sys.argv[1:]:
        sys.exit(check(sys.argv[1:]))
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(__doc__)
        sys.exit(0)

    # A/B 스위치. 주입 없이 같은 스킬을 돌려 비교하려면 이 값을 켜고 세션을 시작한다
    # (훅은 세션 시작 시점에 스냅샷되므로 세션 중간에 끄고 켤 수 없다). 꺼졌다는
    # 사실은 반드시 말한다 — 조용히 안 도는 훅은 "주입이 필요 없었다"로 오독된다.
    if os.environ.get("CONTEXT_INJECT_OFF"):
        warn("CONTEXT_INJECT_OFF 가 설정돼 있어 주입하지 않는다 (A/B 의 B 쪽)")
        return

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        warn("훅 입력이 JSON 이 아니다")
        return
    project = project_dir(payload)
    if not project:
        warn("프로젝트를 찾지 못했다 — 주입하지 않는다")
        return

    event = payload.get("hook_event_name") or ""
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    sess = payload.get("session_id") or ""
    agent_id = payload.get("agent_id") or ""
    agent_type = payload.get("agent_type") or ""

    items, errors = load_context(project)
    for e in errors:
        warn(e)          # 깨진 파일 하나가 나머지 주입을 막지 않는다
    if not items:
        return

    trigger, hits, updated = "", [], None
    if event == "SubagentStart":
        trigger = "agent"
        agent_type = agent_type or payload.get("subagent_type") or ""
        hits = match_agent(items, agent_type)
    elif event == "PreToolUse" and tool == "Skill":
        trigger = "skill"
        hits = match_skill(items, tool_input.get("skill") or "")
    elif event == "PreToolUse" and tool == "Task" and TASK_FALLBACK:
        trigger = "agent"
        agent_type = tool_input.get("subagent_type") or ""
        hits = match_agent(items, agent_type)
    elif event == "PreToolUse":
        trigger = "path"
        cfg, problem = load_config(project)
        if problem:
            hits = []
        else:
            hits = match_path(items, candidate_paths(tool, tool_input), tool,
                              cfg, project)
    if not hits and trigger != "path":
        return

    now = int(time.time())
    state = prune(read_state(project), now)
    room = state.setdefault(sess or "-", {})

    if trigger == "path":
        cfg, problem = load_config(project)
        if problem and "_cfgwarn" not in room:
            room["_cfgwarn"] = now
            write_state(project, state)
            warn(problem + " (에이전트·스킬 트리거는 그대로 동작한다)")
        if problem:
            return

    who = agent_id or (f"type:{agent_type}" if agent_type else "main")
    fresh = [it for it in hits if f"{who}|{it['name']}" not in room]
    if not fresh:
        if hits:
            bump(state, sess, len(hits), 0, now)
            write_state(project, state)
        return
    text, kept = render(fresh, trigger, errors)
    for it in kept:
        room[f"{who}|{it['name']}"] = now
        log(project, {"ts": now, "session_id": sess, "agent_id": agent_id,
                      "agent_type": agent_type, "trigger": trigger, "tool": tool,
                      "file": it["file"], "token": it["token"],
                      "bytes": len(it["body"].encode("utf-8"))})
    bump(state, sess, len(hits), len(kept), now)
    write_state(project, state)

    if event == "SubagentStart":
        emit_subagent(text)
    elif tool == "Task" and TASK_FALLBACK:
        updated = dict(tool_input)
        updated["prompt"] = (str(tool_input.get("prompt") or "")
                             + "\n\n" + text)
        emit_pre(text, updated)
    else:
        emit_pre(text)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:            # 훅 실패가 도구를 막지 않는다
        warn(f"물러난다: {exc!r}")
    sys.exit(0)
