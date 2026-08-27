#!/usr/bin/env python3
"""
Skill 사용 기록 훅 (PostToolUse / matcher: Skill)

Claude Code는 스킬을 호출할 때 `Skill` 툴을 사용한다.
이 스크립트는 그 툴 호출 직후 실행되어, 어떤 스킬을 어떤 맥락에서 썼는지
`.claude/skill-usage.jsonl` 에 한 줄(JSON)씩 append 한다.

stdin 으로 들어오는 훅 페이로드(JSON) 주요 필드:
  session_id      : 세션 식별자
  transcript_path : 이 세션의 대화 기록(JSONL) 경로  -> "맥락" 추출에 사용
  cwd             : 훅 실행 시점의 작업 디렉터리
  tool_name       : "Skill"
  tool_input      : {"skill": "<이름>", "args": "<인자>"}

원칙: 훅은 절대 세션을 방해하면 안 된다.
      어떤 예외가 나든 조용히 exit 0 한다.
"""

import json
import os
import re
import sys
from datetime import datetime

MAX_PROMPT = 160   # 맥락 스니펫 최대 길이
MAX_ARGS = 120
TAIL_BYTES = 512 * 1024  # 트랜스크립트는 뒤쪽 512KB만 읽는다 (긴 세션 대비)


def clean(text: str) -> str:
    """시스템이 주입한 블록과 개행을 걷어내고 한 줄로 만든다."""
    text = re.sub(r"<system-reminder>.*?</system-reminder>", " ", text, flags=re.S)
    text = re.sub(r"<local-command-stdout>.*?</local-command-stdout>", " ", text, flags=re.S)
    text = re.sub(r"<command-message>.*?</command-message>", " ", text, flags=re.S)
    text = re.sub(r"<command-args>(.*?)</command-args>", r" \1", text, flags=re.S)
    text = re.sub(r"</?command-name>", "", text)
    return " ".join(text.split())


def last_user_message(transcript_path: str) -> str:
    """트랜스크립트에서 가장 최근 '사람이 실제로 쓴' 메시지를 찾는다.

    툴 실행 결과(tool_result)도 role=user 로 기록되므로 걸러내야 한다.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            chunk = f.read().decode("utf-8", "replace")
    except OSError:
        return ""

    for line in reversed(chunk.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "user":
            continue
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            # tool_result 만 들어있는 턴은 사람의 발화가 아니다
            texts = [b.get("text", "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            if not texts:
                continue
            text = "\n".join(texts)
        else:
            continue
        text = clean(text)
        if text:
            return text
    return ""


def main() -> None:
    payload = json.load(sys.stdin)
    tool_input = payload.get("tool_input") or {}

    skill = (tool_input.get("skill") or "").strip()
    if not skill:
        return  # 스킬 이름이 없으면 기록할 것도 없다

    args = clean(str(tool_input.get("args") or ""))[:MAX_ARGS]
    prompt = last_user_message(payload.get("transcript_path", ""))

    # 사용자가 /스킬명 으로 직접 부른 것인지, 모델이 알아서 고른 것인지 구분한다.
    short = skill.split(":")[-1]
    trigger = "user" if re.search(r"(^|\s)/(%s|%s)\b" % (re.escape(skill), re.escape(short)),
                                  prompt) else "auto"

    record = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "skill": skill,
        "trigger": trigger,
        "args": args,
        "context": prompt[:MAX_PROMPT],
        "session": payload.get("session_id", ""),
        "cwd": payload.get("cwd", ""),
    }

    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    log_dir = os.path.join(project, ".claude")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "skill-usage.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 훅 실패가 세션을 막지 않도록 항상 조용히 종료
    sys.exit(0)
