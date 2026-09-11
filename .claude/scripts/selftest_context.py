#!/usr/bin/env python3
"""컨텍스트 주입 훅 케이스. 가짜 프로젝트를 향하게 해 실제 상태·로그를 건드리지 않는다.

    python3 selftest_context.py [훅 경로] [--strict]

주입이 결정적이 되면 주입 자체를 테스트할 수 있다 — 그것이 LLM 판단에 맡기는 방식
대신 훅을 고른 이유이고, 이 파일이 그 주장을 실제로 검증한다.

세 가지를 가른다.
  라우팅   맞는 대상에 주입되는가, 그리고 **틀린 대상에는 주입되지 않는가**.
           과잉 주입도 버그다 — 컨텍스트는 유한 자원이다
  출력형식 `SubagentStart` 의 형식은 문서에 없다. 두 형식과 폴백을 모두 돌려
           **셋 다 형식상 유효한지**까지만 본다. 어느 것이 실제로 서브에이전트에
           닿는지는 이 프로세스가 답할 수 없다 — 그건 새 세션의 프로브가 답한다
  이름정합 컨텍스트 파일이 가리키는 에이전트·스킬이 실제로 있는가.
           지금 시점에는 아직 없는 이름이 있을 수 있으므로 기본은 **경고**,
           `--strict` 일 때만 실패

가짜 디렉터리 이름은 이 파일이 스스로 정한다. 대상 체크아웃의 실제 이름을 쓰면 이
파일이 회사 정보를 담게 되고, 그러면 추적될 수 없다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ARGS = [a for a in sys.argv[1:]]
STRICT = "--strict" in ARGS
ARGS = [a for a in ARGS if not a.startswith("--")]
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
HOOK = ARGS[0] if ARGS else os.path.join(PROJECT, ".claude", "hooks",
                                         "context-inject.py")
if not os.path.isfile(HOOK):
    sys.exit(f"훅을 찾지 못했다: {HOOK}")

results, skipped = [], []


def check(name, ok, detail="", secs=None):
    results.append(bool(ok))
    mark = "통과" if ok else "FAIL"
    t = f" {secs * 1000:6.1f}ms" if secs is not None else ""
    print(f"{len(results):>2} {name:<44} {mark}{t}"
          + (f"  {detail}" if detail and not ok else ""))


def skip(name, why):
    """답할 수 없는 케이스. **집계에 넣지 않고** 이유를 찍는다.

    `results` 에 넣으면 `selftest.py` 가 읽는 `N/M` 이 어긋나 실패로 도착하고,
    그러면 "재지 못했다"가 "빨간불"과 같은 모양이 된다. 둘은 다른 사실이다.
    """
    skipped.append(name)
    print(f"{'':2} {name:<44} 건너뜀  {why}")


# ------------------------------------------------------------------ 가짜 환경
BASE = tempfile.mkdtemp(prefix="ctxtest-")
PROJ = os.path.join(BASE, "proj")
CHECKOUT = os.path.join(BASE, "checkout")       # 가짜. 실제 이름을 적지 않는다
BACKEND = os.path.join(BASE, "backend")
CTX = os.path.join(PROJ, ".claude", "context")
STATE = os.path.join(PROJ, ".claude", ".state")
CONFIG = os.path.join(PROJ, ".claude", "config", "workspace.json")
for d in (CTX, STATE, os.path.dirname(CONFIG),
          os.path.join(PROJ, ".claude", "agents"),
          os.path.join(CHECKOUT, "svc"), os.path.join(BACKEND, "mod")):
    os.makedirs(d, exist_ok=True)
SRC = os.path.join(CHECKOUT, "svc", "page.php")
open(SRC, "w").write("<?php echo 1;")
DOC = os.path.join(PROJ, "docs", "note.md")
os.makedirs(os.path.dirname(DOC), exist_ok=True)
open(DOC, "w").write("# note\n")
OUTSIDE = os.path.join(BASE, "elsewhere", "other.md")
os.makedirs(os.path.dirname(OUTSIDE), exist_ok=True)
open(OUTSIDE, "w").write("x\n")

json.dump({"legacy": {"root": CHECKOUT}, "backend": {"root": BACKEND}},
          open(CONFIG, "w"))


def ctxfile(name, kind, agents, skills, paths, token, tools=None, body=None,
            priority=None):
    lines = ["---", f"name: {name}", f"kind: {kind}", "inject:",
             f"  agents: [{', '.join(agents)}]",
             f"  skills: [{', '.join(skills)}]",
             "  paths: [" + ", ".join(f'"{p}"' for p in paths) + "]"]
    if tools:
        lines.append(f"  tools: [{', '.join(tools)}]")
    if priority is not None:
        lines.append(f"  priority: {priority}")
    lines += [f"token: {token}", "---", "", body or f"# {name}", "본문."]
    open(os.path.join(CTX, name + ".md"), "w",
         encoding="utf-8").write("\n".join(lines) + "\n")


ctxfile("alpha", "전문성", ["php-behavior-analyst"], ["php-legacy-io"], [],
        "CTX-T-ALPHA")
ctxfile("beta", "전문성", [], [], ["${legacy.root}/**"], "CTX-T-BETA")
ctxfile("gamma", "팀", [], [], ["${project.root}/**"], "CTX-T-GAMMA",
        tools=["Write", "Edit"])
ctxfile("delta", "도메인", ["domain-scribe"], [], ["${backend.root}/**"],
        "CTX-T-DELTA")


def run(payload, hook=HOOK, project=PROJ, timeout=60):
    t0 = time.time()
    p = subprocess.run([sys.executable, hook], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, "CLAUDE_PROJECT_DIR": project})
    return p, time.time() - t0


def tokens_in(proc):
    """출력에 실린 토큰들. JSON 이면 additionalContext 안에서, 아니면 평문에서."""
    out = proc.stdout or ""
    text = out
    try:
        data = json.loads(out)
        text = (data.get("hookSpecificOutput") or {}).get("additionalContext", "")
        upd = (data.get("hookSpecificOutput") or {}).get("updatedInput")
        if isinstance(upd, dict):
            text += str(upd.get("prompt", ""))
    except ValueError:
        pass
    return {t for t in ("CTX-T-ALPHA", "CTX-T-BETA", "CTX-T-GAMMA",
                        "CTX-T-DELTA") if t in text}


def logs():
    p = os.path.join(STATE, "context-injections.jsonl")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


def reset():
    for n in ("context-injections.jsonl", "context-injected.json"):
        try:
            os.remove(os.path.join(STATE, n))
        except OSError:
            pass


def pre(tool, tool_input, sess="s1", **kw):
    return {"hook_event_name": "PreToolUse", "tool_name": tool,
            "tool_input": tool_input, "session_id": sess, "cwd": BASE, **kw}


def sub(agent_type, sess="s1", agent_id="a1"):
    return {"hook_event_name": "SubagentStart", "agent_type": agent_type,
            "agent_id": agent_id, "session_id": sess, "cwd": BASE}


print(f"{'':2} {'케이스':<44} 판정")
print("-" * 84)

# ---------------------------------------------------------------- 1. 라우팅
reset()
p, s = run(sub("php-behavior-analyst"))
check("에이전트 이름으로 주입", tokens_in(p) == {"CTX-T-ALPHA"},
      f"got={tokens_in(p)} rc={p.returncode} err={p.stderr[:120]}", s)

reset()
p, s = run(sub("backend-slice-builder"))
check("대상이 아닌 에이전트에는 주입 안 함", tokens_in(p) == set(),
      f"got={tokens_in(p)}", s)

reset()
p, s = run(pre("Skill", {"skill": "php-legacy-io"}))
check("스킬 이름으로 주입", tokens_in(p) == {"CTX-T-ALPHA"}, f"got={tokens_in(p)}", s)

reset()
p, s = run(pre("Skill", {"skill": "plugin:php-legacy-io"}))
check("플러그인 접두사 붙은 스킬 이름도 매치", tokens_in(p) == {"CTX-T-ALPHA"},
      f"got={tokens_in(p)}", s)

reset()
p, s = run(pre("Skill", {"skill": "git-commit"}))
check("대상이 아닌 스킬에는 주입 안 함", tokens_in(p) == set(), f"got={tokens_in(p)}", s)

reset()
p, s = run(pre("Read", {"file_path": SRC}))
check("경로 글롭으로 주입 (Read)", tokens_in(p) == {"CTX-T-BETA"},
      f"got={tokens_in(p)}", s)

reset()
p, s = run(pre("Bash", {"command": f"/bin/cat {SRC} | head -5"}))
check("Bash 명령 안의 절대경로로 주입", tokens_in(p) == {"CTX-T-BETA"},
      f"got={tokens_in(p)}", s)

reset()
p, s = run(pre("Read", {"file_path": OUTSIDE}))
check("글롭 밖 경로에는 주입 안 함", tokens_in(p) == set(), f"got={tokens_in(p)}", s)

reset()
p, s = run(pre("Write", {"file_path": DOC, "content": "x"}))
check("tools 제한: Write 는 통과", tokens_in(p) == {"CTX-T-GAMMA"},
      f"got={tokens_in(p)}", s)

reset()
p, s = run(pre("Read", {"file_path": DOC}))
check("tools 제한: Read 는 안 걸림", tokens_in(p) == set(), f"got={tokens_in(p)}", s)

reset()
p, s = run(pre("Read", {"file_path": os.path.join(BACKEND, "mod", "A.kt")}))
check("${backend.root} 치환도 동작", tokens_in(p) == {"CTX-T-DELTA"},
      f"got={tokens_in(p)}", s)

# ---------------------------------------------------------------- 2. 중복 억제
reset()
run(sub("php-behavior-analyst"))
p, s = run(sub("php-behavior-analyst"))
check("같은 세션·같은 에이전트: 두 번째는 억제", tokens_in(p) == set(),
      f"got={tokens_in(p)}", s)

p, s = run(sub("php-behavior-analyst", agent_id="a2"))
check("다른 서브에이전트에는 다시 주입", tokens_in(p) == {"CTX-T-ALPHA"},
      f"got={tokens_in(p)}", s)

p, s = run(sub("php-behavior-analyst", sess="s2", agent_id="a1"))
check("다른 세션에는 다시 주입", tokens_in(p) == {"CTX-T-ALPHA"},
      f"got={tokens_in(p)}", s)

try:
    st = json.load(open(os.path.join(STATE, "context-injected.json"),
                        encoding="utf-8"))
    row = (st.get("__counts") or {}).get("s1") or {}
    ok = row.get("matched", 0) > row.get("injected", 0)
except Exception as exc:
    ok, row = False, repr(exc)
check("억제량이 상태에 집계된다 (ctxstats 의 억제율)", ok, str(row))

# ---------------------------------------------------------------- 3. 로그
reset()
run(sub("php-behavior-analyst"))
rows = logs()
want = {"ts", "session_id", "agent_id", "agent_type", "trigger", "tool",
        "file", "bytes"}
ok = len(rows) == 1 and want <= set(rows[0]) and rows[0]["trigger"] == "agent" \
    and rows[0]["file"] == "alpha.md" and rows[0]["bytes"] > 0
check("주입 로그가 JSONL 로 남는다", ok, str(rows[:1]))

reset()
run(pre("Read", {"file_path": SRC}))
rows = logs()
check("경로 트리거의 trigger 값이 path", bool(rows) and rows[0]["trigger"] == "path",
      str(rows[:1]))

# ------------------------------------------------------- 4. 설정 없음 / 깨진 파일
reset()
NOCFG = os.path.join(BASE, "nocfg")
shutil.copytree(PROJ, NOCFG, dirs_exist_ok=True)
os.remove(os.path.join(NOCFG, ".claude", "config", "workspace.json"))
p, s = run(pre("Read", {"file_path": SRC}), project=NOCFG)
ok = tokens_in(p) == set() and p.returncode == 0 and "workspace.json" in p.stderr
check("설정 없으면 경로 트리거만 꺼지고 이유를 말한다", ok,
      f"rc={p.returncode} err={p.stderr[:100]!r}", s)

p, s = run(sub("php-behavior-analyst"), project=NOCFG)
check("설정 없어도 에이전트 트리거는 동작", tokens_in(p) == {"CTX-T-ALPHA"},
      f"got={tokens_in(p)} err={p.stderr[:100]!r}", s)

p2, _ = run(pre("Read", {"file_path": SRC}, sess="s9"), project=NOCFG)
p3, _ = run(pre("Read", {"file_path": SRC}, sess="s9"), project=NOCFG)
check("설정 경고는 세션당 한 번", "workspace.json" in p2.stderr
      and "workspace.json" not in p3.stderr,
      f"2nd err={p3.stderr[:80]!r}")

BROKEN = os.path.join(CTX, "zbroken.md")
open(BROKEN, "w", encoding="utf-8").write("name: nope\ninject: {}\n")
reset()
p, s = run(sub("php-behavior-analyst"))
ok = p.returncode == 0 and tokens_in(p) == {"CTX-T-ALPHA"} and "zbroken" in p.stderr
check("깨진 컨텍스트 파일: 나머지는 살고 이유만 말한다", ok,
      f"rc={p.returncode} got={tokens_in(p)} err={p.stderr[:100]!r}", s)

c = subprocess.run([sys.executable, HOOK, "--check"], capture_output=True,
                   text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": PROJ})
check("--check 는 프론트매터 오류에 exit 2", c.returncode == 2,
      f"rc={c.returncode} {c.stdout[:120]}")
os.remove(BROKEN)

# ---------------------------------------------------------------- 5. 안전성
reset()
p, s = run({"hook_event_name": "PreToolUse", "tool_name": "Read",
            "tool_input": "문자열이 들어온 경우"})
check("도구 입력이 dict 가 아니어도 exit 0", p.returncode == 0,
      f"rc={p.returncode}", s)

t0 = time.time()
raw = subprocess.run([sys.executable, HOOK], input="쓰레기 입력",
                     capture_output=True, text=True,
                     env={**os.environ, "CLAUDE_PROJECT_DIR": PROJ})
check("JSON 이 아닌 입력에도 exit 0", raw.returncode == 0,
      f"rc={raw.returncode}", time.time() - t0)

reset()
# 이 케이스는 **바닥을 함께 잰다.** 주장은 "이 훅이 자기 일에 45ms 를 넘게 쓰지 않는다"이고,
# 파이썬 인터프리터가 뜨는 시간은 훅의 일이 아니므로 **빼고 잰다.** 예전에는 기동 시간을
# 포함한 전체를 60ms 로 단정했는데, `selftest.py` 가 케이스 모듈 여섯을 겹쳐 돌리는 동안
# 그것이 간헐적으로 67ms 를 찍으며 빨간불이 됐다 — 훅은 그대로인데 부하가 달랐을 뿐이다.
#
# **간헐적으로 깨지는 검사는 없는 검사보다 나쁘다.** 실패를 무시하도록 가르치기 때문이고,
# 그러면 진짜 회귀가 왔을 때도 같은 빨간불로 도착한다. 임계값을 올려서 조용하게 만드는
# 것(측정을 약화시키는 쪽)이 아니라, **재는 대상을 훅 자신의 몫으로 좁혔다.**
#
# 부하가 너무 커서 바닥조차 흔들리면 답할 수 없다고 말하고 건너뛴다. 세 번 중 최소값으로
# 재는 것은 두 쪽 다 같다.
def _best(argv, payload=None):
    out = []
    for _ in range(3):
        t0 = time.time()
        subprocess.run(argv, input=payload, capture_output=True, text=True,
                       env={**os.environ, "CLAUDE_PROJECT_DIR": PROJ})
        out.append(time.time() - t0)
    return min(out)


floor = _best([sys.executable, "-c", "pass"])
best = _best([sys.executable, HOOK], json.dumps(sub("php-behavior-analyst")))
own = best - floor
if floor >= 0.05:
    skip("훅 자기 몫이 45ms 안이다",
         f"빈 인터프리터 기동만 {floor*1000:.0f}ms 다 — 이 부하에서는 바닥을 빼도 "
         f"남는 값을 믿을 수 없다 (전체 {best*1000:.0f}ms)")
else:
    check("훅 자기 몫이 45ms 안이다 (기동 바닥을 뺀 값 · 3회 중 최소)",
          own < 0.045,
          f"자기 몫 {own*1000:.0f}ms = 전체 {best*1000:.0f}ms − 바닥 {floor*1000:.0f}ms",
          best)

reset()
t0 = time.time()
off = subprocess.run([sys.executable, HOOK], input=json.dumps(
    sub("php-behavior-analyst")), capture_output=True, text=True,
    env={**os.environ, "CLAUDE_PROJECT_DIR": PROJ, "CONTEXT_INJECT_OFF": "1"})
ok = (off.returncode == 0 and tokens_in(off) == set()
      and "CONTEXT_INJECT_OFF" in off.stderr and not logs())
check("CONTEXT_INJECT_OFF: 주입 안 하고 그렇다고 말한다 (A/B 의 B)", ok,
      f"rc={off.returncode} err={off.stderr[:80]!r}", time.time() - t0)

# ---------------------------------------------------------------- 6. 출력 형식
reset()
p, s = run(sub("php-behavior-analyst"))
try:
    d = json.loads(p.stdout)
    ok = d["hookSpecificOutput"]["hookEventName"] == "SubagentStart" \
        and "CTX-T-ALPHA" in d["hookSpecificOutput"]["additionalContext"]
except Exception as exc:
    ok = False
    d = repr(exc)
check("SubagentStart json 형식이 유효하다", ok, str(d)[:120], s)

STDOUT_HOOK = os.path.join(BASE, "hook_stdout.py")
src = open(HOOK, encoding="utf-8").read()
open(STDOUT_HOOK, "w", encoding="utf-8").write(
    src.replace('SUBAGENT_OUTPUT = "json"', 'SUBAGENT_OUTPUT = "stdout"'))
reset()
p, s = run(sub("php-behavior-analyst"), hook=STDOUT_HOOK)
ok = p.stdout.lstrip().startswith("#") and "CTX-T-ALPHA" in p.stdout
check("SubagentStart stdout 형식도 구현돼 있다", ok, p.stdout[:80], s)

TASK_HOOK = os.path.join(BASE, "hook_task.py")
open(TASK_HOOK, "w", encoding="utf-8").write(
    src.replace("TASK_FALLBACK = False", "TASK_FALLBACK = True"))
reset()
p, s = run(pre("Task", {"subagent_type": "php-behavior-analyst",
                        "prompt": "원래 프롬프트", "description": "x"}),
           hook=TASK_HOOK)
try:
    d = json.loads(p.stdout)
    upd = d["hookSpecificOutput"]["updatedInput"]
    ok = (upd["prompt"].startswith("원래 프롬프트")
          and "CTX-T-ALPHA" in upd["prompt"]
          and upd["description"] == "x"
          and upd["subagent_type"] == "php-behavior-analyst")
except Exception as exc:
    ok, upd = False, repr(exc)
check("Task 폴백은 입력을 통째로 돌려준다", ok, str(upd)[:120], s)

reset()
p, s = run(pre("Task", {"subagent_type": "php-behavior-analyst",
                        "prompt": "원래 프롬프트"}))
check("폴백이 꺼져 있으면 Task 에 아무것도 안 한다", p.stdout.strip() == "",
      p.stdout[:80], s)

# ------------------------------------------------------- 7. 진짜 컨텍스트 파일
real = subprocess.run([sys.executable, HOOK, "--check"], capture_output=True,
                      text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": PROJECT})
check("실제 .claude/context/ 가 --check 를 통과한다", real.returncode == 0,
      real.stdout[-300:] + real.stderr[-200:])

realdir = os.path.join(PROJECT, ".claude", "context")
files = sorted(f for f in os.listdir(realdir) if f.endswith(".md"))
check("컨텍스트 파일이 5개 이상 (Day2 필수 1)", len(files) >= 5, str(len(files)))

long = []
for f in files:
    n = len(open(os.path.join(realdir, f), encoding="utf-8").read().splitlines())
    if n > 60:
        long.append(f"{f}:{n}")
check("각 파일 60줄 이내", not long, " ".join(long))

hard = []
for f in files:
    text = open(os.path.join(realdir, f), encoding="utf-8").read()
    for line in text.splitlines():
        s2 = line.strip()
        if s2.startswith("paths:") and "${" not in s2 and s2 != "paths: []":
            hard.append(f"{f}: {s2[:40]}")
check("경로 글롭은 전부 ${키} 참조 (회사 정보 없음)", not hard, " ".join(hard))

# ------------------------------------------------- 8. 이름 정합 (경고 or 실패)
agents_dir = os.path.join(PROJECT, ".claude", "agents")
skills_dir = os.path.join(PROJECT, ".claude", "skills")
have_agents = {os.path.splitext(f)[0] for f in os.listdir(agents_dir)
               if f.endswith(".md")} if os.path.isdir(agents_dir) else set()
have_skills = {n for n in (os.listdir(skills_dir) if os.path.isdir(skills_dir)
                           else [])
               if os.path.isfile(os.path.join(skills_dir, n, "SKILL.md"))}
missing = []
for f in files:
    text = open(os.path.join(realdir, f), encoding="utf-8").read()
    for key, have in (("agents", have_agents), ("skills", have_skills)):
        for line in text.splitlines():
            s2 = line.strip()
            if s2.startswith(key + ":") and "[" in s2:
                for n in s2.split("[", 1)[1].rstrip("]").split(","):
                    n = n.strip().strip("'\"")
                    if n and n.split(":")[-1] not in have:
                        missing.append(f"{f}→{key}:{n}")
if STRICT:
    check("inject 대상 이름이 전부 실재한다 (--strict)", not missing,
          " ".join(missing))
else:
    print(f"{'':2} {'inject 대상 이름 대조':<44} "
          + ("모두 실재" if not missing
             else f"경고 {len(missing)}건: {' '.join(missing)}"))
    print("   (없는 이름은 --strict 일 때만 실패로 친다 — 아직 안 만들어졌을 수 있다)")

# ---------------------------------------------------------------- 9. ctxstats
CTXSTATS = os.path.join(HERE, "ctxstats")
if os.path.isfile(CTXSTATS):
    reset()
    run(sub("php-behavior-analyst"))
    run(pre("Read", {"file_path": SRC}))
    r = subprocess.run([sys.executable, CTXSTATS, "--config", CONFIG, "--all"],
                       capture_output=True, text=True)
    ok = r.returncode == 0 and "alpha.md" in r.stdout and "agent" in r.stdout
    check("ctxstats --config 로 가짜 프로젝트를 읽는다", ok,
          r.stdout[-200:] + r.stderr[-120:])
    r = subprocess.run([sys.executable, CTXSTATS, "--config", CONFIG, "--all",
                        "--probe"], capture_output=True, text=True)
    ok = r.returncode == 0 and "CTX-T-ALPHA" in r.stdout
    check("ctxstats --probe 가 물어야 할 토큰을 찍는다", ok,
          r.stdout[-200:] + r.stderr[-120:])

    # 프로브 대조는 "주입된 것 전부"를 기대값으로 삼는다. 그래서 이 두 케이스는
    # 에이전트 트리거 하나만 남기고 잰다 — 남은 경로 주입이 미확인으로 잡히는 것은
    # 버그가 아니라 이 도구가 하는 일이다.
    reset()
    run(sub("php-behavior-analyst"))
    probe = os.path.join(STATE, "context-probe.jsonl")
    sid = [x["session_id"] for x in logs() if x.get("trigger") == "agent"][0]
    open(probe, "w", encoding="utf-8").write(json.dumps(
        {"session": sid, "agent_type": "php-behavior-analyst",
         "reported": ["CTX-T-ALPHA"]}, ensure_ascii=False) + "\n")
    r = subprocess.run([sys.executable, CTXSTATS, "--config", CONFIG, "--all",
                        "--probe"], capture_output=True, text=True)
    check("보고된 토큰이 기대와 맞으면 확인 · exit 0",
          r.returncode == 0 and "확인" in r.stdout and "미확인" not in r.stdout,
          f"rc={r.returncode} {r.stdout[-200:]}")

    open(probe, "w", encoding="utf-8").write(json.dumps(
        {"session": sid, "agent_type": "php-behavior-analyst",
         "reported": ["CTX-없는토큰"]}, ensure_ascii=False) + "\n")
    r = subprocess.run([sys.executable, CTXSTATS, "--config", CONFIG, "--all",
                        "--probe"], capture_output=True, text=True)
    check("보고가 어긋나면 미확인·불일치로 exit 1",
          r.returncode == 1 and "미확인" in r.stdout and "불일치" in r.stdout,
          f"rc={r.returncode} {r.stdout[-200:]}")
    os.remove(probe)
else:
    check("ctxstats 가 있다", False, CTXSTATS)

# ------------------------------------------------- 10. 예산과 우선순위
# 예산을 넘길 때 **무엇이 남는가**. 담는 순서를 파일 이름에 맡기면 알파벳이 정책이
# 되고, 그 순서의 마지막은 하필 공개 저장소 경계 파일이었다. 그래서 여기서는 예산을
# 실제로 넘겨 본다 — 해피 패스는 이 결함을 한 번도 밟지 않는다.
def injected_text(proc):
    out = proc.stdout or ""
    try:
        return (json.loads(out).get("hookSpecificOutput")
                or {}).get("additionalContext", "")
    except ValueError:
        return out


BIG = ("예산을 채우기 위한 본문. " * 40 + "\n") * 10     # 약 14KB
# 하나는 예산 안에 들어가고 둘은 못 들어간다 — 실제 모양(작은 파일 여섯의 합)과
# 같은 조건이다. 한 파일만으로 예산을 넘기면 "첫 항목은 무조건 담는다" 쪽만
# 밟고 우선순위 비교는 밟지 않는다.
ctxfile("ya-big", "전문성", ["budget-probe"], [], [], "CTX-T-BIG", body=BIG)
ctxfile("zz-keep", "팀", ["budget-probe"], [], [], "CTX-T-KEEP", body=BIG,
        priority=0)
reset()
p, s = run(sub("budget-probe", agent_id="b1"))
text = injected_text(p)
check("예산 초과: 우선순위 높은 쪽이 살아남는다",
      "CTX-T-KEEP" in text and "CTX-T-BIG" not in text,
      f"len={len(text)} err={p.stderr[:100]!r}", s)
check("잘린 파일 이름이 주입 블록 안에 남는다",
      "ya-big.md" in text and "예산" in text, text[:200])
check("주입 로그에는 담은 파일만 남는다",
      [r["file"] for r in logs()] == ["zz-keep.md"], str([r["file"] for r in logs()]))

# 프론트매터를 읽지 못한 파일도 받는 쪽에서는 "안 오는 파일"과 구별되지 않는다.
ctxfile("zprio", "전문성", ["budget-probe"], [], [], "CTX-T-PRIO",
        priority="높음")
reset()
p, s = run(sub("budget-probe", agent_id="b2"))
text = injected_text(p)
check("priority 가 정수가 아니면 그 사실을 블록에도 적는다",
      "zprio" in text and "CTX-T-KEEP" in text,
      f"err={p.stderr[:120]!r} text={text[:120]!r}", s)
c = subprocess.run([sys.executable, HOOK, "--check"], capture_output=True,
                   text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": PROJ})
check("priority 가 정수가 아니면 --check 가 exit 2",
      c.returncode == 2 and "priority" in c.stdout, f"rc={c.returncode} {c.stdout[:160]}")
for n in ("ya-big", "zz-keep", "zprio"):
    os.remove(os.path.join(CTX, n + ".md"))

# 훅만 고치고 실제 파일에 우선순위를 주지 않으면 아무것도 달라지지 않는다.
prios = {}
for f in files:
    prios[f] = 50
    for line in open(os.path.join(realdir, f), encoding="utf-8").read().splitlines():
        s2 = line.strip()
        if s2.startswith("priority:"):
            prios[f] = int(s2.split(":", 1)[1].split("#")[0].strip())
lowest = min(prios.values())
check("실제 경계 파일이 유일하게 가장 높은 우선순위를 갖는다",
      prios.get("team-boundary.md") == lowest
      and sum(1 for v in prios.values() if v == lowest) == 1, str(prios))

shutil.rmtree(BASE, ignore_errors=True)
print("-" * 84)
passed = sum(results)
if skipped:
    print(f"건너뜀 {len(skipped)}개 — " + ", ".join(skipped))
print(f"{passed}/{len(results)} 통과")
sys.exit(0 if passed == len(results) else 1)
