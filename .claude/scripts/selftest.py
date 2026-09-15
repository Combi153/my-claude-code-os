#!/usr/bin/env python3
"""도구와 훅이 실제로 동작하는지 검사한다. 프로젝트 루트에서, 환경변수 없이.

    python3 .claude/scripts/selftest.py           전부
    python3 .claude/scripts/selftest.py --quick    트리를 훑는 검사는 건너뛴다

**이 파일에는 환경 상수가 없다.** 대상 경로와 서비스 이름은 도구와 같은 자리인
`.claude/config/workspace.json` 에서 읽는다. 그래야 이 파일이 추적될 수 있고, 검사가
설정과 어긋나는 일도 생기지 않는다. 계측 훅 검사는 가짜 트리를 만들어 그쪽을 향하게
하므로 실제 로그와 상태 파일을 건드리지 않는다.

**각 검사의 소요 시간을 찍는다.** 도구가 정확해도 한 번에 1분이 걸리면 호출자는
우회하고, 그 우회는 로그에 "도구를 안 썼다"로 남는다. 그러면 원인이 설계에 있는 것처럼
읽힌다. 시간이 보이면 그 오독을 막을 수 있다. `--quick` 은 트리 전체를 훑는 검사를
빼는 것이고, 그 경우 무엇을 빼먹었는지 마지막에 말한다.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

QUICK = "--quick" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SCRATCH = tempfile.mkdtemp(prefix="phpselftest-")
ENV = {k: v for k, v in os.environ.items() if k != "PHP_LEGACY_ROOT"}

results = []
skipped = []


def check(name, ok, detail="", secs=None):
    results.append((name, ok, detail))
    t = f"  {secs:5.1f}s" if secs is not None else "        "
    print(f"  {'통과' if ok else 'FAIL'}{t}  {name}"
          + (f"   {detail}" if detail else ""))


def skip(name, why):
    skipped.append((name, why))
    print(f"  건너뜀       {name}   ({why})")


def run(cmd, timeout=180, env=None, **kw):
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT,
                       env=env or ENV, timeout=timeout, **kw)
    return p, time.time() - t0


def load_config():
    p = os.path.join(PROJECT, ".claude", "config", "workspace.json")
    with open(p, encoding="utf-8") as fh:
        return json.load(fh).get("legacy") or {}


LG = load_config()
if not LG.get("root"):
    sys.exit("selftest: workspace.json 의 legacy 절이 비어 있다. "
             "workspace.example.json 을 보고 채워라.")

TREE = LG.get("treeRoot") or os.path.join(LG["root"], LG["treeMarker"])
PRIMARY = LG["primaryService"]
SHARED = LG.get("sharedLibrary") or PRIMARY


def sample(prefix, want_encoding=None, limit=400):
    """트리에서 검사에 쓸 .php 파일 하나. 심볼명을 이 파일에 적지 않기 위한 것이다."""
    sys.path.insert(0, HERE)
    from _phpenc import detect
    base = os.path.join(TREE, prefix)
    seen = 0
    # 벤더 번들을 뽑으면 안 된다. `phplint` 가 그것을 검사 대상에서 빼므로,
    # 벤더 파일로 문법 검사를 확인하면 "건너뜀"을 "통과"로 읽는다. 검사가 실제
    # 동작을 재려면 대상이 우리 코드여야 한다.
    SKIP = ("vendor", "node_modules", "bower_components", "external", "test",
            "tests", "old", "backup")
    for root, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs
                   if d != ".git" and d.lower() not in SKIP
                   and "excel" not in d.lower() and "editor" not in d.lower()]
        for n in names:
            if not n.endswith(".php"):
                continue
            p = os.path.join(root, n)
            seen += 1
            if seen > limit:
                return None
            try:
                with open(p, "rb") as fh:
                    enc = detect(fh.read(200000))
            except OSError:
                continue
            if want_encoding is None or enc == want_encoding:
                return p
    return None


print(f"# 대상 트리 확인: {os.path.isdir(TREE)}"
      f" · 서비스 {len(LG.get('services') or {})}개"
      f" · 런타임 {len(LG.get('runtimes') or {})}개"
      + ("  [--quick]" if QUICK else ""))

# ---------------------------------------------------------------- 1. 도구
print("\n### 1. 도구 여덟 개 — 환경변수 없이, 프로젝트 루트에서")

cp949 = sample(SHARED, "cp949") or sample(PRIMARY, "cp949")
utf8 = sample(PRIMARY, "utf-8") or sample(PRIMARY)

if cp949:
    p, s = run([sys.executable, HERE + "/phpv", cp949, "1:3"])
    check("phpv 가 CP949 를 디코드", p.returncode == 0 and "cp949" in p.stdout,
          secs=s)
else:
    skip("phpv CP949 디코드", "CP949 파일을 찾지 못함")

p, s = run([sys.executable, HERE + "/phpv"])
check("phpv 인자 없이 → 도움말, exit 2", p.returncode == 2, secs=s)

if QUICK:
    skip("phpgrep 정상 검색", "트리 전체를 훑는다")
else:
    p, s = run([sys.executable, HERE + "/phpgrep", "-l", "__nosuchsymbol__"])
    check("phpgrep 이 범위를 찍고 0건을 0건으로 답함",
          p.returncode == 1 and "범위" in p.stderr and "없음" in p.stderr, secs=s)

p, s = run([sys.executable, HERE + "/phpgrep", "-F", "x"])
check("phpgrep 이 모르는 옵션을 거부 (검색어로 삼지 않음)",
      p.returncode == 2 and "모르는 옵션" in p.stderr, secs=s)

p, s = run([sys.executable, HERE + "/phpgrep", "a", "b"])
check("phpgrep 이 검색어 두 개를 거부", p.returncode == 2 and "하나여야" in p.stderr,
      secs=s)

p, s = run([sys.executable, HERE + "/phpindex", "--list"])
check("phpindex --list 가 인덱스를 찾음",
      p.returncode == 0 and ".json" in p.stdout, secs=s)

p, s = run([sys.executable, HERE + "/phpindex", "--nosuchopt"])
check("phpindex 가 모르는 옵션에 재생성하지 않음", p.returncode != 0, secs=s)

p, s = run([sys.executable, HERE + "/phpwhere", "--conflicts"])
check("phpwhere 가 인덱스를 읽음", p.returncode == 0 and "범위" in p.stdout, secs=s)

p, s = run([sys.executable, HERE + "/phpstats", "--days", "1"])
check("phpstats", p.returncode == 0 and "최근 1일" in p.stdout, secs=s)

p, s = run([sys.executable, HERE + "/phped", "status"])
check("phped status", p.returncode == 0, secs=s)

if utf8:
    t0 = time.time()
    p = subprocess.run([sys.executable, HERE + "/phplint", "--as", utf8, "-"],
                       input="<?php function f() { return 1; }", text=True,
                       capture_output=True, cwd=PROJECT, env=ENV, timeout=180)
    check("phplint 정상 소스 → 0, 그리고 맞는 런타임을 골랐다",
          p.returncode == 0 and "OK on PHP" in p.stderr,
          p.stderr.strip()[:70] if p.returncode else "", secs=time.time() - t0)
    t0 = time.time()
    p = subprocess.run([sys.executable, HERE + "/phplint", "--as", utf8, "-"],
                       input="<?php function f( { return 1; }", text=True,
                       capture_output=True, cwd=PROJECT, env=ENV, timeout=180)
    check("phplint 깨진 소스 → 1", p.returncode == 1 and "FAILS" in p.stderr,
          secs=time.time() - t0)
else:
    skip("phplint 정상·실패", "대상 파일을 찾지 못함")

outside = os.path.join(SCRATCH, "outside.php")
open(outside, "w").write("<?php echo 1;")
p, s = run([sys.executable, HERE + "/phplint", outside])
check("phplint 검사 못 함 → 3 (통과 아님)", p.returncode == 3, secs=s)

p, s = run([sys.executable, "-c",
            f"import sys; sys.path.insert(0, {HERE!r});\n"
            "from _phpenc import checkout_root, config_problem;\n"
            "print(config_problem() or checkout_root())"])
check("설정 판정이 체크아웃을 가리킴",
      p.stdout.strip() == os.path.abspath(os.path.expanduser(LG["root"])),
      "" if p.stdout.strip() == os.path.abspath(os.path.expanduser(LG["root"]))
      else p.stdout.strip()[:60], secs=s)

# 설정이 없으면 좁은 답을 내지 않고 멈추는가
empty = os.path.join(SCRATCH, "emptyproj")
os.makedirs(empty + "/.claude/config", exist_ok=True)
with open(empty + "/.claude/config/workspace.json", "w") as fh:
    json.dump({}, fh)
p, s = run([sys.executable, HERE + "/phpwhere", "x"],
           env={**ENV, "CLAUDE_PROJECT_DIR": empty})
check("설정이 비면 멈추고 이유를 말함",
      p.returncode != 0 and ("legacy" in p.stderr or "workspace" in p.stderr),
      secs=s)

# ------------------------------------------------------- 2. 인코딩 가드
print("\n### 2. 인코딩 가드 — 격리된 상태 파일로")
GPROJ = os.path.join(SCRATCH, "guardproj")
os.makedirs(GPROJ + "/.claude/config", exist_ok=True)
# **설정을 통째로 넘긴다.** 전에는 세 키만 복사했고, 그러면 `phplint` 가 런타임을
# 고를 수 없어 "검사하지 못함"으로 끝난다. 검사 항목이 "경고가 없는가"였으므로
# 그 상태가 통과로 읽혔다. 격리는 상태 파일에만 필요하고, 설정을 줄이는 것은
# 격리가 아니라 검사 대상을 바꾸는 것이다.
with open(GPROJ + "/.claude/config/workspace.json", "w") as fh:
    json.dump({"legacy": LG}, fh)
# 가드는 도구를 `CLAUDE_PROJECT_DIR/.claude/scripts` 에서 찾는다. 격리
# 프로젝트에도 그 자리를 만들어 준다.
os.symlink(HERE, os.path.join(GPROJ, ".claude", "scripts"))
GUARD = PROJECT + "/.claude/hooks/php-encoding-guard.py"


def hook_text(p):
    """훅이 사람에게 보이려는 문장. stdout 의 JSON 을 풀고 stderr 를 붙인다.

    훅은 `json.dump` 로 내보내므로 한글이 `\\uXXXX` 로 이스케이프되어 있다.
    그것을 풀지 않고 원문 문구를 찾으면 **긍정 조건은 항상 실패하고 부정 조건은
    항상 통과한다.** 후자가 더 나쁘다 — 검사가 통과하면서 아무것도 확인하지
    않는다. 이 스위트에도 그런 검사가 둘 있었다.
    """
    out = ""
    try:
        out += json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
    except Exception:
        out += p.stdout or ""
    return out + (p.stderr or "")


def guard(path, event="PreToolUse", project=None):
    body = {"tool_name": "Edit", "tool_input": {"file_path": path},
            "hook_event_name": event}
    t0 = time.time()
    p = subprocess.run([sys.executable, GUARD], input=json.dumps(body),
                       text=True, capture_output=True,
                       env={**ENV, "CLAUDE_PROJECT_DIR": project or GPROJ},
                       timeout=180)
    return p, time.time() - t0


if cp949:
    p, s = guard(cp949)
    check("CP949 파일 편집 전에 경고", p.returncode == 0 and "CP949" in hook_text(p),
          "" if "CP949" in hook_text(p) else hook_text(p)[:80], secs=s)
else:
    skip("CP949 편집 전 경고", "CP949 파일을 찾지 못함")

p, s = guard(os.path.join(SCRATCH, "outside.php"))
check("트리 밖 파일은 조용히 통과",
      p.returncode == 0 and not hook_text(p).strip(), secs=s)

if utf8:
    guard(utf8, "PreToolUse")          # 편집 전 기록이 있어야 편집 후 검사가 돈다
    p, s = guard(utf8, "PostToolUse")
    out = hook_text(p)
    check("정상 PHP 편집 후 문법 실패 경고 없음", "돌지 않습니다" not in out, secs=s)
    # **이 줄이 핵심이다.** "검사되지 않았습니다"가 없다는 것은 검사가 돌아서
    # 통과했다는 뜻이고, 도구를 못 찾아 조용히 넘어간 상태와 다르다. 도구 경로가
    # 옛 위치를 가리키던 동안 이 구분이 없어서 결함이 통과했다.
    check("문법 검사가 실제로 돌았다 (미검사 상태가 아니다)",
          "검사되지 않았습니다" not in out,
          "" if "검사되지 않았습니다" not in out else out.strip()[-90:])
    # 도구를 못 찾는 상황을 일부러 만들어, 그때 조용히 넘어가지 않는지 본다.
    BARE = os.path.join(SCRATCH, "bareproj")
    os.makedirs(BARE + "/.claude/config", exist_ok=True)
    with open(BARE + "/.claude/config/workspace.json", "w") as fh:
        json.dump({"legacy": LG}, fh)
    # 편집 전 단계를 먼저 돌린다. PostToolUse 는 그때 기록된 인코딩과 대조하는
    # 것부터 시작하므로, 기록이 없으면 문법 검사까지 가지 않고 조용히 끝난다.
    t0 = time.time()
    for ev in ("PreToolUse", "PostToolUse"):
        p, _ = guard(utf8, ev, project=BARE)
    _o = hook_text(p).strip()
    check("문법 검사 도구가 없으면 그 사실을 말한다 (조용히 통과하지 않는다)",
          "찾지 못했습니다" in _o,
          "" if "찾지 못했습니다" in _o else f"exit={p.returncode} 출력={_o[:120]!r}",
          secs=time.time() - t0)

# --------------------------------------------------------- 3. 계측 훅
print("\n### 3. 계측 훅 — 가짜 트리로")
cases = os.path.join(HERE, "selftest_hook.py")
if os.path.isfile(cases):
    p, s = run([sys.executable, cases,
                PROJECT + "/.claude/hooks/php-tooling-hook.py"], timeout=300)
    tail = [l for l in p.stdout.strip().splitlines() if "통과" in l]
    last = tail[-1] if tail else p.stdout.strip()[-120:]
    n = last.split("/")[0].strip() if "/" in last else "?"
    total = last.split("/")[1].split()[0] if "/" in last else "?"
    check(f"계측 케이스 {total} 개", n == total, last.strip(), secs=s)
    if n != total:
        print(p.stdout)
else:
    skip("계측 훅 케이스", "selftest_hook.py 가 없다")

# --------------------------------------------------- 4~7. 도구별 케이스 모듈
# 각 모듈은 스스로 합성 픽스처를 만들고 마지막 줄에 `N/M 통과` 를 찍는다. 여기서는
# 그 숫자만 읽는다. 모듈을 통째로 이 파일에 옮기지 않는 이유는 하나다 — 이 파일이
# 커지면 아무도 끝까지 돌리지 않고, 돌지 않는 검사는 없는 검사다.
def cases_module(no, title, filename, args=(), timeout=300):
    print(f"\n### {no}. {title}")
    mod = os.path.join(HERE, filename)
    if not os.path.isfile(mod):
        skip(title, f"{filename} 이 없다")
        return
    p, s = run([sys.executable, mod, *args], timeout=timeout)
    tail = [l for l in p.stdout.strip().splitlines() if "통과" in l]
    last = tail[-1] if tail else p.stdout.strip()[-120:]
    n = last.split("/")[0].strip() if "/" in last else "?"
    total = last.split("/")[1].split()[0] if "/" in last else "?"
    check(f"{title} 케이스 {total} 개", n == total, last.strip(), secs=s)
    if n != total:
        print(p.stdout)
        print(p.stderr[-1500:], file=sys.stderr)


cases_module(4, "phpseam — 페이지 모양·본문 해시·호출자",
             "selftest_phpseam.py", [os.path.join(HERE, "phpseam")])
cases_module(5, "htmlsnap — 캡처와 비교", "selftest_htmlsnap.py")
cases_module(6, "dualrun-report — 이중 실행 로그", "selftest_dualrun.py")
cases_module(7, "컨텍스트 주입 — 가짜 프로젝트로", "selftest_context.py",
             [PROJECT + "/.claude/hooks/context-inject.py"])

# ------------------------------------------------------- 8. 교차 검사
# **한 사실이 두 파일에 적혀 있으면 언젠가 갈린다.** 갈라진 것을 사람이 알아채는
# 경로가 없으면 그 어긋남은 조용히 산다 — v1 에서 감사 어휘 하나가 라우팅표에
# 없어서, 그 판정이 돌아올 때마다 갈 곳 없이 사라졌다. 여기서는 정본을 정하고
# 사본을 대조한다. 실패는 "둘 중 하나가 틀렸다"가 아니라 "둘이 갈렸다"이다.
print("\n### 8. 교차 검사 — 같은 사실이 두 곳에 적힌 자리")

AGENTS = os.path.join(PROJECT, ".claude", "agents")
SKILLS = os.path.join(PROJECT, ".claude", "skills")
SLICE = os.path.join(SKILLS, "legacy-slice")
ROW = re.compile(r"^\| `?([^|`]+)`?\s*(?:\([^)]*\))?\s*\|")


def read(*parts):
    try:
        with open(os.path.join(*parts), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def table_first_col(text, header_needle):
    """머리글 줄을 지난 뒤의 표 **본문** 행에서 첫 열만 뽑는다.

    본문의 시작은 구분선(`|---|`)이다. 그것을 기준으로 삼지 않으면 표 머리글이
    첫 항목으로 딸려 들어오고, 그러면 두 파일이 같아도 다르다고 말한다 —
    어긋남을 못 보는 것보다 나쁘지는 않지만, 매번 틀리는 검사는 꺼진다.
    """
    out, seen, started = [], False, False
    for line in text.splitlines():
        if not seen:
            seen = header_needle in line
            continue
        if not line.startswith("|"):
            if started and out:
                break
            continue
        if set(line.replace("|", "").strip()) <= set("-: "):
            started = True
            continue
        if not started:
            continue
        m = ROW.match(line)
        if m:
            out.append(m.group(1).strip())
    return out


# (a) 감사 판정 어휘 — 정본은 감사자 파일 하나 -----------------------------
auditor = read(AGENTS, "domain-boundary-auditor.md")
skill = read(SLICE, "SKILL.md")
canon = table_first_col(auditor, "## 판정 어휘")
routed = table_first_col(skill, "| 감사 판정 |")
check("감사 판정 어휘가 라우팅표와 같다",
      bool(canon) and bool(routed) and canon == routed,
      f"감사자 {canon} vs 라우팅표 {routed}" if canon != routed
      else f"{len(canon)}개")

# (b) 산출물 — 정본은 artifacts.json --------------------------------------
try:
    with open(os.path.join(SLICE, "references", "artifacts.json"),
              encoding="utf-8") as fh:
        art = json.load(fh)
except (OSError, ValueError) as exc:
    art, art_err = {}, str(exc)
else:
    art_err = ""
tbl = dict()
for line in skill.splitlines():
    m = re.match(r"^\| `(\d\d-[\w.-]+)` \| (\d) \| `([\w-]+)` \|$", line.strip())
    if m:
        tbl[m.group(1)] = {"phase": int(m.group(2)), "writer": m.group(3)}
check("산출물 표가 artifacts.json 과 같다",
      bool(art) and tbl == art,
      art_err or (f"JSON {sorted(art)} vs SKILL.md {sorted(tbl)}"
                  if set(art) != set(tbl)
                  else "행 내용이 다르다: "
                       + str([k for k in art if art[k] != tbl.get(k)]))
      if tbl != art else f"{len(art)}개")

# (c) 실험 헬퍼 상수 ↔ 설정 키 ---------------------------------------------
tpl = read(PROJECT, ".claude", "templates", "MigrationExperiment.php")
consts = [c for c in ("VALUE_DUAL", "VALUE_MIGRATED", "LOG_ENV")
          if re.search(r"\bconst\s+" + c + r"\s*=", tpl)]
try:
    with open(os.path.join(PROJECT, ".claude", "config",
                           "workspace.example.json"), encoding="utf-8") as fh:
        ex = json.load(fh)
except (OSError, ValueError):
    ex = {}
exl = (ex.get("legacy") or {})
want_keys = [("legacy.switch.values.dual",
              "dual" in ((exl.get("switch") or {}).get("values") or {})),
             ("legacy.switch.values.migrated",
              "migrated" in ((exl.get("switch") or {}).get("values") or {})),
             ("legacy.dualRun.logEnvVar",
              "logEnvVar" in (exl.get("dualRun") or {}))]
missing = [k for k, ok in want_keys if not ok]
check("실험 헬퍼의 세 상수와 example 의 세 키가 둘 다 있다",
      len(consts) == 3 and not missing,
      f"상수 {consts} · 없는 키 {missing}"
      if len(consts) != 3 or missing else "")

# 실제 설정이 그 절을 채웠다면 값까지 대조한다. 안 채웠으면 건너뛴다 —
# 값이 없는 것은 어긋남이 아니라 아직 쓰지 않은 것이다.
real = {}
try:
    with open(os.path.join(PROJECT, ".claude", "config", "workspace.json"),
              encoding="utf-8") as fh:
        real = (json.load(fh).get("legacy") or {})
except (OSError, ValueError):
    pass
rv = (real.get("switch") or {}).get("values") or {}
rlog = (real.get("dualRun") or {}).get("logEnvVar")
if rv.get("dual") and rv.get("migrated") and rlog:
    lit = {c: (re.search(r"\bconst\s+" + c + r"\s*=\s*'([^']*)'", tpl)
               or [None, None])[1] for c in ("VALUE_DUAL", "VALUE_MIGRATED",
                                             "LOG_ENV")}
    same = (rv["dual"] == lit["VALUE_DUAL"]
            and rv["migrated"] == lit["VALUE_MIGRATED"]
            and rlog == lit["LOG_ENV"])
    check("실제 설정의 토글 값이 헬퍼 상수와 같다", same,
          "" if same else f"설정 {rv}/{rlog} vs 템플릿 {lit}")
else:
    skip("실제 설정의 토글 값 대조", "workspace.json 에 dualRun·dual 값이 아직 없다")

# (d) 컨텍스트 파일의 주입 대상이 실재하는가 ------------------------------
inject = os.path.join(PROJECT, ".claude", "hooks", "context-inject.py")
if os.path.isfile(inject):
    p, s = run([sys.executable, inject, "--check", "--strict"], timeout=60)
    check("컨텍스트 파일의 inject.agents·skills 가 실제 파일과 일치",
          p.returncode == 0,
          (p.stdout + p.stderr).strip()[-200:] if p.returncode else "", secs=s)
else:
    skip("컨텍스트 주입 대상 대조", "context-inject.py 가 없다")

# (e) 옛 이름이 추적 파일에 남아 있지 않은가 -------------------------------
# v1 의 이름이 하나라도 남으면 오케스트레이터가 없는 에이전트를 부르거나 없는
# 파일을 기다린다. 둘 다 실패가 아니라 정지로 나타난다.
# 이름을 조각으로 이어 붙인다. 이 파일도 추적되므로, 목록을 리터럴로 적으면
# **검사가 자기 자신을 잡는다** — 그러면 이 파일을 예외로 두게 되고, 예외가
# 생기는 순간 검사에 사각이 생긴다. `selftest_phpseam.py` 가 콘텐츠 가드에 대해
# 한 것과 같은 거래다.
OLD_NAMES = ["e2e-baseline" + "-author", "00-" + "ledger.md",
             "01-" + "design.md", "02-" + "swap.md",
             "03-" + "audit.md", "04-" + "domain-doc.md"]
# 당시 기록은 제외한다. 지난 일을 지금 이름으로 고쳐 적는 것은 기록이 아니다.
EXCLUDE_FILES = {"docs/first-run-retrospective.md"}
EXCLUDE_RANGES = {"docs/legacy-migration-os.md": [("## 9.", "## 10."),
                                                 ("## 변경 이력", None)]}
# `--others --exclude-standard` 를 붙인다. 아직 `git add` 되지 않은 새 파일도
# 곧 추적될 파일이고, 그 파일에 남은 옛 이름은 커밋 뒤에야 보이기 시작한다.
tracked = subprocess.run(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
    cwd=PROJECT, capture_output=True, text=True, timeout=60).stdout
hits = []
for rel in tracked.splitlines():
    if not rel or rel in EXCLUDE_FILES:
        continue
    if os.path.splitext(rel)[1] not in (".md", ".json", ".py", ".sh", ".php",
                                        ".ts", ".yml", ".yaml", ""):
        continue
    body = read(PROJECT, rel)
    if not body:
        continue
    skipping, ranges = False, EXCLUDE_RANGES.get(rel, [])
    for i, line in enumerate(body.splitlines(), 1):
        for start, end in ranges:
            if line.startswith(start):
                skipping = True
            elif end and skipping and line.startswith(end):
                skipping = False
        if skipping:
            continue
        for name in OLD_NAMES:
            if name in line:
                hits.append(f"{rel}:{i}: {name}")
check("v1 의 옛 이름이 추적 파일에 없다", not hits,
      "; ".join(hits[:4]) + (f" (외 {len(hits) - 4}건)" if len(hits) > 4 else ""))

# ------------------------------------------------------------------ 정리
shutil.rmtree(SCRATCH, ignore_errors=True)
print("\n" + "=" * 64)
bad = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(bad)}/{len(results)} 통과"
      + ("" if not bad else "   실패: " + ", ".join(bad)))
if skipped:
    print(f"건너뜀 {len(skipped)}개 — " + ", ".join(n for n, _ in skipped))
    print("  건너뛴 검사는 통과가 아니다. --quick 없이 한 번은 돌려야 한다.")
sys.exit(1 if bad else 0)
