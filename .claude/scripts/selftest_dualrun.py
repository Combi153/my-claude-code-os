#!/usr/bin/env python3
"""dualrun-report 케이스. 합성 JSONL 로, 그리고 있으면 진짜 PHP 헬퍼로.

    python3 selftest_dualrun.py [dualrun-report 경로] [MigrationExperiment.php 경로]

합성 로그만으로도 집계·종료 코드·ignore 매칭은 전부 검사된다. 그러나 합성 로그는
**우리가 스키마를 옳게 이해했다는 것만** 증명한다. 헬퍼가 실제로 그 스키마로 쓰는지는
헬퍼를 돌려야 알 수 있고, 그래서 로컬에 php 가 있으면 템플릿을 실제로 실행해 만든
로그도 같은 케이스에 넣는다. php 가 없으면 그 케이스는 '건너뜀'으로 명시한다 —
건너뛴 검사는 통과가 아니다.

이 파일은 실제 workspace.json 을 읽지 않는다. 합성 설정을 써서 `--config` 로 준다.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "dualrun-report")
TEMPLATE = (sys.argv[2] if len(sys.argv) > 2
            else os.path.join(os.path.dirname(HERE), "templates",
                              "MigrationExperiment.php"))
if not os.path.isfile(TOOL):
    sys.exit(f"사용법: selftest_dualrun.py [dualrun-report 경로]  (찾은 곳: {TOOL})")

BASE = tempfile.mkdtemp(prefix="dualrun-selftest-")
results, skipped = [], []


def check(name, ok, detail="", secs=None):
    results.append((name, ok, detail))
    t = f"  {secs:5.1f}s" if secs is not None else "        "
    print(f"  {'통과' if ok else 'FAIL'}{t}  {name}" + (f"   {detail}" if detail else ""))


def skip(name, why):
    skipped.append((name, why))
    print(f"  건너뜀       {name}   ({why})")


def run(args, timeout=60):
    t0 = time.time()
    p = subprocess.run([sys.executable, TOOL] + args, capture_output=True, text=True,
                       timeout=timeout, cwd=BASE)
    return p, time.time() - t0


def row(experiment="list-page", equal=True, diff=None, control=None, candidate=None,
        ts="2026-09-08T12:00:00+09:00", **extra):
    rec = {"ts": ts, "experiment": experiment, "mode": "dual",
           "input": {"page": 1}, "control_sha": "a" * 8, "candidate_sha": "b" * 8,
           "equal": equal, "diff_keys": diff or [], "ignored_keys": [],
           "truncated": False, "control_ms": 12, "candidate_ms": 40,
           "page": "/<page>.php", "caller": "<page>.php:42"}
    if not equal:
        rec["control"] = control if control is not None else {"total": 120}
        rec["candidate"] = candidate if candidate is not None else {"total": 7}
    rec.update(extra)
    return json.dumps(rec, ensure_ascii=False)


def log(name, lines):
    path = os.path.join(BASE, f"{name}.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(l + "\n" for l in lines))
    return path


def ignore_file(name, rules):
    path = os.path.join(BASE, f"ignore-{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"rules": rules}, fh, ensure_ascii=False)
    return path


CONFIG = os.path.join(BASE, "workspace.json")
DEFAULT_LOG = log("configured", [row(), row(equal=False, diff=["total"])])
with open(CONFIG, "w", encoding="utf-8") as fh:
    json.dump({"legacy": {"dualRun": {"logPath": DEFAULT_LOG,
                                      "logEnvVar": "MIGRATION_EXPERIMENT_LOG"}}}, fh)
EMPTY_CONFIG = os.path.join(BASE, "workspace-empty.json")
with open(EMPTY_CONFIG, "w", encoding="utf-8") as fh:
    json.dump({"legacy": {}}, fh)

print(f"# 도구 {TOOL}")
print("\n### 1. 집계와 종료 코드")

lg = log("equal", [row(), row(), row()])
p, secs = run(["--log", lg])
check("전부 equal 이면 exit 0 이고 '예상 밖 없음'이라고 말한다",
      p.returncode == 0 and "예상 밖 불일치 없음" in p.stdout,
      f"exit={p.returncode}", secs=secs)

lg = log("unexpected", [row(), row(equal=False, diff=["total"]),
                        row(equal=False, diff=["total"]),
                        row(equal=False, diff=["items[0].title", "total"])])
p, _ = run(["--log", lg])
check("예상 밖 불일치가 있으면 exit 1",
      p.returncode == 1, f"exit={p.returncode}")
check("diff_keys 서명으로 묶어 두 가지로 보고한다 (건수 4가 아니라 서명 2)",
      "서명 2가지" in p.stdout and "3건" not in p.stdout.split("서명 2가지")[0],
      [l for l in p.stdout.splitlines() if "서명" in l][:1])
check("서명별 건수를 센다 (같은 서명 2건)",
      "list-page  2건" in p.stdout,
      [l.strip() for l in p.stdout.splitlines() if "건 " in l or l.strip().endswith("건")][:2])

ig = ignore_file("total", [{"experiment": "list-page", "keys": ["total"],
                            "ledger": "R-17", "reason": "의도수정: 기본값 결함 교정"}])
p, _ = run(["--log", lg, "--ignore", ig])
check("ignore 가 덮는 불일치는 '예상'으로 빠지고, 나머지만 남는다",
      p.returncode == 1 and "서명 1가지" in p.stdout, f"exit={p.returncode}")
check("부분적으로만 덮인 불일치에는 원장 행 힌트가 붙는다",
      "R-17" in p.stdout, "" if "R-17" in p.stdout else "힌트가 없다")

ig2 = ignore_file("both", [{"experiment": "list-page",
                            "keys": ["total", "items[].title"], "ledger": "R-17",
                            "reason": "의도수정"}])
p, _ = run(["--log", lg, "--ignore", ig2])
check("배열 인덱스 와일드카드가 먹는다 (items[].title 이 items[0].title 을 덮는다)",
      p.returncode == 0 and "예상 밖 불일치 없음" in p.stdout, f"exit={p.returncode}")

lg_other = log("other", [row(experiment="detail-page", equal=False, diff=["body"]),
                         row(experiment="list-page", equal=False, diff=["total"])])
p, _ = run(["--log", lg_other, "--ignore", ig])
check("ignore 의 experiment 는 다른 실험까지 덮지 않는다",
      p.returncode == 1 and "detail-page" in p.stdout and "서명 1가지" in p.stdout,
      f"exit={p.returncode}")

print("\n### 2. 절단·예외·필터")

lg = log("trunc", [row(equal=False, diff=["items"], truncated=True,
                       control=None, candidate=None)])
p, _ = run(["--log", lg])
out_trunc = "\n".join(l for l in p.stdout.splitlines() if "truncated" in l)
check("truncated 행은 본문 없이 sha 만 보여주고, 절단 수를 센다",
      p.returncode == 1 and "truncated" in p.stdout and "aaaaaaaa"[:8] in p.stdout,
      out_trunc.strip()[:70])

lg = log("boom", [json.dumps({"ts": "2026-09-08T12:00:00+09:00",
                              "experiment": "detail-page", "mode": "dual",
                              "input": {"seq": 9}, "equal": False, "diff_keys": [],
                              "candidate_error": {"class": "RuntimeException",
                                                  "message": "backend said no"}},
                             ensure_ascii=False)])
p, _ = run(["--log", lg])
check("candidate 예외는 예상 밖으로 남는다 (diff_keys 가 비었다고 조용히 통과시키지 않는다)",
      p.returncode == 1 and "RuntimeException" in p.stdout, f"exit={p.returncode}")

lg = log("filter", [row(ts="2026-09-01T00:00:00+09:00", equal=False, diff=["old"]),
                    row(ts="2026-09-08T12:00:00+09:00", equal=False, diff=["new"])])
p, _ = run(["--log", lg, "--since", "2026-09-05T00:00:00+09:00"])
# 서명 줄로 본다. 임시 디렉터리 경로가 보고에 찍히고 그 경로에 'old' 가 들어 있을 수 있다.
check("--since 가 그 이전 줄을 걸러낸다",
      p.returncode == 1 and "서명: new" in p.stdout and "서명: old" not in p.stdout,
      f"exit={p.returncode} 걸러냄 " + ("1" if "걸러냄 1" in p.stdout else "?"))
p, _ = run(["--log", lg, "--since", "어제"])
check("읽을 수 없는 --since 는 exit 2",
      p.returncode == 2 and "ISO" in p.stderr, f"exit={p.returncode}")
p, _ = run(["--log", lg, "--since", "2030-01-01T00:00:00+09:00"])
check("전부 걸러져 남은 줄이 없으면 exit 2 — 0건과 '못 읽었다'는 다르다",
      p.returncode == 2 and "하나도 없다" in p.stderr, f"exit={p.returncode}")

p, _ = run(["--log", lg_other, "--experiment", "detail-page"])
check("--experiment 가 실험 하나만 남긴다",
      p.returncode == 1 and "list-page" not in p.stdout, f"exit={p.returncode}")

print("\n### 3. 못 읽는 경우")

lg = log("broken", [row(), "{이건 JSON 이 아니다", row(equal=False, diff=["total"]),
                    json.dumps({"ts": "x", "mode": "dual"})])
p, _ = run(["--log", lg])
check("깨진 줄이 있으면 exit 2 이고 몇 번째 줄인지 말한다",
      p.returncode == 2 and "[2]" in p.stderr and "[4]" in p.stderr,
      p.stderr.strip().splitlines()[-1][:80] if p.stderr else "")
check("깨진 줄이 있어도 읽은 만큼의 보고는 먼저 낸다",
      "실험" in p.stdout, "" if "실험" in p.stdout else "보고가 통째로 사라졌다")

p, _ = run(["--log", os.path.join(BASE, "없는파일.jsonl")])
check("로그가 없으면 exit 2 (빈 로그와 구분한다)",
      p.returncode == 2 and "로그가 없다" in p.stderr, f"exit={p.returncode}")

p, _ = run(["--config", EMPTY_CONFIG])
check("logPath 설정도 --log 도 없으면 멈추고 어느 키인지 말한다",
      p.returncode == 2 and "legacy.dualRun.logPath" in p.stderr, f"exit={p.returncode}")

p, _ = run(["--config", CONFIG])
check("--log 가 없으면 legacy.dualRun.logPath 를 쓴다",
      p.returncode == 1 and os.path.basename(DEFAULT_LOG) in p.stdout,
      f"exit={p.returncode}")

bad_ig = os.path.join(BASE, "ignore-bad.json")
with open(bad_ig, "w", encoding="utf-8") as fh:
    json.dump({"rules": [{"experiment": "x", "keys": "total"}]}, fh)
p, _ = run(["--log", lg_other, "--ignore", bad_ig])
check("ignore 형태가 어긋나면 조용히 무시하지 않고 exit 2",
      p.returncode == 2 and "keys" in p.stderr, f"exit={p.returncode}")

print("\n### 4. --as-fixtures · --json")

fx = os.path.join(BASE, "fixtures.json")
p, _ = run(["--log", lg_other, "--as-fixtures", fx])
doc = json.load(open(fx, encoding="utf-8")) if os.path.isfile(fx) else None
check("--as-fixtures 가 {experiment, input, control, candidate} 목록을 쓴다",
      isinstance(doc, list) and len(doc) == 2
      and sorted(doc[0]) == ["candidate", "control", "experiment", "input"],
      f"{doc if not isinstance(doc, list) else len(doc)}건")

p, _ = run(["--log", lg_other, "--json"])
try:
    j = json.loads(p.stdout)
except ValueError:
    j = None
check("--json 이 기계용 요약을 낸다 (실험별 집계와 서명 목록)",
      isinstance(j, dict) and j.get("unexpected") == 2
      and len(j.get("groups") or []) == 2
      and set(j["experiments"]) == {"list-page", "detail-page"},
      "" if j else p.stdout[:120])

print("\n### 5. 템플릿이 5.6 에서도 파싱되는가")

# `php -l` 은 8.x 로 도는 로컬 바이너리라 5.6 호환을 증명하지 못한다 - 상위 집합을 통과시킨다.
# 그래서 5.6 에 없는 구문을 이름으로 막는다. 이 트리의 한쪽 런타임이 5.6 이고, 거기서 나는
# 파스 에러는 흰 화면 하나로 끝나 어느 테스트도 잡지 않는다.
BANNED = {
    "?? 연산자": r"\?\?",
    "우주선 연산자": r"<=>",
    "화살표 함수": r"\bfn\s*\(",
    "스칼라 타입 선언": r"function\s+\w+\s*\([^)]*\b(int|float|string|bool|iterable|object)\s+\$",
    "반환 타입 선언": r"function\s+\w+\s*\([^)]*\)\s*:\s*[\\\w]",
    "strict_types": r"declare\s*\(\s*strict_types",
    "PHP7+ 내장 함수": r"\b(str_contains|str_starts_with|str_ends_with|array_key_first|"
                    r"random_int|is_iterable|intdiv)\s*\(",
    "JSON_THROW_ON_ERROR": r"JSON_THROW_ON_ERROR",
}
if not os.path.isfile(TEMPLATE):
    skip("템플릿 5.6 구문 검사", f"템플릿 없음: {TEMPLATE}")
else:
    raw = open(TEMPLATE, "rb").read()
    nonascii = [i for i, b in enumerate(raw) if b > 127]
    where = ""
    if nonascii:
        # 어느 줄인지 말한다. "비ASCII 45바이트"만으로는 그 45바이트를 찾으러
        # 파일 전체를 눈으로 훑어야 한다.
        lines = sorted({raw[:i].count(b"\n") + 1 for i in nonascii})
        where = (f"비ASCII {len(nonascii)}바이트 · {len(lines)}줄 "
                 f"({', '.join(str(n) for n in lines[:6])}"
                 + (" 외" if len(lines) > 6 else "") + ")")
    check("템플릿이 순수 ASCII 다 (레거시 트리는 파일마다 인코딩이 다르다)",
          not nonascii, where)
    # `errors="replace"`. 위 검사가 빨간불일 때 이 줄이 예외로 죽으면 **뒤의 검사가
    # 아예 돌지 않는다** — 실패 하나가 나머지 전부를 건너뛰게 만드는 것은 검사
    # 스위트가 가질 수 있는 가장 나쁜 성질이다. 한 줄이 깨져도 5.6 구문 검사는
    # 여전히 답할 수 있다.
    code = re.sub(r"/\*.*?\*/", "", raw.decode("ascii", "replace"), flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    hits = {name: len(re.findall(rx, code)) for name, rx in BANNED.items()
            if re.search(rx, code)}
    check("5.6 에 없는 구문을 쓰지 않는다 (php -l 은 8.x 라 이것을 증명하지 못한다)",
          not hits, str(hits) if hits else "")

print("\n### 6. 진짜 PHP 헬퍼가 쓴 로그")

php = shutil.which("php")
if not php:
    skip("템플릿을 실제로 돌려 만든 로그", "php 없음")
elif not os.path.isfile(TEMPLATE):
    skip("템플릿을 실제로 돌려 만든 로그", f"템플릿 없음: {TEMPLATE}")
else:
    driver = os.path.join(BASE, "driver.php")
    with open(driver, "w", encoding="ascii") as fh:
        fh.write(
            "<?php\n"
            "require_once " + json.dumps(TEMPLATE) + ";\n"
            "$ko = \"\\xb0\\xa1\\xb3\\xaa\";\n"
            "$control = function () use ($ko) {\n"
            "    return array('items' => array(array('seq' => 1, 'title' => $ko)),\n"
            "                 'total' => 120);\n"
            "};\n"
            "$same = function () use ($ko) {\n"
            "    return array('items' => array(array('seq' => 1, 'title' => $ko)),\n"
            "                 'total' => 120);\n"
            "};\n"
            "$candidate = function () use ($ko) {\n"
            "    return array('items' => array(array('seq' => 1, 'title' => $ko)),\n"
            "                 'total' => 7);\n"
            "};\n"
            "MigrationExperiment::run('list-page', 'T_MODE', $control, $same,\n"
            "    array(), array('input' => array('page' => 1)));\n"
            "MigrationExperiment::run('list-page', 'T_MODE', $control, $candidate,\n"
            "    array(), array('input' => array('page' => 2)));\n"
            "echo MigrationExperiment::mode('T_MODE');\n")
    php_log = os.path.join(BASE, "php.jsonl")
    env = dict(os.environ, T_MODE="dual", MIGRATION_EXPERIMENT_LOG=php_log)
    t0 = time.time()
    r = subprocess.run([php, driver], capture_output=True, text=True, timeout=60,
                       env=env, cwd=BASE)
    secs = time.time() - t0
    lines = (open(php_log, encoding="utf-8").read().splitlines()
             if os.path.isfile(php_log) else [])
    check("헬퍼가 dual 모드에서 호출마다 한 줄씩 남긴다",
          r.returncode == 0 and r.stdout.strip() == "dual" and len(lines) == 2,
          f"exit={r.returncode} 줄={len(lines)} {r.stderr.strip()[:60]}", secs=secs)
    p, _ = run(["--log", php_log])
    check("그 로그를 dualrun-report 가 그대로 읽어 불일치 한 건을 짚는다",
          p.returncode == 1 and "서명 1가지" in p.stdout and "total" in p.stdout,
          f"exit={p.returncode} {p.stderr.strip()[:80]}")
    check("호출자 file:line 이 보고에 실린다 (같은 메서드를 다른 페이지가 부른다)",
          "driver.php:" in p.stdout,
          [l.strip() for l in p.stdout.splitlines() if "호출자" in l][:1])
    ig3 = ignore_file("php", [{"experiment": "list-page", "keys": ["total"],
                               "ledger": "R-17", "reason": "의도수정"}])
    p, _ = run(["--log", php_log, "--ignore", ig3])
    check("헬퍼가 쓴 diff_keys 가 ignore.json 의 키와 같은 어휘다",
          p.returncode == 0, f"exit={p.returncode}")

# ------------------------------------------------------------------ 정리
shutil.rmtree(BASE, ignore_errors=True)
bad = [n for n, ok, _ in results if not ok]
print("\n" + "=" * 64)
if skipped:
    print(f"건너뜀 {len(skipped)}개 — " + ", ".join(n for n, _ in skipped))
    print("  건너뛴 검사는 통과가 아니다.")
print(f"{len(results) - len(bad)}/{len(results)} 통과"
      + ("" if not bad else "   실패: " + ", ".join(bad)))
sys.exit(1 if bad else 0)
