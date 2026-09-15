#!/usr/bin/env bash
# Environment status for the legacy-slice orchestrator.
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
  echo "workspace.json 없음 — .claude/config/workspace.example.json 을 복사해 채우세요"
  exit 0
fi

# curl prints 000 when it cannot connect; report that as DOWN rather than a status code.
probe() {
  local code
  [ -z "$1" ] && { echo "주소 없음"; return; }
  code=$(curl -s -o /dev/null -m 2 -w "%{http_code}" "$1" 2>/dev/null)
  if [ -z "$code" ] || [ "$code" = "000" ]; then echo "DOWN"; else echo "$code"; fi
}

# docker hangs when the daemon is wedged, and this block is embedded in SKILL.md with `!`,
# so a hang stops the skill from loading at all. Bound every docker call and, on timeout,
# say "확인 불가 (시간 초과)" rather than returning an empty list that reads as "nothing is up".
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
        printf '%s javaHome 미설정 — gradle 이 기본 JDK 로 돌아 실패할 수 있음\n' "$a"
      elif [ ! -x "$b/bin/java" ]; then
        printf '%s javaHome 경로에 JDK 없음\n' "$a"
      else
        printf '%s%s\n' "$a" "$("$b/bin/java" -version 2>&1 | head -1 | sed 's/.*version //; s/"//g')"
      fi ;;
    DOCKER)
      # a = composeDir, b = comma-joined container names the config points at.
      if ! command -v docker >/dev/null 2>&1; then
        printf 'docker   : docker 없음 — 확인 불가\n'
      elif [ -z "$a" ] || [ ! -d "$a" ]; then
        printf 'docker   : compose 디렉토리 확인 불가 (%s)\n' "${a:-경로 미설정}"
      else
        up=$(bounded 8 docker compose --project-directory "$a" ps --services --status running)
        case $? in
          124) printf 'docker   : 확인 불가 (compose ps 시간 초과 8초)\n' ;;
          *)   if [ -z "$up" ]; then
                 printf 'docker   : (이 compose 로 기동 중인 서비스 없음)\n'
               else
                 printf 'docker   : %s\n' "$(printf '%s' "$up" | tr '\n' ' ')"
               fi ;;
        esac

        # 잔여 컨테이너 — 설정이 지목한 이름과 실제 떠 있는 이름이 갈리는 경우.
        # 이름으로 스택을 찾는 도구는 여기서 조용히 빈손이 되고, 빈손은 "안 떠 있다"로 읽힌다.
        live=$(bounded 8 docker ps --format '{{.Names}}')
        if [ $? -eq 124 ]; then
          printf '컨테이너 : 확인 불가 (docker ps 시간 초과 8초)\n'
        elif [ -z "$b" ]; then
          printf '컨테이너 : surfaces 에 container 이름이 없어 대조 불가\n'
        else
          # '%s\n' 이지 '%s' 가 아니다. 마지막 줄에 개행이 없으면 read 가 그 줄을 조용히
          # 버리고, 마지막 컨테이너 하나가 점검에서 빠진 채로 "이상 없음"처럼 보인다.
          printf '%s\n' "$b" | tr ',' '\n' | while IFS= read -r want; do
            [ -z "$want" ] && continue
            if printf '%s\n' "$live" | grep -qx -- "$want"; then
              printf '컨테이너 : %-24s 떠 있음\n' "$want"
            else
              near=$(printf '%s\n' "$live" | awk -v w="$want" \
                     'length($0) && (index(w,$0) || index($0,w)) {printf "%s ", $0}')
              if [ -n "$near" ]; then
                printf '컨테이너 : %-24s 없음 — 비슷한 이름이 떠 있음: %s(다른 compose 의 잔여물 의심)\n' "$want" "$near"
              else
                printf '컨테이너 : %-24s 없음\n' "$want"
              fi
            fi
          done
        fi
      fi ;;
  esac
done < <(python3 - "$CFG" "$ART" <<'PY'
import json, os, re, sys

cfg = json.load(open(sys.argv[1], encoding="utf-8"))
# 산출물 번호의 정본은 references/artifacts.json 하나뿐이다. 없으면 번호를 해석하지 않는다.
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
        line(f"{head}{name:<7} 포트 미설정")
    else:
        probe(f"{head}{name:<7} :{port}", f"http://localhost:{port}/actuator/health")
if first:
    line("backend  : 포트를 가진 모듈 설정 없음")
# 빌드가 기본 JDK 로 돌면 버전 번호 한 줄만 남기고 죽는다. Phase 0 에서 보이게 한다.
out.append(f"JAVA\t           gradle JDK  \t{backend.get('javaHome') or ''}")

# ── legacy surfaces — whatever they are named ──────────────────────────────
surfaces = legacy.get("surfaces") or {}
first = True
for name, s in surfaces.items():
    head = "legacy   : " if first else "           "
    first = False
    probe(f"{head}{name:<7}", (s or {}).get("localBaseUrl"))
if first:
    line("legacy   : 표면 설정 없음")

# ── docker — 기동 중인 서비스 + 설정이 지목한 컨테이너 이름 대조 ──────────
want = sorted({(s or {}).get("container") for s in surfaces.values() if (s or {}).get("container")})
out.append(f"DOCKER\t{(legacy.get('docker') or {}).get('composeDir') or ''}\t{','.join(want)}")

# ── slices — the highest-numbered artifact is the phase that finished ──────
# 이 세 줄을 dict comprehension 한 줄로 줄이지 마라. bash 의 <(...) 파서가 중괄호 안의
# 괄호를 파라미터 확장으로 잘못 읽어 히어독을 통째로 망가뜨린다 (실측: "bad substitution").
PHASE = {}
for _name, _meta in art.items():
    PHASE[_name[:2]] = [_name, _meta.get("phase")]
LAST = max([p for _, p in PHASE.values() if isinstance(p, int)] or [0])
root, sub = docs.get("root"), docs.get("slicesDir") or "slices"
sdir = os.path.join(root, sub) if root else None
if not art:
    line("슬라이스 : references/artifacts.json 없음 — 단계 판정 불가")
elif not sdir or not os.path.isdir(sdir):
    line(f"슬라이스 : 디렉토리 없음 ({sdir or '경로 미설정'})")
else:
    names = sorted(n for n in os.listdir(sdir) if os.path.isdir(os.path.join(sdir, n)))
    if not names:
        line("슬라이스 : (없음)")
    for i, n in enumerate(names):
        nums = sorted(m.group(1) for f in os.listdir(os.path.join(sdir, n))
                      if (m := re.match(r"(\d\d)-", f)))
        head = "슬라이스 : " if i == 0 else "           "
        if not nums:
            state = "산출물 없음      · 다음 Phase 1"
        elif nums[-1] not in PHASE:
            state = f"{nums[-1]}-* 알 수 없는 번호 · artifacts.json 과 대조 필요"
        else:
            fname, ph = PHASE[nums[-1]]
            nxt = "완료" if ph >= LAST else f"다음 Phase {ph + 1}"
            state = f"{fname:<16} Phase {ph} 끝 · {nxt}"
        line(f"{head}{n:<24} {state}")

line(f"e2e      : {e2e.get('root') or '경로 미설정'}")
print("\n".join(out))
PY
)
