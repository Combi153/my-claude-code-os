#!/usr/bin/env bash
# Environment status for the legacy-migrate orchestrator.
# Reads .claude/config/workspace.json and probes each moving part, so Phase 0 does not
# have to guess what is up. Every probe is read-only and fails soft.
#
# Nothing here names a surface, a port, a module, or a directory: those come from the
# config, so this file stays publishable and works for a workspace whose surfaces are
# named something else entirely. The artifact numbering is not here either — it is read
# from references/artifacts.json, which is the one place that defines it.
#
# Python decides *what* to report and formats the labels; bash only runs curl and
# docker. The two talk over TSV so a path containing a space cannot shift a field.
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
CFG="$ROOT/.claude/config/workspace.json"
# artifacts.json is resolved from this script's own location, not from ROOT: the numbering
# belongs to the skill, and the skill knows where it lives even when ROOT is pointed elsewhere.
ART="$(dirname "${BASH_SOURCE[0]:-$0}")/references/artifacts.json"

if [ ! -f "$CFG" ]; then
  echo "no workspace.json - copy .claude/config/workspace.example.json and fill it in"
  exit 0
fi

# curl prints 000 when it cannot connect; report that as DOWN rather than a status code.
probe() {
  local code
  [ -z "$1" ] && { echo "no URL"; return; }
  code=$(curl -s -o /dev/null -m 2 -w "%{http_code}" "$1" 2>/dev/null)
  if [ -z "$code" ] || [ "$code" = "000" ]; then echo "DOWN"; else echo "$code"; fi
}

# docker hangs when the daemon is wedged, and this block is embedded in SKILL.md with `!`,
# so a hang stops the skill from loading at all. Bound every docker call and, on timeout,
# say "cannot determine (timed out)" rather than returning an empty list that reads as "nothing is up".
bounded() {          # bounded <seconds> <cmd...>
  local secs="$1"; shift
  local tmp pid i=0
  tmp=$(mktemp) || return 125
  ( "$@" >"$tmp" 2>/dev/null ) & pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -ge $((secs * 10)) ]; then kill -9 "$pid" 2>/dev/null; rm -f "$tmp"; return 124; fi
    sleep 0.1
  done
  wait "$pid" 2>/dev/null
  cat "$tmp"; rm -f "$tmp"
}

while IFS=$'\t' read -r kind a b; do
  case "$kind" in
    LINE)   printf '%s\n' "$a" ;;
    PROBE)  printf '%s = %s\n' "$a" "$(probe "$b")" ;;
    JAVA)
      if [ -z "$b" ]; then
        printf '%s javaHome unset - gradle may run on the default JDK and fail\n' "$a"
      elif [ ! -x "$b/bin/java" ]; then
        printf '%s no JDK at the javaHome path\n' "$a"
      else
        printf '%s%s\n' "$a" "$("$b/bin/java" -version 2>&1 | head -1 | sed 's/.*version //; s/"//g')"
      fi ;;
    DOCKER)
      # a = composeDir, b = comma-joined container names the config points at.
      if ! command -v docker >/dev/null 2>&1; then
        printf 'docker   : no docker - cannot determine\n'
      elif [ -z "$a" ] || [ ! -d "$a" ]; then
        printf 'docker   : cannot determine the compose directory (%s)\n' "${a:-path unset}"
      else
        up=$(bounded 8 docker compose --project-directory "$a" ps --services --status running)
        case $? in
          124) printf 'docker   : cannot determine (compose ps timed out after 8s)\n' ;;
          *)   if [ -z "$up" ]; then
                 printf 'docker   : (no service running under this compose)\n'
               else
                 printf 'docker   : %s\n' "$(printf '%s' "$up" | tr '\n' ' ')"
               fi ;;
        esac

        # Leftover containers - where the configured name and the running name diverge.
        # A tool finding the stack by name goes quietly empty here, and empty reads as "not up".
        live=$(bounded 8 docker ps --format '{{.Names}}')
        if [ $? -eq 124 ]; then
          printf 'container: cannot determine (docker ps timed out after 8s)\n'
        elif [ -z "$b" ]; then
          printf 'container: no container name under surfaces, cannot compare\n'
        else
          # '%s\n', not '%s'. Without a trailing newline, read drops the last line quietly and
          # one container falls out of the check while it looks like "all fine".
          printf '%s\n' "$b" | tr ',' '\n' | while IFS= read -r want; do
            [ -z "$want" ] && continue
            if printf '%s\n' "$live" | grep -qx -- "$want"; then
              printf 'container: %-24s up\n' "$want"
            else
              near=$(printf '%s\n' "$live" | awk -v w="$want" \
                     'length($0) && (index(w,$0) || index($0,w)) {printf "%s ", $0}')
              if [ -n "$near" ]; then
                printf 'container: %-24s absent - a similar name is up: %s(suspect a leftover from another compose)\n' "$want" "$near"
              else
                printf 'container: %-24s absent\n' "$want"
              fi
            fi
          done
        fi
      fi ;;
  esac
done < <(python3 - "$CFG" "$ART" <<'PY'
import json, os, re, sys

cfg = json.load(open(sys.argv[1], encoding="utf-8"))
# references/artifacts.json is the only canonical record of artifact numbering. Without it, no number is interpreted.
art = json.load(open(sys.argv[2], encoding="utf-8")) if os.path.isfile(sys.argv[2]) else {}
legacy, backend = cfg.get("legacy") or {}, cfg.get("backend") or {}
docs, e2e = cfg.get("docs") or {}, cfg.get("e2e") or {}
out = []
def line(t):        out.append(f"LINE\t{t}\t")
def probe(lbl, url): out.append(f"PROBE\t{lbl}\t{url or ''}")

# ── backend modules — whatever the config names them ───────────────────────
mods = [(n, m) for n, m in backend.items() if isinstance(m, dict) and "port" in m]
first = True
for name, mod in mods:
    head = "backend  : " if first else "           "
    first = False
    port = mod.get("port")
    if not port:
        line(f"{head}{name:<7} port unset")
    else:
        probe(f"{head}{name:<7} :{port}", f"http://localhost:{port}/actuator/health")
if first:
    line("backend  : no module configured with a port")
# A build on the default JDK dies leaving one version number. Make it visible at Phase 0.
out.append(f"JAVA\t           gradle JDK  \t{backend.get('javaHome') or ''}")

# ── legacy surfaces — whatever they are named ──────────────────────────────
surfaces = legacy.get("surfaces") or {}
first = True
for name, s in surfaces.items():
    head = "legacy   : " if first else "           "
    first = False
    probe(f"{head}{name:<7}", (s or {}).get("localBaseUrl"))
if first:
    line("legacy   : no surface configured")

# -- docker: running services, compared against the container names the config points at ----
want = sorted({(s or {}).get("container") for s in surfaces.values() if (s or {}).get("container")})
out.append(f"DOCKER\t{(legacy.get('docker') or {}).get('composeDir') or ''}\t{','.join(want)}")

# ── pages — the highest-numbered artifact is the phase that finished ──────
# Do not shrink these three lines into one dict comprehension. The bash parser for <(...)
# misreads the parentheses inside the braces as a parameter expansion and destroys the
# whole heredoc (measured: "bad substitution"). An apostrophe in a comment here breaks it
# the same way - the parser reads it as an opening quote and never finds the closing paren.
PHASE = {}
for _name, _meta in art.items():
    PHASE[_name[:2]] = [_name, _meta.get("phase")]
LAST = max([p for _, p in PHASE.values() if isinstance(p, int)] or [0])
# No fallback value here. A missing key quietly replaced by a guess produces "no directory",
# which reads as "no page has started yet" rather than "the config is wrong" - the narrow
# answer this OS exists to refuse. Name the key instead.
# (When the key IS present, its value is a fact about the layout of the backend repository,
# not a name this OS chose, so renames in this OS leave that value alone.)
root, sub = docs.get("root"), docs.get("pagesDir")
sdir = os.path.join(root, sub) if root and sub else None
if not art:
    line("page     : no references/artifacts.json - the phase cannot be determined")
elif not root:
    line("page     : docs.root is not set in workspace.json - nothing was looked up")
elif not sub:
    line("page     : docs.pagesDir is not set in workspace.json - nothing was looked up")
elif not os.path.isdir(sdir):
    line(f"page     : no directory ({sdir})")
else:
    names = sorted(n for n in os.listdir(sdir) if os.path.isdir(os.path.join(sdir, n)))
    if not names:
        line("page     : (none)")
    for i, n in enumerate(names):
        nums = sorted(m.group(1) for f in os.listdir(os.path.join(sdir, n))
                      if (m := re.match(r"(\d\d)-", f)))
        head = "page     : " if i == 0 else "           "
        if not nums:
            state = "no artifact       · next Phase 1"
        elif nums[-1] not in PHASE:
            state = f"{nums[-1]}-* unknown number · compare against artifacts.json"
        else:
            fname, ph = PHASE[nums[-1]]
            nxt = "done" if ph >= LAST else f"next Phase {ph + 1}"
            state = f"{fname:<16} Phase {ph} done · {nxt}"
        line(f"{head}{n:<24} {state}")

line(f"e2e      : {e2e.get('root') or 'path unset'}")
print("\n".join(out))
PY
)
