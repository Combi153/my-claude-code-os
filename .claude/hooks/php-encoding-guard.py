#!/usr/bin/env python3
"""Pre/PostToolUse(Edit|Write) — preserve per-file encoding in the legacy checkout.

The legacy PHP tree is not uniformly encoded. Measured in the target checkout:
two data-access files of the same service, two directories apart, are UTF-8 and
EUC-KR/CP949 respectively. An agent that writes Korean into the wrong one produces
a file that decodes as neither, and the page renders mojibake in production.
Nothing in the test suite catches it, because the bytes are only wrong for humans.

Two phases, two different postures:

  PreToolUse   record path -> encoding in .claude/.state/php-encoding.json, and
               warn — target is CP949, or sits outside the dirs we own. Never
               blocks: old files have to be editable too.
  PostToolUse  re-detect and BLOCK if the encoding changed, became undecodable,
               or replacement characters appeared. By then the damage is done and
               there is a definite thing to restore. Also nudges when a `phped`
               working copy was edited but not written back, and reports a file
               that no longer parses on the runtime it ships on.

No path from the legacy tree is written here: this file is tracked and the
repository is public, and such a path is company information just as much as the
code inside it. Everything environment-specific comes from
.claude/config/workspace.json (`legacy.treeRoot`, `legacy.ours`), which is
gitignored. Missing config disables the hook rather than blocking work.
"""
import json
import os
import subprocess
import sys

STATE = os.path.join(".claude", ".state", "php-encoding.json")
WATCHED_SUFFIXES = (".php", ".inc", ".html", ".htm", ".js", ".css", ".tpl")
LINT_SUFFIXES = (".php", ".inc", ".tpl", ".phtml")
MOJIBAKE = b"\xef\xbf\xbd"          # U+FFFD encoded as UTF-8
WORKDIR = os.sep + os.path.join(".claude", ".edit") + os.sep


def detect(path):
    """'ascii' | 'utf-8' | 'cp949' | 'undecodable' | None(missing)."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    if not raw:
        return "ascii"
    try:
        raw.decode("ascii")
        return "ascii"
    except UnicodeDecodeError:
        pass
    # UTF-8 first: a byte sequence valid as UTF-8 is almost never CP949 Korean by
    # accident, while the reverse happens often. This is the same order `file` uses.
    for enc in ("utf-8", "cp949"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "undecodable"


def config(project_dir):
    cfg = os.path.join(project_dir, ".claude", "config", "workspace.json")
    try:
        with open(cfg, encoding="utf-8") as fh:
            return json.load(fh).get("legacy") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_state(project_dir):
    try:
        with open(os.path.join(project_dir, STATE), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(project_dir, state):
    path = os.path.join(project_dir, STATE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Keep the file from growing without bound across a long session.
    if len(state) > 200:
        state = dict(list(state.items())[-100:])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh)


def emit(event, messages):
    """Advisory output. Several warnings go out as one block, not one each."""
    json.dump({"hookSpecificOutput": {
        "hookEventName": event,
        "additionalContext": "\n\n".join(messages),
    }}, sys.stdout)
    sys.exit(0)


def outside_ours(path, tree_root, ours):
    """treeRoot-relative name of the owner dir, or None when inside one.

    Ownership decides who may *edit* a file. It says nothing about whether a file
    is worth reading, which is why nothing here narrows a search.
    """
    if not tree_root or not ours:
        return None
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(tree_root))
    except ValueError:
        return None
    if rel.startswith(".."):
        return None                  # outside the tree entirely; not our business
    if any(rel == d or rel.startswith(d + "/") for d in ours):
        return None
    return rel


def restore_hint(path):
    """The command that undoes this edit, or a warning that nothing can."""
    d = os.path.dirname(os.path.abspath(path))
    try:
        top = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        if top.returncode == 0:
            root = top.stdout.strip()
            rel = os.path.relpath(os.path.abspath(path), root)
            tracked = subprocess.run(
                ["git", "-C", root, "ls-files", "--error-unmatch", rel],
                capture_output=True, timeout=5)
            if tracked.returncode == 0:
                return f"git -C {root} checkout -- {rel}"
            return ("이 파일은 git 이 추적하지 않습니다 — 되돌릴 방법이 없습니다. "
                    "다시 덮어쓰지 마세요.")
    except (OSError, subprocess.SubprocessError):
        pass
    return "이 경로에 해당하는 git 저장소를 찾지 못했습니다."


# 타임아웃은 **중첩되어야 한다.** 이 훅은 settings.json 에서 PostToolUse 35초를
# 받고, 그 안에서 `phplint` 를 25초로 부르며, `phplint` 는 그 안에서 도커에
# 20초를 준다. 예전에는 안쪽(도커 60초 × 재시도)이 바깥(25초)보다 컸다. 그러면
# 바깥이 먼저 죽고, `TimeoutExpired` 가 `SubprocessError` 로 잡혀 `None` 이
# 되어 **검사가 돌지 않았다는 사실이 통과와 같은 모양으로 도착했다.**
LINT_TIMEOUT = 25
DOCKER_TIMEOUT = 20


def lint_failure(path, scripts):
    """`phped` lints before it saves; a direct Write/Edit does not. This is the net.

    Returns (kind, message) - kind is "fails" when the file will not parse on the
    runtime it ships on, "unchecked" when the checker could not answer at all.
    The second one used to arrive as exit 0, which reads as a pass; a check that
    silently reports success is worse than no check.
    """
    if not path.lower().endswith(LINT_SUFFIXES):
        return None
    tool = os.path.join(scripts, "phplint")
    if not os.path.isfile(tool):
        # 도구가 없다는 것은 "문법이 괜찮다"가 아니다. 조용히 넘어가면 검사가
        # 사라진 것을 아무도 모르고, 그 상태가 통과와 구별되지 않는다.
        return "unchecked", f"문법 검사 도구를 찾지 못했습니다: {tool}"
    try:
        p = subprocess.run(
            [sys.executable, tool, path], capture_output=True,
            timeout=LINT_TIMEOUT,
            env={**os.environ, "PHPLINT_DOCKER_TIMEOUT": str(DOCKER_TIMEOUT)})
    except subprocess.TimeoutExpired:
        # 시간 초과는 결과가 아니다. 이것을 `None` 으로 돌려주면 "검사했고
        # 괜찮았다"와 구별되지 않는다.
        return "unchecked", (
            f"문법 검사 못 함 (시간 초과 {LINT_TIMEOUT}초). "
            f"컨테이너가 느리거나 이미지가 없을 수 있습니다 — "
            f"{tool} {path} 를 직접 돌려 확인하세요.")
    except (OSError, subprocess.SubprocessError):
        return None                  # cannot check is not the same as failed
    msg = p.stderr.decode("utf-8", "replace").strip()
    if p.returncode == 1:
        return "fails", msg
    if p.returncode == 3:
        return "unchecked", msg
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not path:
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    legacy = config(project_dir)
    root = legacy.get("root")
    if not root or not os.path.abspath(path).startswith(os.path.abspath(root)):
        return 0

    event = payload.get("hook_event_name", "PreToolUse")
    # 도구는 이 프로젝트에 있다. 2026-09-08 에 레거시 체크아웃에서 옮겼고, 이
    # 경로가 그때 함께 고쳐지지 않아서 `phplint` 를 찾지 못했다. 못 찾으면
    # `lint_failure` 가 None 을 돌려주므로 **검사가 돌지 않은 채 조용히
    # 통과했다.** 이 훅이 막으려는 실패가 정확히 그것이다.
    scripts = os.path.join(project_dir, ".claude", "scripts")
    in_workdir = WORKDIR in os.path.abspath(path)

    # ---- a `phped` working copy is UTF-8 by construction -------------------
    if in_workdir:
        if event == "PreToolUse":
            return 0
        meta = os.path.splitext(path)[0] + ".json"
        try:
            with open(meta, encoding="utf-8") as fh:
                source = json.load(fh).get("source", "")
        except (OSError, ValueError):
            source = ""
        if source:
            emit(event, [f"작업 사본을 고쳤습니다. 아직 원본에 반영되지 않았습니다:\n"
                         f"  {scripts}/phped save {source}"])
        return 0

    if not path.endswith(WATCHED_SUFFIXES):
        return 0

    state = load_state(project_dir)

    # ---- Pre: record, then advise ------------------------------------------
    if event == "PreToolUse":
        before = detect(path)
        if before is not None:
            state[path] = before
            save_state(project_dir, state)

        notes = []
        rel = outside_ours(path, legacy.get("treeRoot"), legacy.get("ours") or {})
        if rel:
            notes.append(
                f"소유권: {rel} 은 다른 팀 코드입니다. 읽는 것은 자유지만, 그렇게 "
                f"하기로 정한 게 아니라면 고치지 마세요.")
        if before == "cp949":
            notes.append(
                f"인코딩 경고: 이 파일은 CP949 입니다. 이 도구로 쓰면 고치려는 한 줄이 "
                f"아니라 파일 전체가 UTF-8 로 다시 쓰이면서 안의 한글이 전부 깨집니다.\n"
                f"왕복 편집을 쓰세요:\n"
                f"  {scripts}/phped open {path}\n"
                f"  ...출력된 작업 사본을 고친 뒤...\n"
                f"  {scripts}/phped save {path}")
        if notes:
            emit(event, notes)
        return 0

    # ---- Post: block on damage --------------------------------------------
    before = state.pop(path, None)
    save_state(project_dir, state)
    after = detect(path)

    if after == "undecodable":
        sys.stderr.write(
            f"인코딩이 깨졌습니다: {path}\n"
            f"  편집 전: {before or '알 수 없음'} -> 편집 후: 어떤 인코딩으로도 디코딩 불가\n\n"
            "한 파일 안에 서로 다른 인코딩의 바이트가 섞였습니다. 편집을 되돌리세요.\n"
            f"  {restore_hint(path)}\n"
            + (
                f"이 파일의 원본 인코딩은 {before} 입니다 — 그 인코딩으로만 쓰세요.\n"
                if before in ("utf-8", "cp949")
                else "되돌린 뒤 원본 인코딩을 먼저 확인하세요.\n"
            )
            + f"다시 고칠 때는 {scripts}/phped 를 거치세요.\n"
            "  (한글을 넣지 않고 ASCII 만 쓰면 이 문제를 통째로 피할 수 있습니다)\n"
        )
        return 2

    if before in ("utf-8", "cp949") and after in ("utf-8", "cp949") and before != after:
        sys.stderr.write(
            f"파일 인코딩이 바뀌었습니다: {path}\n"
            f"  {before} -> {after}\n\n"
            "이 레거시 트리는 파일마다 인코딩이 다르고, 페이지 헤더가 원래 인코딩을\n"
            "선언합니다. 인코딩을 바꾸면 화면이 깨집니다. 되돌리세요.\n"
            f"  {restore_hint(path)}\n"
            f"다시 고칠 때는 {scripts}/phped 를 거치세요.\n"
            "  (한글을 넣지 않고 ASCII 식별자만 쓰면 이 문제를 통째로 피할 수 있습니다)\n"
        )
        return 2

    # Encoding held, but the bytes may still have been mangled in place: a
    # decode-with-replacement upstream leaves valid UTF-8 full of U+FFFD.
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return 0
    n = raw.count(MOJIBAKE)
    if n:
        sys.stderr.write(
            f"인코딩이 손상됐습니다: {path}\n"
            f"  대체 문자(U+FFFD) {n}개가 생겼습니다. 이 파일의 한글이 파괴됐습니다.\n\n"
            "되돌리세요.\n"
            f"  {restore_hint(path)}\n"
            f"다시 고칠 때는 {scripts}/phped 를 거치세요.\n"
        )
        return 2

    checked = lint_failure(path, scripts)
    if checked:
        kind, msg = checked
        if kind == "fails":
            emit(event, ["문법: 이 파일은 자신이 배포되는 PHP 버전에서 "
                         f"돌지 않습니다.\n{msg}"])
        else:
            emit(event, ["문법: 이 파일은 검사되지 않았습니다 — 통과한 것이 "
                         f"아닙니다.\n{msg}"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
