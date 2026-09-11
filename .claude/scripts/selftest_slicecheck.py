#!/usr/bin/env python3
"""slicecheck 케이스. 합성 픽스처로만 돈다 — 회사 트리도, 도커도, 스택도 없이.

    python3 selftest_slicecheck.py [slicecheck 경로]

픽스처 넷이 이 파일의 전부다.

1. **가짜 표면** — 스레드 하나의 HTTP 서버가 레거시 페이지와 토글 되읽기 페이지를
   서비스하고, 요청마다 이중 실행 로그에 JSONL 한 줄을 붙인다. 헬퍼가 하는 일이다.
2. **가짜 `docker`** — PATH 에 놓인 스크립트. `up -d --force-recreate` 가 compose
   env 파일을 "배달된 환경" 파일로 **복사**한다. 이것이 이 픽스처의 핵심이다:
   값을 쓰는 것과 그 값이 PHP 에 도달하는 것을 두 개의 사실로 갈라 놓기 때문에,
   배달을 끊으면 `slicecheck` 가 캡처를 거부하는지 실제로 밟을 수 있다.
3. **합성 설정** — `--config` 로 준다. 실제 `workspace.json` 을 읽지 않는다.
4. **헬퍼 두 판** — 템플릿 그대로의 것과 `NOISE_ENV`·`POISON_ENV` 를 지운 것.
   두 번째가 "지원하지 않는 것을 조용히 건너뛰지 않는다"를 밟는다.

**여기서 검사하는 것은 판정과 종료 코드다.** 특히 3(검사할 수 없었다)이 0 과 섞이지
않는지, 그리고 실패 경로가 실제로 밟히는지 — 상한 정지, 되읽기 불일치, 설정 키 부재,
독 주입 빨간불, 커버리지 건너뜀 기록, 깨진 `state.json`.
"""
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "slicecheck")
TEMPLATE = os.path.join(os.path.dirname(HERE), "templates", "MigrationExperiment.php")
if not os.path.isfile(TOOL):
    sys.exit(f"사용법: selftest_slicecheck.py [slicecheck 경로]  (찾은 곳: {TOOL})")

BASE = tempfile.mkdtemp(prefix="slicecheck-selftest-")
PHP = shutil.which("php")
results, skipped = [], []


def check(name, ok, detail="", secs=None):
    results.append((name, ok, detail))
    t = f"  {secs:5.1f}s" if secs is not None else "        "
    print(f"  {'통과' if ok else 'FAIL'}{t}  {name}" + (f"   {detail}" if detail else ""))


def skip(name, why):
    skipped.append((name, why))
    print(f"  건너뜀       {name}   ({why})")


# ------------------------------------------------------------ 가짜 표면

CONTAINER = "surface-web"            # 픽스처가 지어낸 이름. 설정에서만 나온다.
DELIVERED = os.path.join(BASE, "delivered.env")
FLAGS = os.path.join(BASE, "flags")
LOG = os.path.join(BASE, "dual.jsonl")
MODE_VALUES = {"php": "legacy", "dual": "dual", "spring": "migrated"}


def flag(name):
    return os.path.exists(os.path.join(FLAGS, name))


def set_flag(name, on=True):
    os.makedirs(FLAGS, exist_ok=True)
    p = os.path.join(FLAGS, name)
    if on:
        open(p, "w").close()
    elif os.path.exists(p):
        os.remove(p)


def delivered():
    """컨테이너 안에서 `getenv()` 가 보는 값. 배달된 것만 보인다."""
    out = {}
    try:
        with open(DELIVERED, encoding="utf-8") as fh:
            for line in fh:
                if "=" in line and not line.strip().startswith("#"):
                    k, _, v = line.strip().partition("=")
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def append_log(rec):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


class App(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_GET(self):
        env = delivered()
        raw = env.get("X_BACKEND_DEMO_PAGE", "")
        mode = MODE_VALUES.get(raw, "legacy")
        noise = env.get("MIGRATION_EXPERIMENT_NOISE") or ""
        poison = env.get("MIGRATION_EXPERIMENT_POISON") or ""
        path = self.path.split("?")[0]

        if path == "/__toggle.php":
            # 되읽기 페이지는 모드 토큰 하나만 찍는다. 머리글도 설명도 없다.
            return self.send(raw.encode("ascii") or b"php")
        if path == "/":
            return self.send(b"ok")
        if path != "/page.php":
            return self.send(b"not found", 404)

        if flag("coverage_on"):
            # Xdebug 가 실행 줄을 떨어뜨리는 것을 흉내낸다. 내용은 케이스가 정한다.
            with open(os.path.join(FLAGS, "coverage_content"), encoding="utf-8") as fh:
                body = fh.read()
            with open(COVERAGE, "w", encoding="utf-8") as fh:
                fh.write(body)

        ts = datetime.datetime.now().astimezone().isoformat()
        if flag("nolog"):
            # 로그 경로가 컨테이너 안에 없는 상태. 화면은 정상이고 파일만 비어 있다.
            pass
        elif noise:
            # 레거시 대 레거시. 같은 코드를 두 번 돌려도 움직이는 키가 잡음 바닥이다.
            append_log({"ts": ts, "experiment": "demo-page", "mode": "dual",
                        "equal": False, "diff_keys": ["rendered_at"],
                        "ignored_keys": [], "truncated": False,
                        "context": {"noise": True},
                        "control": {"rendered_at": 1}, "candidate": {"rendered_at": 2}})
        elif mode == "dual":
            bad = flag("mismatch")
            append_log({"ts": ts, "experiment": "demo-page", "mode": "dual",
                        "equal": not bad,
                        "diff_keys": ["items[0].title"] if bad else [],
                        "ignored_keys": [], "truncated": False,
                        **({"control": {"items": [{"title": "a"}]},
                            "candidate": {"items": [{"title": "b"}]}} if bad else {})})
        elif mode == "migrated" and poison:
            append_log({"ts": ts, "experiment": "demo-page", "mode": "migrated",
                        "poison": poison, "equal": True, "diff_keys": [],
                        "ignored_keys": [], "truncated": False})

        value = "42"
        if mode == "migrated" and poison and flag("leaky"):
            # 화면이 아직 레거시 반환값을 쓰고 있다 — 독이 그대로 렌더된다.
            value = "POISON:" + poison
        self.send(f"<html><body><p>total {value}</p></body></html>".encode())

    def send(self, body, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


PORT = free_port()
BFF_PORT = free_port()
server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), App)
threading.Thread(target=server.serve_forever, daemon=True).start()
# 단계 1 의 BFF 포트 도달 검사가 볼 대상. 듣기만 한다.
bff = socket.socket()
bff.bind(("127.0.0.1", BFF_PORT))
bff.listen(8)


# ------------------------------------------------------------ 가짜 docker

BIN = os.path.join(BASE, "bin")
os.makedirs(BIN, exist_ok=True)
COMPOSE_DIR = os.path.join(BASE, "compose")
ENV_FILE = os.path.join(COMPOSE_DIR, ".env")
os.makedirs(COMPOSE_DIR, exist_ok=True)
with open(ENV_FILE, "w", encoding="utf-8") as fh:
    fh.write("# 다른 서비스의 값도 이 파일에 산다. 한 줄도 건드리면 안 된다.\n"
             "OTHER_SERVICE_FLAG=keep-me\n")

FAKE_DOCKER = f'''#!/usr/bin/env python3
"""compose 흉내. `up` 이 env 파일을 배달된 환경으로 복사한다 — 그것이 이 픽스처가
가르는 두 사실이다: 값을 쓴 것과 그 값이 PHP 에 도달한 것."""
import os, shutil, sys
FLAGS, DELIVERED = {FLAGS!r}, {DELIVERED!r}
args = sys.argv[1:]
def has(name): return os.path.exists(os.path.join(FLAGS, name))
env_file = None
for i, a in enumerate(args):
    if a == "--env-file" and i + 1 < len(args):
        env_file = args[i + 1]
if "ps" in args:
    print("{CONTAINER}\\trunning" if not has("container_gone") else "other\\trunning")
    sys.exit(0)
if "up" in args:
    if has("nodeliver"):          # 컨테이너를 다시 만들지 못한 상태
        sys.exit(0)
    shutil.copyfile(env_file, DELIVERED)
    sys.exit(0)
if "exec" in args:
    mods = ["Core", "json", "pcre"] + (["xdebug"] if has("xdebug") else [])
    print("[PHP Modules]"); print("\\n".join(mods))
    sys.exit(0)
sys.exit(0)
'''
with open(os.path.join(BIN, "docker"), "w", encoding="utf-8") as fh:
    fh.write(FAKE_DOCKER)
os.chmod(os.path.join(BIN, "docker"), 0o755)


# ------------------------------------------------------------ 합성 설정

TREE = os.path.join(BASE, "tree")
HELPER_DIR = os.path.join(TREE, "helper")
NOHELPER_DIR = os.path.join(TREE, "helper-old")
SCHEMA_DIR = os.path.join(BASE, "backend", "schema")
for d in (HELPER_DIR, NOHELPER_DIR, SCHEMA_DIR, os.path.join(TREE, "marker")):
    os.makedirs(d, exist_ok=True)
with open(os.path.join(SCHEMA_DIR, "demo.graphqls"), "w", encoding="utf-8") as fh:
    fh.write("type Query { demo: String }\n")

if os.path.isfile(TEMPLATE):
    shutil.copyfile(TEMPLATE, os.path.join(HELPER_DIR, "MigrationExperiment.php"))
    body = open(TEMPLATE, encoding="utf-8").read()
    old = (body.replace("const NOISE_ENV", "const UNRELATED_A")
               .replace("const POISON_ENV", "const UNRELATED_B"))
    with open(os.path.join(NOHELPER_DIR, "MigrationExperiment.php"), "w",
              encoding="utf-8") as fh:
        fh.write(old)

SEAM_PHP = os.path.join(TREE, "seam.php")
with open(SEAM_PHP, "w", encoding="utf-8") as fh:
    fh.write("<?php\nfunction demo_body($p)\n{\n    return array('total' => 42);\n}\n")

COVERAGE = os.path.join(BASE, "coverage.json")
PROJ = os.path.join(BASE, "proj")
os.makedirs(os.path.join(PROJ, ".claude", "config"), exist_ok=True)


def write_config(name, **over):
    cfg = {
        "legacy": {
            "root": BASE, "treeRoot": TREE, "treeMarker": "marker",
            "services": {"helper": "helper"}, "sharedLibrary": "helper",
            "primaryService": "helper",
            "tooling": {"phpBinary": PHP or "php"},
            "seam": {"pinsFile": "pins.json"},
            "snapshot": {"normalize": [], "errorMarker": "__NEVER_AN_ERROR__",
                         "timeoutSeconds": 10},
            "dualRun": {"logPath": LOG, "logEnvVar": "MIGRATION_EXPERIMENT_LOG",
                        "readbackPath": "/__toggle.php",
                        "ignoreFile": "ignore.json",
                        "noiseEnvVar": "MIGRATION_EXPERIMENT_NOISE",
                        "poisonEnvVar": "MIGRATION_EXPERIMENT_POISON",
                        "coveragePath": COVERAGE},
            "surfaces": {"demo": {
                "docroot": TREE, "localBaseUrl": f"http://127.0.0.1:{PORT}",
                "container": CONTAINER, "daoPaths": [],
                "loggedOutMarker": "__NEVER_LOGGED_OUT__", "charset": "utf-8"}},
            "docker": {"composeDir": COMPOSE_DIR, "envFile": ENV_FILE},
            "switch": {"envVarPattern": "X_BACKEND_{SLICE}",
                       "values": {"legacy": "php", "dual": "dual",
                                  "migrated": "spring"},
                       "helperPath": HELPER_DIR},
        },
        "backend": {"root": BASE, "graphqlSchemaDir": SCHEMA_DIR,
                    "proxy": {"module": ":apps:x", "port": BFF_PORT,
                              "packageBase": "x"}},
        "docs": {"root": BASE, "slicesDir": "slices", "domainDir": "domain"},
    }
    for dotted_key, val in over.items():
        key = dotted_key.replace("__", ".")
        cur, parts = cfg, key.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        if val is None:
            cur.pop(parts[-1], None)
        else:
            cur[parts[-1]] = val
    path = os.path.join(PROJ, ".claude", "config", name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=1)
    return path


CONFIG = write_config("workspace.json")
NO_COMPOSE = write_config("no-compose.json", legacy__docker__envFile=None)
NO_READBACK = write_config("no-readback.json",
                           legacy__dualRun__readbackPath="<relative path>")
OLD_HELPER = write_config("old-helper.json",
                          legacy__switch__helperPath=NOHELPER_DIR)
NO_COVERAGE = write_config("no-coverage.json",
                           legacy__dualRun__coveragePath=None)


# ------------------------------------------------------------ 실행 도우미

ENVIRON = dict(os.environ)
ENVIRON["PATH"] = BIN + os.pathsep + ENVIRON.get("PATH", "")
ENVIRON.pop("CLAUDE_PROJECT_DIR", None)


def run(args, timeout=180):
    t0 = time.time()
    p = subprocess.run([sys.executable, TOOL] + args, capture_output=True,
                       text=True, timeout=timeout, cwd=BASE, env=ENVIRON)
    return p, time.time() - t0


def htmlsnap(args, timeout=120):
    return subprocess.run([sys.executable, os.path.join(HERE, "htmlsnap")] + args,
                          capture_output=True, text=True, timeout=timeout,
                          cwd=BASE, env=ENVIRON)


def deliver(mode, **extra):
    """토글을 직접 배달한다 — slicecheck 없이 픽스처를 어떤 모드로든 놓기 위해."""
    value = {"legacy": "php", "dual": "dual", "migrated": "spring"}[mode]
    lines = [f"X_BACKEND_DEMO_PAGE={value}"]
    lines += [f"{k}={v}" for k, v in extra.items()]
    with open(DELIVERED, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


SLICE_ID = "demo_page"          # 토글 변수 이름이 이것에서 나온다: X_BACKEND_DEMO_PAGE


def new_slice(name, corpus=True, init=True, caps="L2=9,L3=9"):
    """슬라이스 디렉터리 하나. **id 는 전부 같고 디렉터리만 다르다.**

    id 가 토글 환경변수 이름을 정하므로(`X_BACKEND_{SLICE}`), 픽스처마다 id 를
    다르게 두면 가짜 앱이 읽는 변수와 slicecheck 이 쓰는 변수가 갈린다 — 그리고
    그 갈림은 "토글이 PHP 에 도달하지 않았다"와 정확히 같은 모양으로 도착한다.
    픽스처가 도구의 실패를 흉내내는 것은 배달을 끊는 `nodeliver` 플래그로만 한다.
    """
    d = os.path.join(BASE, "slices", name)
    os.makedirs(d, exist_ok=True)
    if corpus:
        with open(os.path.join(d, "corpus.json"), "w", encoding="utf-8") as fh:
            json.dump({"surface": "demo", "entries": [
                {"id": "page", "path": "/page.php", "params": {"id": "1"},
                 "mode": "full", "rules": ["R-07"]}]}, fh)
    if init:
        p, _ = run([d, "--init", "--slice", SLICE_ID, "--cap", caps])
        if p.returncode != 0:
            sys.exit(f"--init 실패: {p.stdout}{p.stderr}")
    return d


def state_of(d):
    with open(os.path.join(d, "state.json"), encoding="utf-8") as fh:
        return json.load(fh)


def baseline(d):
    """Phase 1 이 남겨야 하는 legacy 골든 마스터."""
    deliver("legacy")
    r = htmlsnap(["capture", "--corpus", os.path.join(d, "corpus.json"),
                  "--out", os.path.join(d, "captures", "legacy"),
                  "--toggle-expect", "legacy", "--config", CONFIG])
    if r.returncode != 0:
        sys.exit(f"기준선 캡처 실패: {r.stdout}{r.stderr}")


def make_pins(d):
    """`phpseam pin` 으로 본문 해시를 고정한다. php 가 없으면 None."""
    if not PHP:
        return None
    path = os.path.join(d, "pins.json")
    r = subprocess.run([sys.executable, os.path.join(HERE, "phpseam"), "pin",
                        SEAM_PHP, "demo_body", "--pins", path,
                        "--config", CONFIG], capture_output=True, text=True,
                       timeout=180, cwd=BASE, env=ENVIRON)
    return path if r.returncode == 0 and os.path.isfile(path) else None


print(f"# 도구 {TOOL}   표면 127.0.0.1:{PORT}   php {'있음' if PHP else '없음'}")

# ------------------------------------------------------------ 1. 사용법·단계 해석
print("\n### 1. 사용법과 단계 해석")

p, _ = run([])
check("인자가 없으면 exit 2", p.returncode == 2, f"exit={p.returncode}")

d = new_slice("stages")
p, _ = run([d, "--stage", "9", "--config", CONFIG])
check("모르는 단계는 exit 2 이고 있는 단계를 나열한다",
      p.returncode == 2 and "1~7" in p.stderr, f"exit={p.returncode}")

p, _ = run([d, "--stage", "1..7", "--dry-run", "--config", CONFIG])
listed = [l for l in p.stdout.splitlines() if l.strip().startswith("단계")]
check("`1..7` 범위가 일곱 단계로 펼쳐진다",
      p.returncode == 0 and len(listed) == 7, f"exit={p.returncode} · {len(listed)}줄")

p, _ = run([d, "--stage", "3,4,7", "--dry-run", "--config", CONFIG])
listed = [l.split()[1] for l in p.stdout.splitlines() if l.strip().startswith("단계")]
check("`3,4,7` 목록이 적은 순서 그대로 온다",
      listed == ["3", "4", "7"], f"{listed}")

p, _ = run([d, "--stage", "1", "--init", "--slice", "x", "--config", CONFIG])
check("이미 있는 state.json 을 --init 이 덮어쓰지 않는다 (exit 3)",
      p.returncode == 3 and "덮어쓰지 않는다" in p.stderr, f"exit={p.returncode}")

# ------------------------------------------------------------ 2. state.json
print("\n### 2. state.json — 없거나 깨졌을 때")

bare = os.path.join(BASE, "slices", "bare")
os.makedirs(bare, exist_ok=True)
p, _ = run([bare, "--stage", "7", "--config", CONFIG])
check("state.json 이 없으면 exit 3 이고 --init 을 가리킨다",
      p.returncode == 3 and "--init" in p.stderr, f"exit={p.returncode}")
check("없는 state.json 을 조용히 만들지 않는다",
      not os.path.exists(os.path.join(bare, "state.json")))

broken = new_slice("broken")
with open(os.path.join(broken, "state.json"), "w", encoding="utf-8") as fh:
    fh.write("{ this is not json")
p, _ = run([broken, "--stage", "7", "--config", CONFIG])
check("깨진 state.json 은 exit 3 이고 덮어쓰지 않는다",
      p.returncode == 3 and "읽을 수 없다" in p.stderr, f"exit={p.returncode}")
check("깨진 내용이 그대로 남아 있다",
      open(os.path.join(broken, "state.json")).read().startswith("{ this"))

half = new_slice("half")
doc = state_of(half)
del doc["loops"]
with open(os.path.join(half, "state.json"), "w", encoding="utf-8") as fh:
    json.dump(doc, fh)
p, _ = run([half, "--stage", "7", "--config", CONFIG])
check("계약과 형태가 다른 state.json 도 exit 3 (loops 없음)",
      p.returncode == 3 and "loops" in p.stderr, f"exit={p.returncode}")

fresh = state_of(new_slice("fresh"))
check("갓 만든 게이지는 0 이 아니라 null 이다 (측정하지 않은 것을 초록으로 적지 않는다)",
      all(fresh["gauges"][g] is None for g in
          ("unexpected", "golden_diff", "poison", "legacy_lines")),
      str(fresh["gauges"]))

# ------------------------------------------------------------ 3. 설정 키 부재
print("\n### 3. 설정 키가 없으면 어느 키인지 말하고 exit 3")

d = new_slice("cfg")
p, _ = run([d, "--stage", "7", "--config", NO_COMPOSE])
check("compose env 파일 키가 없으면 exit 3 + 키 이름",
      p.returncode == 3 and "legacy.docker.envFile" in p.stderr,
      f"exit={p.returncode} · {p.stderr.strip()[:70]}")

p, _ = run([d, "--stage", "7", "--config", os.path.join(BASE, "nope.json")])
check("설정 파일 자체가 없으면 exit 3", p.returncode == 3, f"exit={p.returncode}")

d2 = new_slice("cfg2")
baseline(d2)
p, _ = run([d2, "--stage", "1", "--config", NO_READBACK])
check("되읽기 경로가 골격의 자리표시자면 단계 1 이 exit 3",
      p.returncode == 3 and "되읽기 설정 X" in p.stdout,
      f"exit={p.returncode}")

# ------------------------------------------------------------ 4. 단계 1 환경
print("\n### 4. 단계 1 — 환경 넷")

d = new_slice("env")
deliver("legacy")
p, secs = run([d, "--stage", "1", "--config", CONFIG])
check("넷이 다 통과하면 exit 0", p.returncode == 0 and "통과" in p.stdout,
      p.stdout.strip().splitlines()[-2:][0] if p.stdout.strip() else "", secs=secs)

set_flag("container_gone")
p, _ = run([d, "--stage", "1", "--config", CONFIG])
set_flag("container_gone", False)
check("compose 프로젝트에 그 컨테이너가 없으면 exit 3 (0 이 아니다)",
      p.returncode == 3 and "컨테이너 대조 X" in p.stdout, f"exit={p.returncode}")

# ------------------------------------------------------------ 5. 토글 되읽기
print("\n### 5. 토글 — 되읽은 값이 다르면 캡처하지 않는다")

d = new_slice("readback")
baseline(d)
deliver("legacy")
set_flag("nodeliver")
p, secs = run([d, "--stage", "3", "--config", CONFIG])
set_flag("nodeliver", False)
check("env 에 쓴 값이 PHP 에 도달하지 않으면 exit 3",
      p.returncode == 3 and "되읽기" in p.stderr, f"exit={p.returncode}", secs=secs)
check("되읽기 불일치에서는 캡처 디렉터리를 만들지 않는다",
      not os.path.isdir(os.path.join(d, "captures", "dual")))
check("그래도 회차는 세어 두었다 (돌려 보려 한 사실은 남는다)",
      state_of(d)["loops"]["L2"]["n"] == 1, str(state_of(d)["loops"]["L2"]))

check("다른 서비스의 env 줄을 건드리지 않았다",
      "OTHER_SERVICE_FLAG=keep-me" in open(ENV_FILE).read())

# ------------------------------------------------------------ 6. 단계 2 잡음
print("\n### 6. 단계 2 — 잡음 바닥과 씨앗")

d = new_slice("noise")
deliver("legacy")
p, _ = run([d, "--stage", "2", "--config", OLD_HELPER])
check("헬퍼가 잡음 모드를 지원하지 않으면 exit 3 이고 건너뛰지 않는다",
      p.returncode == 3 and "지원하지 않는다" in p.stdout,
      f"exit={p.returncode}")

ign = os.path.join(d, "ignore.json")
with open(ign, "w", encoding="utf-8") as fh:
    json.dump({"rules": [{"experiment": "demo-page", "keys": ["total"],
                          "ledger": "R-17", "reason": "의도수정"}]}, fh)
open(LOG, "w").close()
p, secs = run([d, "--stage", "2", "--config", CONFIG])
rules = json.load(open(ign))["rules"]
seeds = [r for r in rules if r.get("origin") == "noise"]
check("잡음 바닥이 돌고 씨앗이 생기면 exit 0",
      p.returncode == 0, f"exit={p.returncode} · {p.stdout.strip()[-120:]}", secs=secs)
check("씨앗은 `origin: \"noise\"` 로 출처가 구별된다",
      len(seeds) == 1 and seeds[0]["keys"] == ["rendered_at"], str(seeds))
check("씨앗에는 원장 행이 없다 (사람이 승인한 행을 가리키지 않기 때문)",
      seeds and seeds[0]["ledger"] is None)
check("사람이 승인한 규칙은 그대로 남는다",
      any(r.get("ledger") == "R-17" for r in rules), f"{len(rules)}개")
check("단계 2 는 토글을 legacy 에 둔다", state_of(d)["toggle"] == "legacy",
      str(state_of(d)["toggle"]))

# ------------------------------------------------------------ 7. 단계 3 dual
print("\n### 7. 단계 3 — 예상 밖 불일치")

d = new_slice("dual")
baseline(d)
open(LOG, "w").close()
p, secs = run([d, "--stage", "3", "--config", CONFIG])
check("예상 밖 0 이면 exit 0 이고 게이지가 0 으로 적힌다",
      p.returncode == 0 and state_of(d)["gauges"]["unexpected"] == 0,
      f"exit={p.returncode} · {state_of(d)['gauges']}", secs=secs)

d = new_slice("dual-bad")
baseline(d)
open(LOG, "w").close()
set_flag("mismatch")
p, _ = run([d, "--stage", "3", "--config", CONFIG])
set_flag("mismatch", False)
check("예상 밖 불일치가 있으면 exit 1 (3 이 아니다 — 검사는 돌았다)",
      p.returncode == 1 and state_of(d)["gauges"]["unexpected"] >= 1,
      f"exit={p.returncode} · {state_of(d)['gauges']}")

open(LOG, "w").close()
set_flag("nolog")
p, _ = run([d, "--stage", "3", "--config", CONFIG])
set_flag("nolog", False)
check("로그가 비면 exit 3 — '불일치 없음'으로 읽지 않는다",
      p.returncode == 3 and "불일치" not in p.stdout.split("단계 3")[-1][:40],
      f"exit={p.returncode}")

# ------------------------------------------------------------ 8. 단계 4 migrated
print("\n### 8. 단계 4 — migrated 골든")

d = new_slice("mig")
p, _ = run([d, "--stage", "4", "--config", CONFIG])
check("기준선 캡처가 없으면 exit 3 (비교할 대상이 없다)",
      p.returncode == 3 and "기준선" in p.stdout, f"exit={p.returncode}")

baseline(d)
open(LOG, "w").close()
p, secs = run([d, "--stage", "4", "--config", CONFIG])
check("migrated 화면이 기준선과 같으면 exit 0",
      p.returncode == 0 and state_of(d)["gauges"]["golden_diff"] == 0,
      f"exit={p.returncode} · {state_of(d)['gauges']}", secs=secs)

# ------------------------------------------------------------ 9. 단계 5 독 주입
print("\n### 9. 단계 5 — 독 주입 (동일해야 통과)")

d = new_slice("poison")
baseline(d)
open(LOG, "w").close()
p, _ = run([d, "--stage", "4", "--config", CONFIG])
pins = make_pins(d)

p, _ = run([d, "--stage", "5", "--config", OLD_HELPER])
check("헬퍼가 독 주입을 지원하지 않으면 exit 3",
      p.returncode == 3 and "지원하지 않는다" in p.stdout, f"exit={p.returncode}")

set_flag("leaky")
p, secs = run([d, "--stage", "5", "--config", CONFIG])
set_flag("leaky", False)
check("독이 화면에 나타나면(레거시 값이 렌더된다) 실패한다",
      p.returncode == 1 and state_of(d)["gauges"]["poison"] == "fail",
      f"exit={p.returncode} · {state_of(d)['gauges']['poison']}", secs=secs)
check("실패 사유를 '레거시에서 온다'로 말한다",
      "레거시에서" in p.stderr, p.stderr.strip()[-90:])

if pins:
    p, secs = run([d, "--stage", "5", "--config", CONFIG])
    check("독을 넣어도 화면이 동일하면 통과하고, 본문 해시도 그대로다",
          p.returncode == 0 and state_of(d)["gauges"]["poison"] == "pass"
          and "본문 해시 그대로" in p.stdout,
          f"exit={p.returncode} · {p.stdout.strip().splitlines()[-2][-60:]}", secs=secs)
    with open(SEAM_PHP, "w", encoding="utf-8") as fh:   # 본문 안을 고친다
        fh.write("<?php\nfunction demo_body($p)\n{\n"
                 "    return array('total' => 43);\n}\n")
    p, _ = run([d, "--stage", "5", "--config", CONFIG])
    check("본문 해시가 움직이면 독 주입이 통과하지 못한다",
          p.returncode != 0, f"exit={p.returncode}")
else:
    skip("독 주입 통과 · 본문 해시 대조", "php 가 없어 phpseam pin 을 걸 수 없다")

check("독 봉투는 단계 안에서 다시 꺼진다",
      "MIGRATION_EXPERIMENT_POISON" not in open(ENV_FILE).read(),
      open(ENV_FILE).read().replace("\n", " ")[:90])

# ------------------------------------------------------------ 10. 단계 6 커버리지
print("\n### 10. 단계 6 — Xdebug 가 없으면 건너뛰고 그 사실을 남긴다")

d = new_slice("cov")
baseline(d)
p, secs = run([d, "--stage", "6", "--config", CONFIG])
st = state_of(d)
check("Xdebug 가 없으면 건너뛴다 (exit 0)", p.returncode == 0 and "건너뜀" in p.stdout,
      f"exit={p.returncode}", secs=secs)
check("건너뛴 사실이 state.json 의 skips 에 남는다",
      "6" in (st.get("skips") or {}) and "Xdebug" in st["skips"]["6"],
      str(st.get("skips")))
check("건너뛴 단계의 게이지는 0 이 아니라 null 이다",
      st["gauges"]["legacy_lines"] is None, str(st["gauges"]["legacy_lines"]))

set_flag("xdebug")
p, _ = run([d, "--stage", "6", "--config", NO_COVERAGE])
check("Xdebug 는 있는데 coveragePath 키가 없으면 exit 3",
      p.returncode == 3 and "coveragePath" in p.stdout, f"exit={p.returncode}")

p, _ = run([d, "--stage", "6", "--config", CONFIG])
check("Xdebug 는 있는데 산출물이 안 생기면 exit 3 (배선 없는 커버리지를 0 으로 적지 않는다)",
      p.returncode == 3 and "배선" in p.stdout, f"exit={p.returncode}")

if pins:
    shutil.copyfile(pins, os.path.join(d, "pins.json"))
    pinned = list(json.load(open(pins))["pins"].values())[0]
    lo, hi = pinned["lines"][:2]
    set_flag("coverage_on")

    def coverage_is(payload):
        with open(os.path.join(FLAGS, "coverage_content"), "w",
                  encoding="utf-8") as fh:
            json.dump(payload, fh)

    coverage_is({pinned["file"]: {str(lo): 1, str(hi): 1}})
    p, _ = run([d, "--stage", "6", "--config", CONFIG])
    check("옮긴 본문이 migrated 에서 실행되면 실패 (exit 1)",
          p.returncode == 1 and state_of(d)["gauges"]["legacy_lines"] == 2,
          f"exit={p.returncode} · {state_of(d)['gauges']['legacy_lines']}")
    coverage_is({pinned["file"]: {str(hi + 500): 3}})
    p, _ = run([d, "--stage", "6", "--config", CONFIG])
    check("본문 밖의 실행 줄은 세지 않는다 (exit 0, 게이지 0)",
          p.returncode == 0 and state_of(d)["gauges"]["legacy_lines"] == 0,
          f"exit={p.returncode}")
    set_flag("coverage_on", False)
else:
    skip("커버리지 줄 범위 판정", "php 가 없어 핀의 줄 범위를 만들 수 없다")
set_flag("xdebug", False)
if os.path.exists(COVERAGE):
    os.remove(COVERAGE)

# ------------------------------------------------------------ 11. 상한
# --------------------------------------- 10.5 측정 불가 회차는 예산을 쓰지 않는다
print("\n### 10.5 측정 불가(exit 3) 회차는 예산에서 되돌려진다")

# 회차를 돌기 **전에** 세는 것은 맞다 — 중간에 죽은 실행도 회차를 쓴 것이다. 그러나
# 검사 자체가 돌지 못한 회차는 루프에 대해 아무것도 말하지 않으므로 예산을 쓰지 않는다.
# 되돌린 사실은 조용히 두지 않고 연속 횟수로 남긴다.
d = new_slice("unmeas", caps="L2=9,L3=2")
baseline(d)
set_flag("xdebug")

p, _ = run([d, "--stage", "6", "--config", CONFIG])
st = state_of(d)
check("측정 불가로 끝나면 exit 3", p.returncode == 3, f"exit={p.returncode}")
check("그 회차는 예산에서 되돌려진다 (L3 가 0 이다)",
      st["loops"]["L3"]["n"] == 0, str(st["loops"]["L3"]))
check("되돌린 사실을 조용히 두지 않는다 (출력에 남는다)",
      "회차를 되돌렸다" in p.stdout + p.stderr)
check("측정 불가 연속 횟수를 센다", (st.get("unmeasurable") or {}).get("L3") == 1,
      str(st.get("unmeasurable")))

p, _ = run([d, "--stage", "6", "--config", CONFIG])
st = state_of(d)
check("두 번째도 되돌려진다 (상한 2 를 소모하지 않는다)",
      st["loops"]["L3"]["n"] == 0 and (st.get("unmeasurable") or {}).get("L3") == 2,
      f"{st['loops']['L3']} · {st.get('unmeasurable')}")

p, _ = run([d, "--stage", "6", "--config", CONFIG])
check("두 번 연속이면 크게 말한다", "회 연속" in p.stderr, p.stderr[-140:])
check("그러나 막지 않는다 — 막으면 고친 것을 확인할 길이 없어 교착이 된다",
      p.returncode == 3 and "진행하지 않았다" not in p.stderr,
      f"exit={p.returncode}")

# 측정이 일어난 회차는 연속 횟수를 0 으로 되돌린다. Xdebug 가 없으면 단계 6 은
# 건너뛰는데, 건너뛴 것도 "검사가 돌았고 답할 수 없다고 말한 것"이므로 exit 0 이다.
set_flag("xdebug", on=False)
p, _ = run([d, "--stage", "6", "--config", CONFIG])
st = state_of(d)
check("측정이 일어나면(건너뜀 포함) 연속 횟수가 0 으로 돌아간다",
      not (st.get("unmeasurable") or {}).get("L3"),
      f"exit={p.returncode} · {st.get('unmeasurable')}")

print("\n### 11. 상한 — 닿으면 진행하지 않는다")

d = new_slice("cap", caps="L2=1,L3=2")
baseline(d)
open(LOG, "w").close()
p, _ = run([d, "--stage", "3", "--config", CONFIG])
check("첫 회차는 돈다", p.returncode == 0, f"exit={p.returncode}")

deliver("legacy")
before = open(ENV_FILE).read()
p, _ = run([d, "--stage", "3,4", "--config", CONFIG])
check("상한에 닿으면 exit 4 — 1(빨간불)과 구별된다",
      p.returncode == 4 and "상한에 닿았다" in p.stderr, f"exit={p.returncode}")
check("상한 정지는 토글도 env 파일도 건드리지 않는다",
      open(ENV_FILE).read() == before)
check("상한 정지는 회차를 더 올리지 않는다",
      state_of(d)["loops"]["L2"]["n"] == 1, str(state_of(d)["loops"]["L2"]))
check("상한 정지가 게이지를 함께 말한다", "게이지" in p.stderr)

p, _ = run([d, "--stage", "5", "--config", CONFIG])
check("다른 루프의 상한은 따로 센다 (L2 가 닿아도 L3 는 돈다)",
      p.returncode != 4 and "상한에 닿았다" not in p.stderr,
      f"exit={p.returncode}")

# ------------------------------------------------------------ 12. 단계 7 복귀·순서
print("\n### 12. 단계 7 복귀, 그리고 실패에서 멈추는 것")

d = new_slice("restore")
baseline(d)
deliver("migrated")
p, secs = run([d, "--stage", "7", "--config", CONFIG])
check("단계 7 은 토글을 legacy 로 되돌리고 되읽기로 확인한다",
      p.returncode == 0 and state_of(d)["toggle"] == "legacy",
      f"exit={p.returncode} · {delivered().get('X_BACKEND_DEMO_PAGE')}", secs=secs)

d = new_slice("stop")
baseline(d)
open(LOG, "w").close()
set_flag("mismatch")
p, _ = run([d, "--stage", "3,4,7", "--config", CONFIG])
set_flag("mismatch", False)
lines = [l for l in p.stdout.splitlines() if l.strip().startswith("단계")]
check("실패한 단계에서 멈추고 뒤 단계를 돌지 않는다",
      p.returncode == 1 and len(lines) == 1 and " 3 " in lines[0],
      f"exit={p.returncode} · {len(lines)}단계 실행")
check("돌지 않은 단계를 통과로 적지 않는다 (golden_diff 는 여전히 null)",
      state_of(d)["gauges"]["golden_diff"] is None,
      str(state_of(d)["gauges"]))

d = new_slice("full")
baseline(d)
open(LOG, "w").close()
p, secs = run([d, "--stage", "1,2,3,4,6,7", "--config", CONFIG], timeout=300)
check("환경부터 복귀까지 한 번에 통과한다 (단계 5 는 핀이 필요해 뺐다)",
      p.returncode == 0, f"exit={p.returncode} · {p.stdout.strip()[-100:]}", secs=secs)
st = state_of(d)
check("회차가 루프별로 기록된다 (L2 1 · L3 1)",
      st["loops"]["L2"]["n"] == 1 and st["loops"]["L3"]["n"] == 1,
      str({k: v["n"] for k, v in st["loops"].items()}))
check("rounds 에 단계마다 한 줄이 쌓인다", len(st["rounds"]) == 6,
      f"{len(st['rounds'])}줄")

p, _ = run([d, "--show", "--json", "--config", CONFIG])
check("--show --json 이 state.json 을 그대로 낸다",
      p.returncode == 0 and json.loads(p.stdout)["slice"] == SLICE_ID,
      f"exit={p.returncode}")

# ------------------------------------------------------------ 정리
server.shutdown()
bff.close()
shutil.rmtree(BASE, ignore_errors=True)
print("\n" + "=" * 64)
bad = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(bad)}/{len(results)} 통과"
      + ("" if not bad else "   실패: " + ", ".join(bad)))
if skipped:
    print(f"건너뜀 {len(skipped)}개 — " + ", ".join(n for n, _ in skipped))
    print("  건너뛴 검사는 통과가 아니다.")
sys.exit(1 if bad else 0)
