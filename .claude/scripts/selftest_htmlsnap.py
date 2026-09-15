#!/usr/bin/env python3
"""htmlsnap 케이스. 합성 페이지를 스레드로 서빙해, 실제 표면 없이 검사한다.

    python3 selftest_htmlsnap.py [htmlsnap 경로]

이 파일은 **실제 workspace.json 을 읽지 않는다.** 스크래치 디렉터리에 합성 설정을 쓰고
`--config` 로 그것을 가리킨다. 그래서 스택이 내려가 있어도, 설정이 비어 있어도 돌고,
로컬 표면에 요청을 하나도 보내지 않는다.

서빙하는 페이지는 이 도구가 틀릴 수 있는 자리마다 하나씩이다.
  정상       CP949 본문 + charset 없는 헤더        - 바이트로 저장하는가
  로그아웃   200 + `<script>confirm(...)</script>`  - 상태 코드로 판정하지 않는가
  5xx        서버 오류                              - error_page 로 잡는가
  토큰       매 요청 바뀌는 값                      - 정규화가 먹는가
  목록       텍스트만 다른 두 판                    - structure 모드가 같다고 하는가
  되읽기     현재 모드를 출력                       - --toggle-expect 가 실제로 읽는가
  느림       타임아웃보다 오래                      - timeout 을 unreachable 과 가르는가
  쿠키       받은 Cookie 헤더를 본문에 반영         - storageState 가 요청에 실리는가
"""
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "htmlsnap")
if not os.path.isfile(TOOL):
    sys.exit(f"사용법: selftest_htmlsnap.py [htmlsnap 경로]  (찾은 곳: {TOOL})")

BASE = tempfile.mkdtemp(prefix="htmlsnap-selftest-")
SURFACE = "synth"                       # 가짜 표면 이름. 실제 이름을 적지 않는다.
KO = "가나다 공지사항".encode("cp949")   # CP949 바이트. 디코드하면 안 되는 그 바이트.

results = []


def check(name, ok, detail="", secs=None):
    results.append((name, ok, detail))
    t = f"  {secs:5.1f}s" if secs is not None else "        "
    print(f"  {'통과' if ok else 'FAIL'}{t}  {name}" + (f"   {detail}" if detail else ""))


# ------------------------------------------------------------- 합성 서버

STATE = {"mode": "php"}                 # 되읽기 페이지가 말할 값
COUNTER = {"n": 0}


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):          # 조용히
        pass

    def _send(self, code, body, ctype="text/html"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)      # charset 을 일부러 붙이지 않는다
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        cookie = self.headers.get("Cookie", "")
        if path == "/ok.php":
            self._send(200, b"<html><body><h1>" + KO + b"</h1>"
                       + f"<!--cookie:{cookie}-->".encode("ascii", "replace")
                       + b"</body></html>")
        elif path == "/loggedout.php":
            self._send(200, b"<html><script>confirm('login?');"
                            b"location.href='/sso';</script></html>")
        elif path == "/boom.php":
            self._send(500, b"<html><!--server-error-->500</html>")
        elif path == "/token.php":
            COUNTER["n"] += 1
            self._send(200, b"<html><input name='x' value='csrf_token="
                       + f"{COUNTER['n']:08x}".encode() + b"'>" + KO + b"</html>")
        elif path == "/list.php":
            v = params.get("v", "1")
            rows = b"".join(b"<li class='row'><a href='/d.php?seq=" + str(i).encode()
                            + b"'>" + f"{v}-{i} ".encode() + KO + b"</a></li>"
                            for i in range(3))
            self._send(200, b"<html><ul id='listbox'>" + rows + b"</ul></html>")
        elif path == "/readback.php":
            self._send(200, b"<html><p>toggle=" + STATE["mode"].encode() + b"</p></html>")
        elif path == "/slow.php":
            time.sleep(3)
            self._send(200, b"<html>slow</html>")
        else:
            self._send(404, b"<html>404</html>")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


srv = Server(("127.0.0.1", 0), Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE_URL = f"http://127.0.0.1:{PORT}"

# ------------------------------------------------------------- 합성 설정

CONFIG = os.path.join(BASE, "workspace.json")
SESSION = os.path.join(BASE, "storageState.json")


def write_config(logged_out=r"confirm\(|history\.back\(", snapshot=True):
    cfg = {"legacy": {
        "surfaces": {SURFACE: {"localBaseUrl": BASE_URL, "charset": "cp949"}},
        "dualRun": {"readbackPath": "/readback.php"},
        "switch": {"values": {"legacy": "php", "dual": "dual", "migrated": "spring"}}}}
    if logged_out:
        cfg["legacy"]["surfaces"][SURFACE]["loggedOutMarker"] = logged_out
    if snapshot:
        cfg["legacy"]["snapshot"] = {
            "normalize": [{"pattern": r"csrf_token=[0-9a-f]+",
                           "replace": "csrf_token=<TOKEN>"}],
            "errorMarker": "<!--server-error-->", "timeoutSeconds": 5}
    cfg["e2e"] = {"storageState": {SURFACE: SESSION}}
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False)


write_config()
with open(SESSION, "w", encoding="utf-8") as fh:
    json.dump({"cookies": [
        {"name": "SESSIONID", "value": "abc123", "domain": "127.0.0.1", "path": "/"},
        {"name": "ELSEWHERE", "value": "nope", "domain": "other.example", "path": "/"},
    ], "origins": []}, fh)


def corpus(name, entries, surface=SURFACE):
    path = os.path.join(BASE, f"corpus-{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"surface": surface, "entries": entries}, fh, ensure_ascii=False)
    return path


def run(args, timeout=90):
    t0 = time.time()
    p = subprocess.run([sys.executable, TOOL] + args, capture_output=True, text=True,
                       timeout=timeout, cwd=BASE)
    return p, time.time() - t0


def capture(name, entries, extra=None, timeout=90):
    out = os.path.join(BASE, "cap-" + name)
    args = ["capture", "--corpus", corpus(name, entries), "--out", out,
            "--config", CONFIG] + (extra or [])
    p, secs = run(args, timeout=timeout)
    return p, out, secs


def manifest(out):
    with open(os.path.join(out, "manifest.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    return {e["id"]: e for e in doc["entries"]}


E_OK = {"id": "ok", "path": "/ok.php", "mode": "full", "rules": ["R-01"]}
E_OUT = {"id": "loggedout", "path": "/loggedout.php"}
E_BOOM = {"id": "boom", "path": "/boom.php"}
E_TOKEN = {"id": "token", "path": "/token.php"}
E_SLOW = {"id": "slow", "path": "/slow.php"}


print(f"# 합성 표면 {BASE_URL} · 도구 {TOOL}")
print("\n### 1. capture — 플래그를 제대로 붙이는가")

p, out_flags, secs = capture("flags", [E_OK, E_OUT, E_BOOM, E_SLOW],
                             extra=["--timeout", "1"])
m = manifest(out_flags) if os.path.isfile(os.path.join(out_flags, "manifest.json")) else {}
check("정상 페이지는 유효하고 CP949 바이트가 그대로 저장된다",
      bool(m) and m["ok"]["valid"]
      and open(os.path.join(out_flags, "ok.raw.html"), "rb").read().find(KO) > 0,
      "" if m else f"exit={p.returncode} {p.stderr[-200:]}", secs=secs)
check("미인증 200 + confirm() 을 logged_out 으로 잡는다 (상태 코드가 아니라 본문)",
      bool(m) and m["loggedout"]["status"] == 200
      and m["loggedout"]["flags"] == ["logged_out"],
      str(m.get("loggedout", {}).get("flags")))
check("5xx 를 error_page 로 잡는다",
      bool(m) and m["boom"]["flags"] == ["error_page"],
      str(m.get("boom", {}).get("flags")))
check("타임아웃을 timeout 으로 잡는다 (unreachable 과 구분한다)",
      bool(m) and m["slow"]["flags"] == ["timeout"] and m["slow"]["error"],
      str(m.get("slow", {}).get("flags")))
check("invalid 가 섞이면 capture 는 exit 1", p.returncode == 1, f"exit={p.returncode}")

p2, out_dead, secs2 = capture("dead", [E_SLOW], extra=["--timeout", "1"])
check("전부 전송 실패면 exit 2 — 검사 실패가 아니라 '답할 수 없음'이다",
      p2.returncode == 2 and "표면이 떠 있는지" in p2.stderr,
      f"exit={p2.returncode}", secs=secs2)

print("\n### 2. 쿠키 — storageState 가 요청 헤더에 실리는가")
cookie_body = open(os.path.join(out_flags, "ok.raw.html"), "rb").read().decode("cp949")
check("storageState 의 쿠키가 Cookie 헤더로 나간다",
      "cookie:SESSIONID=abc123" in cookie_body, cookie_body.split("<!--")[-1][:60])
check("도메인이 다른 쿠키는 빼고, 뺐다는 사실을 말한다",
      "ELSEWHERE" not in cookie_body and "1개는 도메인이" in p.stderr,
      "" if "ELSEWHERE" not in cookie_body else "다른 도메인 쿠키가 새어나갔다")

print("\n### 3. 정규화·구조 모드")
pa, out_t1, _ = capture("tok1", [E_TOKEN])
pb, out_t2, _ = capture("tok2", [E_TOKEN])
pa_m, pb_m = manifest(out_t1), manifest(out_t2)
_norm_same = pa_m["token"]["sha256_norm"] == pb_m["token"]["sha256_norm"]
_raw_diff = pa_m["token"]["sha256_raw"] != pb_m["token"]["sha256_raw"]
check("매 요청 바뀌는 토큰이 정규화로 지워져 두 캡처의 정규화본이 같다",
      _norm_same and _raw_diff,
      "" if _norm_same and _raw_diff
      else ("raw 가 같아 검사가 성립하지 않는다" if not _raw_diff else "정규화가 안 먹었다"))

L1 = {"id": "list", "path": "/list.php", "params": {"v": "1"}, "mode": "structure"}
L2 = {"id": "list", "path": "/list.php", "params": {"v": "2"}, "mode": "structure"}
F1 = {"id": "list", "path": "/list.php", "params": {"v": "1"}, "mode": "full"}
F2 = {"id": "list", "path": "/list.php", "params": {"v": "2"}, "mode": "full"}
_, out_s1, _ = capture("s1", [L1])
_, out_s2, _ = capture("s2", [L2])
_, out_f1, _ = capture("f1", [F1])
_, out_f2, _ = capture("f2", [F2])
ps, _ = run(["compare", out_s1, out_s2, "--config", CONFIG])
pf, _ = run(["compare", out_f1, out_f2, "--config", CONFIG])
check("structure 모드: 텍스트만 다른 두 판이 identical",
      ps.returncode == 0 and "identical" in ps.stdout, f"exit={ps.returncode}")
check("full 모드로는 같은 쌍이 different — 구조 모드가 실제로 무언가를 지운다",
      pf.returncode == 1 and "different" in pf.stdout, f"exit={pf.returncode}")

print("\n### 4. compare — 네 가지 결과와 종료 코드")
pc, _ = run(["compare", out_t1, out_t1, "--config", CONFIG])
check("같은 디렉터리끼리는 identical, exit 0", pc.returncode == 0, f"exit={pc.returncode}")

_, out_two, _ = capture("two", [E_TOKEN, E_OK])
pm, _ = run(["compare", out_t1, out_two, "--config", CONFIG])
check("한쪽에만 있는 id 는 missing, exit 1",
      pm.returncode == 1 and "missing" in pm.stdout, f"exit={pm.returncode}")

rep = os.path.join(BASE, "report.md")
pd, _ = run(["compare", out_f1, out_f2, "--config", CONFIG, "--report", rep,
             "--context", "1"])
body = open(rep, encoding="utf-8").read() if os.path.isfile(rep) else ""
check("--report 가 마크다운 표와 diff 를 쓴다",
      "| id | 결과 | 비고 |" in body and "```diff" in body, f"{len(body)}바이트")

_, out_bad, _ = capture("bad", [E_OUT])
pi, _ = run(["compare", out_bad, out_bad, "--config", CONFIG])
check("어느 쪽에든 invalid 캡처가 있으면 exit 2 — 로그아웃 페이지는 기준선이 못 된다",
      pi.returncode == 2 and "기준선이 될 수 없" in pi.stderr, f"exit={pi.returncode}")

print("\n### 5. 토글 되읽기")
STATE["mode"] = "php"
pt, _, secs = capture("tog-bad", [E_OK], extra=["--toggle-expect", "dual"])
check("되읽기가 다른 모드를 말하면 캡처하지 않고 exit 2",
      pt.returncode == 2 and "'legacy'" in pt.stderr and "'dual'" in pt.stderr,
      f"exit={pt.returncode} {pt.stderr.strip()[-90:]}", secs=secs)
STATE["mode"] = "dual"
pt2, out_tog, secs2 = capture("tog-ok", [E_OK], extra=["--toggle-expect", "dual"])
check("되읽기가 맞으면 캡처하고 manifest 에 기록한다",
      pt2.returncode == 0 and manifest(out_tog) and
      json.load(open(os.path.join(out_tog, "manifest.json")))["toggle_readback"] == "dual",
      f"exit={pt2.returncode}", secs=secs2)
STATE["mode"] = "php"

print("\n### 6. corpus validate · 설정 부재")
good = corpus("valid-ok", [E_OK])
pv, _ = run(["corpus", "validate", good, "--config", CONFIG])
check("정상 코퍼스는 exit 0", pv.returncode == 0, f"exit={pv.returncode}")

bad_corpus = os.path.join(BASE, "corpus-broken.json")
with open(bad_corpus, "w", encoding="utf-8") as fh:
    json.dump({"surface": "없는표면", "entries": [
        {"id": "a b", "path": "relative", "mode": "이상함"},
        {"id": "dup", "path": "/x.php"}, {"id": "dup", "path": "/y.php"}]}, fh,
        ensure_ascii=False)
pv2, _ = run(["corpus", "validate", bad_corpus, "--config", CONFIG])
check("어긋난 코퍼스는 문제를 하나씩 짚고 exit 1",
      pv2.returncode == 1 and pv2.stdout.count("문제") >= 5,
      f"exit={pv2.returncode} 문제 {pv2.stdout.count('문제') - 1}건")

write_config(logged_out=None)
pn, _, _ = capture("nomarker", [E_OK])
check("loggedOutMarker 가 없으면 캡처하지 않고 이유를 말한다 (exit 2)",
      pn.returncode == 2 and "loggedOutMarker" in pn.stderr,
      f"exit={pn.returncode}")
write_config(snapshot=False)
pn2, _, _ = capture("nosnap", [E_OK])
check("legacy.snapshot 이 없어도 멈춘다",
      pn2.returncode == 2 and "legacy.snapshot" in pn2.stderr, f"exit={pn2.returncode}")
write_config()

pu, _ = run(["capture", "--corpus", good, "--out", os.path.join(BASE, "x"),
             "--config", CONFIG, "--모르는옵션", "1"])
check("모르는 옵션은 조용히 무시하지 않는다",
      pu.returncode == 2 and "모르는 옵션" in pu.stderr, f"exit={pu.returncode}")

# ------------------------------------------------------------------ 정리
srv.shutdown()
shutil.rmtree(BASE, ignore_errors=True)
bad = [n for n, ok, _ in results if not ok]
print("\n" + "=" * 64)
print(f"{len(results) - len(bad)}/{len(results)} 통과"
      + ("" if not bad else "   실패: " + ", ".join(bad)))
sys.exit(1 if bad else 0)
