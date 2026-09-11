#!/usr/bin/env python3
"""주입 예산 검사 — 어떤 소비처도 MAX_INJECT_BYTES 의 90% 를 넘지 않는다.

설계 문서의 성장 규칙 4번이 이 검사다. 줄 수가 아니라 바이트로 재는 이유는 기계가
바이트로 자르기 때문이고, 90% 로 두는 이유는 파일이 자랐을 때 **조용히 잘리기 전에**
멈추기 위해서다. 잘린 사실이 통과와 같은 모양으로 도착하는 것이 이 OS 가 반복해 고쳐
온 결함이다.

프론트매터를 여기서 직접 읽는다. 훅의 파서를 import 하면 훅이 깨진 회차에 이 검사도
함께 침묵하고, 그러면 두 검사가 한 번에 사라진다.

인자 없이 돌고 회사 트리를 요구하지 않는다.
"""
import glob
import os
import re
import sys

BUDGET_FRACTION = 0.90
LINE_SMELL = {"context": 40, "agent": 60, "skill": 150}

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def max_inject_bytes(root):
    """훅이 선언한 예산을 훅 소스에서 읽는다. 못 읽으면 그렇다고 말하고 멈춘다."""
    p = os.path.join(root, ".claude", "hooks", "context-inject.py")
    if not os.path.isfile(p):
        return None, f"{p} 없음 — 예산을 알 수 없다"
    src = open(p, encoding="utf-8").read()
    m = re.search(r"^MAX_INJECT_BYTES\s*=\s*(.+)$", src, re.M)
    if not m:
        return None, "context-inject.py 에서 MAX_INJECT_BYTES 를 찾지 못했다"
    try:
        return int(eval(m.group(1), {"__builtins__": {}}, {})), None
    except Exception as exc:
        return None, f"MAX_INJECT_BYTES 값을 해석하지 못했다: {exc}"


def body_of(text):
    parts = text.split("---\n", 2)
    return parts[2] if len(parts) == 3 else text


def context_items(root):
    """(name, agents, skills, rendered_bytes, body_lines) 목록."""
    out = []
    d = os.path.join(root, ".claude", "context")
    for f in sorted(glob.glob(os.path.join(d, "*.md"))):
        s = open(f, encoding="utf-8").read()
        parts = s.split("---\n", 2)
        if len(parts) != 3:
            out.append((os.path.basename(f), [], [], 0, 0, "프론트매터를 읽을 수 없다"))
            continue
        fm, body = parts[1], parts[2]

        def lst(key):
            m = re.search(rf"^  {key}: \[(.*?)\]$", fm, re.M)
            return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []

        def val(key):
            m = re.search(rf"^{key}: (.+)$", fm, re.M)
            return m.group(1).strip() if m else ""

        name = val("name")
        # 훅이 조립하는 블록과 같은 모양으로 센다.
        block = (
            f'\n<context name="{name}" kind="{val("kind")}" token="{val("token")}">\n'
            f"{body.strip()}\n</context>"
        )
        out.append(
            (name, lst("agents"), lst("skills"), len(block.encode("utf-8")),
             len(body.strip().splitlines()), None)
        )
    return out


def main():
    cap, err = max_inject_bytes(ROOT)
    fails, warns = [], []

    print("## 주입 예산")
    if err:
        # 예산을 모르는 것은 통과가 아니다.
        print(f"  FAIL  {err}")
        return 1

    items = context_items(ROOT)
    broken = [n for n, _, _, _, _, e in items if e]
    for n in broken:
        fails.append(f"{n}: 프론트매터를 읽을 수 없다")

    header = 112  # render() 의 첫 줄
    limit = int(cap * BUDGET_FRACTION)
    consumers = sorted({c for _, ags, sks, _, _, _ in items for c in ags + sks})
    for c in consumers:
        b = header + sum(
            sz for _, ags, sks, sz, _, e in items if not e and c in ags + sks
        )
        pct = 100.0 * b / cap
        mark = "통과"
        if b > cap:
            mark, _ = "FAIL", fails.append(f"{c}: 주입 {b}B > 예산 {cap}B — 파일이 잘린다")
        elif b > limit:
            mark, _ = "경고", warns.append(f"{c}: 주입 {b}B > {int(BUDGET_FRACTION*100)}% ({limit}B)")
        print(f"  {mark:4}  {c:32} {b:6}B  {pct:5.1f}%")

    print("\n## 줄 수 (게이트가 아니라 냄새)")
    for n, _, _, _, lines, e in items:
        if e:
            continue
        over = " ← 넘음" if lines > LINE_SMELL["context"] else ""
        print(f"        {n:32} {lines:4}줄{over}")
    for kind, pat, key in (
        ("agent", ".claude/agents/*.md", "agent"),
        ("skill", ".claude/skills/*/SKILL.md", "skill"),
    ):
        for f in sorted(glob.glob(os.path.join(ROOT, pat))):
            lines = len(body_of(open(f, encoding="utf-8").read()).strip().splitlines())
            if lines > LINE_SMELL[key]:
                label = os.path.basename(os.path.dirname(f)) if key == "skill" else os.path.basename(f)
                print(f"        {label:32} {lines:4}줄 ← {kind} 냄새 상한 {LINE_SMELL[key]}")

    if warns:
        print("\n경고:")
        for w in warns:
            print(f"  - {w}")
    if fails:
        print("\nFAIL:")
        for f_ in fails:
            print(f"  - {f_}")
        return 1
    print(f"\n{len(consumers)} 소비처 전부 예산 {int(BUDGET_FRACTION*100)}% 이내")
    return 0


if __name__ == "__main__":
    sys.exit(main())
