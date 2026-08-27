#!/usr/bin/env python3
"""
.claude/skill-usage.jsonl 을 읽어 스킬 사용 통계를 출력한다.

사용법:
  python3 .claude/skills/skill-stat/stat.py                # 전체 통계
  python3 .claude/skills/skill-stat/stat.py --since 7d     # 최근 7일
  python3 .claude/skills/skill-stat/stat.py --since 2026-08-01
  python3 .claude/skills/skill-stat/stat.py --skill git-commit   # 특정 스킬만
  python3 .claude/skills/skill-stat/stat.py --recent 10    # 최근 호출 내역(맥락 포함)
  python3 .claude/skills/skill-stat/stat.py --json         # 기계용 출력
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta

DEFAULT_LOG = os.path.join(
    os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()), ".claude", "skill-usage.jsonl"
)


def parse_since(value):
    """'7d' / '12h' / '2026-08-01' 을 datetime(aware) 으로 바꾼다."""
    if not value:
        return None
    now = datetime.now().astimezone()
    m = re.fullmatch(r"(\d+)([dhw])", value.strip().lower())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"d": timedelta(days=n), "h": timedelta(hours=n), "w": timedelta(weeks=n)}[unit]
        return now - delta
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        sys.exit("--since 형식이 잘못됨: %r (예: 7d, 12h, 2w, 2026-08-01)" % value)
    return dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)


def load(path, since=None, skill=None, session=None):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue  # 깨진 줄은 건너뛴다 (append-only 로그의 현실적 방어)
            try:
                r["_ts"] = datetime.fromisoformat(r["ts"])
            except (KeyError, ValueError):
                continue
            if since and r["_ts"] < since:
                continue
            if skill and skill not in r.get("skill", ""):
                continue
            if session and r.get("session", "") != session:
                continue
            rows.append(r)
    rows.sort(key=lambda r: r["_ts"])
    return rows


def width_of(text):
    """터미널 표시 폭. 한글·이모지는 2칸을 차지하므로 len() 으로는 정렬이 어긋난다."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text, w, align="<"):
    """표시 폭 기준으로 자르고 채운다."""
    while width_of(text) > w:
        text = text[:-1]
    space = " " * (w - width_of(text))
    return space + text if align == ">" else text + space


def bar(count, top, width=24):
    if top <= 0:
        return ""
    filled = max(1, round(count / top * width))
    return "█" * filled


def human(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def report(rows, recent):
    if not rows:
        print("기록된 스킬 호출이 없습니다.")
        print("(훅 등록 후 새 세션에서 스킬을 한 번 이상 호출해야 로그가 쌓입니다)")
        return

    counts = Counter(r["skill"] for r in rows)
    triggers = defaultdict(Counter)
    last_used = {}
    for r in rows:
        triggers[r["skill"]][r.get("trigger", "auto")] += 1
        last_used[r["skill"]] = r["_ts"]

    total = len(rows)
    span = "%s ~ %s" % (human(rows[0]["_ts"]), human(rows[-1]["_ts"]))
    sessions = len({r.get("session", "") for r in rows})

    print("스킬 사용 통계")
    print("─" * 64)
    print("기간      : %s" % span)
    print("총 호출   : %d회   |   스킬 종류: %d개   |   세션: %d개"
          % (total, len(counts), sessions))
    print()

    top = counts.most_common(1)[0][1]
    name_w = min(max(max(width_of(s) for s in counts), 12), 34)
    row = "%s %s %s  %s %s"
    print(row % (pad("스킬", name_w), pad("횟수", 5, ">"), pad("비율", 5, ">"),
                 pad("", 24), "최근 사용"))
    print("─" * 64)
    for skill, n in counts.most_common():
        print(row % (pad(skill, name_w), pad(str(n), 5, ">"),
                     pad("%.0f%%" % (n / total * 100), 5, ">"),
                     pad(bar(n, top), 24), human(last_used[skill])))
    print()

    # 직접 호출(/스킬명) vs 모델이 스스로 선택 — 스킬 설명(description)이
    # 제대로 작동하는지 보여주는 지표다.
    user_n = sum(t["user"] for t in triggers.values())
    print("호출 경로 : 사용자 직접 %d회 / 모델 자동 선택 %d회" % (user_n, total - user_n))

    if recent:
        print()
        print("최근 호출 %d건" % min(recent, total))
        print("─" * 64)
        for r in rows[-recent:][::-1]:
            print("%s  %s (%s)" % (human(r["_ts"]), r["skill"], r.get("trigger", "auto")))
            ctx = r.get("context") or "(맥락 없음)"
            print("    ↳ %s" % ctx)


def main():
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--log", default=DEFAULT_LOG)
    p.add_argument("--since")
    p.add_argument("--skill")
    p.add_argument("--session")
    p.add_argument("--recent", type=int, default=5)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    rows = load(a.log, parse_since(a.since), a.skill, a.session)

    if a.json:
        counts = Counter(r["skill"] for r in rows)
        print(json.dumps({
            "total": len(rows),
            "skills": [{"skill": s, "count": n} for s, n in counts.most_common()],
            "entries": [{k: v for k, v in r.items() if k != "_ts"} for r in rows],
        }, ensure_ascii=False, indent=2))
        return

    report(rows, a.recent)


if __name__ == "__main__":
    main()
