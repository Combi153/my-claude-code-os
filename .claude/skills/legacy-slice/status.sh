#!/usr/bin/env bash
# Environment status for the legacy-slice orchestrator.
# Reads .claude/config/workspace.json and probes each moving part, so Phase 0 does not
# have to guess what is up. Every probe is read-only and fails soft.
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
CFG="$ROOT/.claude/config/workspace.json"

if [ ! -f "$CFG" ]; then
  echo "workspace.json 없음 — .claude/config/workspace.example.json 을 복사해 채우세요"
  exit 0
fi

read -r PROXY FIXITY HELP ADMIN COMPOSE BACKEND DOCS E2E <<<"$(python3 - "$CFG" <<'PY'
import json, sys
c = json.load(open(sys.argv[1]))
b, l, d, e = c.get("backend", {}), c.get("legacy", {}), c.get("docs", {}), c.get("e2e", {})
s = l.get("surfaces", {})
def g(d_, *ks, default="-"):
    for k in ks:
        d_ = (d_ or {}).get(k) if isinstance(d_, dict) else None
    return d_ or default
print(
    g(b, "proxy", "port"), g(b, "fixity", "port"),
    g(s, "help", "localBaseUrl"), g(s, "admin", "localBaseUrl"),
    g(l, "docker", "composeDir"), b.get("root", "-"), d.get("root", "-"), e.get("root", "-"),
)
PY
)"

# curl prints 000 when it cannot connect; report that as DOWN rather than a status code.
probe() {
  local code
  code=$(curl -s -o /dev/null -m 2 -w "%{http_code}" "$1" 2>/dev/null)
  [ -z "$code" ] || [ "$code" = "000" ] && { echo "DOWN"; return; }
  echo "$code"
}

echo "backend  : proxy :$PROXY = $(probe "http://localhost:$PROXY/actuator/health")  |  fixity :$FIXITY = $(probe "http://localhost:$FIXITY/actuator/health")"
echo "legacy   : help $HELP = $(probe "$HELP")  |  admin $ADMIN = $(probe "$ADMIN")"

if command -v docker >/dev/null 2>&1 && [ -d "$COMPOSE" ]; then
  up=$(cd "$COMPOSE" && docker compose ps --services --status running 2>/dev/null | tr '\n' ' ')
  echo "docker   : ${up:-(기동 중인 서비스 없음)}"
else
  echo "docker   : compose 디렉토리 확인 불가 ($COMPOSE)"
fi

if [ -d "$DOCS" ]; then
  echo "슬라이스 : $(ls "$DOCS/slices" 2>/dev/null | tr '\n' ' ' || echo '(없음)')"
else
  echo "슬라이스 : docs 루트 없음 ($DOCS)"
fi
echo "e2e      : $([ -d "$E2E" ] && echo "$E2E" || echo "경로 확인 불가 ($E2E)")"
