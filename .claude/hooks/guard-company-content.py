#!/usr/bin/env python3
"""PreToolUse(Bash) — keep company content out of this public repository.

CLAUDE.md forbids moving anything from the gitignored company checkouts into a
tracked file: source, internal domains, issue IDs, people's names. git already
refuses to stage ignored paths, but it cannot see the case that actually bites —
a skill or doc that *quotes* company internals.

So this hook fires on the git commands that would publish, and checks two things:

  1. Path guard   — nothing being published lives under a gitignored company dir.
  2. Content guard — the published diff matches none of the redaction patterns.

**검사 대상은 명령마다 다르다.** 트리거는 셋인데 인덱스만 읽으면, 인덱스가 비어 있는
두 명령이 한 줄도 검사되지 않은 채 통과한다 — 그리고 그 통과는 깨끗한 통과와 같은
모양으로 도착한다.

  git add        인덱스                     (이 훅은 도구 실행 **전**에 도므로 방금
                                            넣으려는 것은 아직 없다 — 그것은 뒤따르는
                                            `commit` 에서 걸린다)
  git commit     인덱스
  git commit -a  인덱스 + 작업 트리의 추적 파일 변경  (커밋 안에서 스테이징한다)
  git push       원격에 아직 없는 커밋들의 변경        (인덱스는 이미 비어 있다)

`-C` 는 읽는다. 이 OS 의 규칙이 모든 경로를 `git -C <절대경로>` 로 쓰게 하므로, 그것을
무시하면 훅은 명령이 건드리지도 않는 저장소를 검사하고 그 결과를 이 저장소의 판정으로
내놓는다. 대상이 이 저장소가 아니면 판정하지 않고 그 사실을 말하며, 대상을 **확정할 수
없으면 막는다** — 확정할 수 없는 대상이 이 저장소일 수도 있다.

패턴은 `.claude/config/redaction.json` 에 있고, 그 목록 자체가 내부 시스템 이름을
담으므로 gitignore 된다. **없거나 깨졌거나 0개면 막는다.** 예전에는 그때 내용 검사를
조용히 건너뛰었는데, 새 체크아웃에는 그 파일이 없으므로 "패턴을 하나도 보지 않았다"가
"패턴에 걸리지 않았다"와 구별되지 않았다. 경로 검사는 설정과 무관하게 항상 돈다.

Exit 2 blocks the tool call and shows stderr to Claude.
"""
import json
import os
import re
import shlex
import subprocess
import sys

# 복합 명령의 구분자. `&&`·`||` 를 먼저 보고 남은 한 글자짜리를 본다.
SEP = re.compile(r"&&|\|\||[;\n|&]")

# `git` 서브명령 앞에 오는 옵션 중 다음 토큰을 값으로 먹는 것들.
GIT_PRE_VALUE = ("-C", "-c", "--exec-path", "--namespace", "--super-prefix",
                 "--work-tree", "--git-dir", "--config-env")

# `git commit` 에서 다음 토큰을 값으로 먹는 옵션들. 값을 플래그로 읽으면
# `git commit -m "-a"` 가 작업 트리 검사까지 켠다.
COMMIT_VALUE = {"-m", "--message", "-F", "--file", "-t", "--template",
                "-c", "--reedit-message", "-C", "--reuse-message",
                "--author", "--date", "--fixup", "--squash", "--cleanup",
                "--gpg-sign", "-S", "--pathspec-from-file", "--trailer",
                "-u", "--untracked-files"}
SHORT_CLUSTER = re.compile(r"^-[A-Za-z]+$")

PUBLISHING = ("add", "commit", "push")

# Directories the repository declares as company checkouts. Derived from .gitignore
# so the two never drift; anything anchored there must never be staged.
#
# .gitignore writes a directory three ways, and reading only one of them is a
# guard that reports "clean" on the paths it never looked at:
#
#   /cs-system/          leading and trailing slash - anchored at the root
#   handoff/             trailing slash only        - matches at any depth
#   /docs/lecture-notes  leading slash only         - anchored, no trailing slash
#
# The first was the only shape this function read, so the handoff notes and the
# lecture material - both of which carry company content - passed the path guard
# silently. Returns [(path, anchored), ...].
def ignored_company_dirs(root):
    path = os.path.join(root, ".gitignore")
    dirs = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("!"):
                    continue
                if any(c in line for c in "*?["):
                    continue          # a glob is not a path prefix
                if not (line.startswith("/") or line.endswith("/")):
                    continue          # names one file, not a tree
                dirs.append((line.strip("/"), line.startswith("/")))
    except OSError:
        pass
    return dirs


def under(path, d, anchored):
    """Is `path` inside the ignored entry `d`?

    An anchored entry (`/cs-system/`) only matches from the repository root; an
    unanchored one (`handoff/`) matches at any depth, which is what gitignore
    itself means by the two shapes.
    """
    if anchored:
        return path == d or path.startswith(d + "/")
    return ("/" + path + "/").find("/" + d + "/") >= 0


def run_git(repo, *args):
    """`(종료코드, stdout, stderr)`.

    **실패를 빈 출력으로 바꾸지 않는다.** 예전 구현은 예외와 0 아닌 종료를 모두
    `""` 로 돌려줬고, 그러면 "검사할 변경이 없다"와 "검사하지 못했다"가 같은 값이
    된다. 뒤쪽이 앞쪽으로 읽히는 것이 이 훅이 막으려는 실패 모양 그 자체다.
    """
    try:
        p = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                           text=True, timeout=10)
    except Exception as exc:
        return 127, "", repr(exc)
    return p.returncode, p.stdout, p.stderr


def toplevel(d):
    """`(저장소 루트, 실패 이유)`. 둘 중 하나만 값을 가진다."""
    if not d or not os.path.isdir(d):
        return None, f"`{d}` 디렉터리가 없다"
    code, out, err = run_git(d, "rev-parse", "--show-toplevel")
    if code != 0 or not out.strip():
        return None, (err or out).strip().splitlines()[0] if (err or out).strip() \
            else f"`{d}` 가 git 저장소가 아니다"
    return os.path.realpath(out.strip()), None


def commit_stages_worktree(args):
    """`git commit` 이 커밋 안에서 스테이징하는가 — `-a`·`--all`·`-am` 같은 묶음.

    값을 받는 옵션의 값은 건너뛴다. 묶음(`-am`)은 왼쪽부터 읽다가 값을 먹는 글자를
    만나면 멈춘다 — `-ma` 의 `a` 는 플래그가 아니라 메시지다.
    """
    i = 0
    while i < len(args):
        t = args[i]
        if t == "--":
            break
        if t in ("-a", "--all"):
            return True
        if t in COMMIT_VALUE:
            i += 2
            continue
        if t.startswith("--"):
            i += 1
            continue
        if SHORT_CLUSTER.match(t):
            for ch in t[1:]:
                if ch == "a":
                    return True
                if "-" + ch in COMMIT_VALUE:
                    break
            i += 2 if "-" + t[-1] in COMMIT_VALUE else 1
            continue
        i += 1
    return False


def git_parts(command):
    """복합 명령에서 `git add|commit|push` 마다 `(서브명령, -C 경로, -a 여부)`.

    `&&`·`;`·개행·파이프로 이어진 조각을 각각 따로 본다. 명령 전체를 정규식 하나로
    보면 `echo x && git commit -am y` 의 커밋을 첫 조각의 판정으로 덮어쓴다.

    `-C` 를 읽는 이유는 이 OS 의 규칙이 모든 경로를 `git -C <절대경로>` 로 쓰게 하기
    때문이다. 그것을 무시하면 훅은 명령이 건드리지도 않는 저장소를 검사하고, 그
    결과를 "깨끗하다"로 보고한다.
    """
    out = []
    for raw in SEP.split(command or ""):
        if "git" not in raw:
            continue
        try:
            toks = shlex.split(raw, posix=True)
        except ValueError:
            toks = raw.split()
        i = 0
        while i < len(toks) and os.path.basename(toks[i]) != "git":
            i += 1                      # `env A=1 git ...`, `/usr/bin/git ...`
        if i >= len(toks):
            continue
        i += 1
        cdir = None
        while i < len(toks) and toks[i].startswith("-"):
            t = toks[i]
            if t in GIT_PRE_VALUE:
                if t == "-C" and i + 1 < len(toks):
                    cdir = toks[i + 1]
                i += 2
                continue
            i += 1
        if i >= len(toks):
            continue
        sub = toks[i]
        if sub not in PUBLISHING:
            continue
        out.append((sub, cdir,
                    sub == "commit" and commit_stages_worktree(toks[i + 1:])))
    return out


def push_base(repo):
    """push 가 새로 공개하는 커밋의 기준. `(기준, 못 정한 이유)`.

    업스트림 → `origin/HEAD` → `origin/main` 순으로 본다. 셋 다 없으면 **통과시키지
    않는다.** 기준이 없으면 무엇이 새로 나가는지 알 수 없고, 그때 조용히 0 을 내면
    "검사했고 깨끗하다"와 구별되지 않는다.
    """
    code, out, _ = run_git(repo, "rev-parse", "--abbrev-ref",
                           "--symbolic-full-name", "@{upstream}")
    if code == 0 and out.strip():
        return out.strip(), None
    code, out, _ = run_git(repo, "symbolic-ref", "refs/remotes/origin/HEAD")
    ref = out.strip()
    if code == 0 and ref.startswith("refs/remotes/"):
        return ref[len("refs/remotes/"):], None
    code, _, _ = run_git(repo, "rev-parse", "--verify", "--quiet", "origin/main")
    if code == 0:
        return "origin/main", None
    return None, (
        "push 가 무엇을 새로 공개하는지 판정할 기준을 정하지 못했습니다.\n"
        "    업스트림(@{upstream}) 없음 · origin/HEAD 없음 · origin/main 없음\n"
        "    조치: `git branch --set-upstream-to=origin/<브랜치>` 로 업스트림을 붙이거나\n"
        "          `git remote set-head origin -a` 로 원격 기본 브랜치를 정한 뒤 다시 push 하세요.")


def scopes_for(repo, sub, stages_worktree):
    """`([(이름, name-only 인자, unified=0 인자)], 막는 사유)`."""
    index = ("인덱스", ["diff", "--cached", "--name-only"],
             ["diff", "--cached", "--unified=0"])
    if sub == "add":
        return [index], []
    if sub == "commit":
        scopes = [index]
        if stages_worktree:
            # `-a` 는 커밋 안에서 스테이징한다. 훅이 도는 시점의 인덱스는 비어
            # 있을 수 있고, 그 빈 인덱스가 예전에는 "검사할 것이 없다"로 읽혔다.
            scopes.append(("작업 트리", ["diff", "--name-only"],
                           ["diff", "--unified=0"]))
        return scopes, []
    base, why = push_base(repo)
    if not base:
        return [], [why]
    rng = f"{base}..HEAD"
    return [(rng, ["diff", "--name-only", rng],
             ["diff", "--unified=0", rng])], []


def load_redaction(root):
    """`(패턴 목록, allowPaths, 문제 이유)`. 문제가 있으면 패턴은 None 이다.

    **없거나 깨졌거나 0개면 막는다.** 이 파일은 gitignore 되어 있어서 새 체크아웃에는
    없고, 예전에는 그 상태가 통과와 구별되지 않았다. 패턴 하나의 컴파일 실패도 같다 —
    조용히 버리면 그 모양의 유출만 검사에서 빠지고, 빠진 사실은 아무 데도 남지 않는다.
    """
    path = os.path.join(root, ".claude", "config", "redaction.json")
    example = os.path.join(root, ".claude", "config", "redaction.example.json")
    hint = (f"조치: `cp {example} {path}` 로 복사해 값을 채우세요.\n"
            "    redaction.json 은 gitignore 되어 있으므로 새 체크아웃에는 없습니다.")
    if not os.path.isfile(path):
        return None, set(), f"{path} 가 없어 내용 검사를 한 줄도 하지 못했습니다.\n    {hint}"
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, set(), f"{path} 를 읽을 수 없습니다: {exc}\n    {hint}"
    if not isinstance(cfg, dict):
        return None, set(), f"{path} 의 최상위가 객체가 아닙니다.\n    {hint}"
    entries = cfg.get("patterns")
    if not isinstance(entries, list) or not entries:
        return None, set(), (f"{path} 에 쓸 수 있는 패턴이 0개입니다 — "
                             "내용 검사가 아무것도 보지 못합니다.\n    " + hint)
    compiled, broken = [], []
    for n, entry in enumerate(entries, 1):
        name = (entry.get("name") if isinstance(entry, dict) else None) or f"#{n}"
        if not isinstance(entry, dict) or not entry.get("regex"):
            broken.append(f"{name}: `regex` 가 없다")
            continue
        # Default to case-insensitive: that is what the first patterns were written
        # against. A pattern whose whole signal is CamelCase must opt out, or `re.I`
        # turns `[A-Z]\w+Service` into a match for the word "microservice" — and a
        # guard that blocks ordinary English is a guard someone switches off.
        flags = 0 if entry.get("ignoreCase") is False else re.I
        try:
            compiled.append((name, re.compile(entry["regex"], flags)))
        except re.error as exc:
            broken.append(f"{name}: 정규식을 컴파일할 수 없다 — {exc}")
    if broken:
        return None, set(), (f"{path} 의 패턴 {len(broken)}개를 쓸 수 없습니다:\n"
                             + "\n".join("      " + b for b in broken)
                             + "\n    패턴이 조용히 버려지면 그 모양의 유출만 검사에서 빠집니다.")
    return compiled, set(cfg.get("allowPaths") or []), None


def added_lines(diff):
    """`(파일, 추가된 줄)`. 지우는 줄은 보지 않는다 — 유출을 지우는 것은 막지 않는다."""
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        yield current, line


def emit_note(notes):
    """판정하지 않았다는 사실을 Claude 가 보는 자리에 남긴다.

    exit 0 의 stderr 는 Claude 에 닿지 않는다. 그래서 "이 저장소를 검사하지 않았다"를
    stderr 로만 적으면, 검사한 것과 구별할 수 없는 침묵이 된다.
    """
    if not notes:
        return
    text = "공개 저장소 가드: " + " / ".join(notes)
    try:
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                          "additionalContext": text}},
                  sys.stdout, ensure_ascii=False)
    except Exception:
        pass
    sys.stderr.write(text + "\n")


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    parts = git_parts(command)
    if not parts:
        return 0

    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    project_top, project_why = toplevel(root)
    company = ignored_company_dirs(root)
    problems, blockers, notes, diffs = [], [], [], []

    for sub, cdir, stages_worktree in parts:
        repo = os.path.expanduser(cdir) if cdir else root
        if not os.path.isabs(repo):
            repo = os.path.join(root, repo)
        top, why = toplevel(repo)
        if top is None:
            # **어느 저장소를 건드리는지 모르면 막는다.** 그 저장소가 이 공개
            # 저장소일 수도 있고, 그때 통과시키면 검사하지 못한 것이 통과와 같은
            # 모양으로 나간다. `-C` 값이 셸 변수면 훅에는 펼쳐지지 않은 문자열로
            # 도착하므로, 이 자리가 그것을 알아차리는 유일한 지점이다.
            if cdir:
                blockers.append(
                    f"git {sub} 의 `-C {cdir}` 가 가리키는 저장소를 확정할 수 "
                    f"없습니다: {why}\n"
                    "    셸 변수는 훅에 펼쳐지지 않은 채로 옵니다 — "
                    "절대경로를 리터럴로 쓰세요.")
            else:
                blockers.append(f"`{root}` 를 검사할 수 없습니다: {project_why or why}")
            continue
        if project_top and top != project_top:
            notes.append(f"git {sub} 는 다른 저장소(`{top}`)를 향하므로 이 공개 "
                         "저장소의 가드가 판정하지 않았습니다")
            continue
        if not project_top:
            notes.append(f"git {sub} 의 대상 `{top}` 이 이 프로젝트(`{root}`)가 "
                         "아니어서 판정하지 않았습니다")
            continue

        scopes, cannot = scopes_for(top, sub, stages_worktree)
        blockers += cannot
        for label, name_args, diff_args in scopes:
            code, out, err = run_git(top, *name_args)
            if code != 0:
                blockers.append(f"git {sub} 의 {label} 목록을 얻지 못했습니다: "
                                f"{(err or out).strip()[:200]}")
                continue
            for path in [p for p in out.splitlines() if p]:
                for d, anchored in company:
                    if under(path, d, anchored):
                        problems.append(f"  [{label}] 회사 경로: {path}  "
                                        f"(gitignored {d}/ 아래)")
            code, diff, err = run_git(top, *diff_args)
            if code != 0:
                blockers.append(f"git {sub} 의 {label} 변경 내용을 얻지 못했습니다: "
                                f"{(err or diff).strip()[:200]}")
                continue
            diffs.append((label, diff))

    # 내용 검사. 설정이 없거나 깨졌으면 막는다 — 경로 검사는 위에서 이미 돌았다.
    if diffs:
        patterns, allow, cfg_problem = load_redaction(root)
        if cfg_problem:
            blockers.append(cfg_problem)
        else:
            for label, diff in diffs:
                for current_file, line in added_lines(diff):
                    if current_file in allow:
                        continue
                    for name, rx in patterns:
                        hit = rx.search(line)
                        if hit:
                            problems.append(
                                f"  [{label}] {current_file}: {name} "
                                f"-> {hit.group(0)!r}")
                            break

    if not problems and not blockers:
        emit_note(notes)
        return 0

    seen, unique = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    if unique:
        sys.stderr.write(
            "이 저장소는 공개됩니다. 회사 내용이 추적 파일에 들어가려 합니다:\n\n"
            + "\n".join(unique[:20])
            + ("\n  ... (외 %d건)" % (len(unique) - 20) if len(unique) > 20 else "")
            + "\n\n조치: 값을 .claude/config/workspace.json(gitignored)으로 옮기고\n"
            "스킬·문서에는 일반 명칭만 남기세요. 명령을 중단했습니다.\n")
    if blockers:
        sys.stderr.write(
            ("\n" if unique else "")
            + "공개 저장소 가드가 검사를 끝내지 못했습니다 — 통과가 아닙니다:\n\n"
            + "\n".join("  " + b for b in dict.fromkeys(blockers))
            + "\n\n검사하지 못한 것을 통과로 내보내지 않기 위해 명령을 중단했습니다.\n")
    for n in notes:
        sys.stderr.write("  참고: " + n + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
