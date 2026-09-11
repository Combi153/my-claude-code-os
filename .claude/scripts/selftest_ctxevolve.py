#!/usr/bin/env python3
"""ctxevolve 검사 — 합성 저널로만 돈다. 회사 트리를 요구하지 않는다.

실패 경로를 밟는 것이 이 파일의 목적이다. 해피 패스만 검사하면, 이 도구가 조용히
빈손이 되는 경우를 아무도 못 본다 — 그게 이 저장소가 반복해 고쳐 온 결함이다.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "ctxevolve")
ok = fail = 0


def run(args, cwd=None):
    p = subprocess.run([sys.executable, TOOL] + args, capture_output=True, text=True, cwd=cwd)
    return p.returncode, p.stdout + p.stderr


def case(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  통과   {name}   {detail}")
    else:
        fail += 1
        print(f"  FAIL   {name}   {detail}")


def jl(d, role, rows):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{role}.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def item(**kw):
    base = {"ts": "2026-09-11T00:00:00+09:00", "slice": "p1", "role": "php-behavior-analyst",
            "lesson": "L", "trigger": "T", "evidence": ".claude/context/ledger-contract.md:1",
            "scope": "global"}
    base.update(kw)
    return base


print("### 1. 형식 검사는 실패를 잡는다")
with tempfile.TemporaryDirectory() as td:
    d = os.path.join(td, "area")
    jl(d, "php-behavior-analyst", [
        item(),
        item(evidence=""),
        item(trigger=""),
        item(scope="everywhere"),
        item(role=""),
    ])
    open(os.path.join(d, "php-behavior-analyst.jsonl"), "a", encoding="utf-8").write("{not json\n")
    rc, out = run(["--check", "--journal-dir", d])
    case("evidence 없는 항목을 FAIL 로 잡는다", "빠진 열" in out and "evidence" in out)
    case("trigger 없는 항목을 FAIL 로 잡는다", out.count("빠진 열") >= 2)
    case("scope 어휘 밖을 FAIL 로 잡는다", "scope 가" in out)
    case("role 없는 항목을 FAIL 로 잡는다", "role 이 없다" in out)
    case("깨진 JSON 줄을 조용히 넘기지 않는다", "JSON 이 아니다" in out)
    case("실패가 있으면 exit 1", rc == 1, f"exit={rc}")

print("\n### 2. 한 줄이 깨져도 나머지는 산다")
with tempfile.TemporaryDirectory() as td:
    d = os.path.join(td, "area")
    jl(d, "php-behavior-analyst", [item(lesson="살아있는 항목")])
    open(os.path.join(d, "php-behavior-analyst.jsonl"), "a", encoding="utf-8").write("{broken\n")
    rc, out = run(["--propose", "--journal-dir", d])
    case("깨진 줄 뒤에도 정상 항목이 후보가 된다", "살아있는 항목" in out)

print("\n### 3. scope 가 전파 범위를 정한다")
with tempfile.TemporaryDirectory() as td:
    d = os.path.join(td, "area")
    jl(d, "php-behavior-analyst", [
        item(lesson="전역 교훈", scope="global"),
        item(lesson="표면 교훈", scope="surface"),
        item(lesson="영역 교훈", scope="area"),
    ])
    rc, out = run(["--propose", "--journal-dir", d])
    case("global 만 후보가 된다", "전역 교훈" in out and "표면 교훈" not in out and "영역 교훈" not in out)
    case("후보 수를 말한다", "1 후보" in out)

print("\n### 4. 근거가 사라진 항목은 후보가 아니다")
with tempfile.TemporaryDirectory() as td:
    d = os.path.join(td, "area")
    jl(d, "php-behavior-analyst", [
        item(lesson="살아있는 근거"),
        item(lesson="죽은 근거", evidence="no-such-evidence.md:12"),
    ])
    rc, out = run(["--stale", "--propose", "--journal-dir", d])
    case("만료 후보로 표시한다", "만료 후보" in out and "no-such-evidence.md" in out)
    case("개정 후보에서는 뺀다", "제외:" in out and "1 후보" in out)
    case("빼면서 이유를 말한다", "근거가 사라진" in out)

print("\n### 5. 적용하지 않는다")
with tempfile.TemporaryDirectory() as td:
    d = os.path.join(td, "area")
    jl(d, "php-behavior-analyst", [item()])
    target = os.path.join(HERE, "..", "context", "ledger-contract.md")
    before = open(target, "rb").read()
    rc, out = run(["--propose", "--journal-dir", d])
    case("컨텍스트 파일을 고치지 않는다", open(target, "rb").read() == before)
    case("적용하지 않았다고 말한다", "적용하지 않았다" in out)
    case("무엇을 지울지 정하라고 말한다", "대체하는 산문" in out)

print("\n### 6. 답을 못 찾은 것과 답이 없는 것을 구별한다")
with tempfile.TemporaryDirectory() as td:
    rc, out = run(["--check", "--journal-dir", os.path.join(td, "없는디렉터리")])
    case("저널 디렉터리가 없으면 exit 3 으로 멈춘다", rc == 3, f"exit={rc}")
    case("무엇이 없는지 말한다", "저널 디렉터리가 없다" in out)
    d = os.path.join(td, "area")
    os.makedirs(d)
    rc, out = run(["--propose", "--journal-dir", d])
    case("빈 저널은 '항목이 없다'로 말한다 (후보 0 과 구별)", "항목이 없다" in out, f"exit={rc}")

print("\n### 7. 인자 없이 부르면 사용법과 exit 2")
rc, out = run([])
case("인자 없이 exit 2", rc == 2, f"exit={rc}")
case("사용법을 찍는다", "--propose" in out)

print("\n" + "-" * 70)
print(f"{ok}/{ok + fail} 통과")
sys.exit(0 if fail == 0 else 1)
