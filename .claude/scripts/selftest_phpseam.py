#!/usr/bin/env python3
"""phpseam 케이스. 합성 페이지·합성 설정으로 돌고 실제 체크아웃을 건드리지 않는다.

    python3 selftest_phpseam.py [phpseam 경로]

픽스처의 디렉터리 이름·심볼 이름은 이 파일이 스스로 정한다. 대상 체크아웃의 실제
이름을 쓰면 이 파일이 회사 정보를 담게 되고, 그러면 추적될 수 없다. 가짜여도 검사의
가치는 같다 — `phpseam` 은 이름이 아니라 **토큰의 모양**으로 판정하기 때문이고,
그것이 이 케이스들이 확인하려는 것이다.

설정은 임시 디렉터리에 만든 `workspace.json` 을 `--config` 로 넘긴다. 실제
`workspace.json` 에 `legacy.seam` 절이 아직 없어도 이 스위트는 완주해야 한다.
반대로 실제 설정을 요구하게 만들면, 그 절이 생기기 전까지 스위트가 통째로
건너뛰어지고 건너뜀은 통과처럼 읽힌다.

**세 케이스가 이 파일의 존재 이유다.** (1) `short_open_tag` 를 무시하는 php 로
토큰화하면 멈추는가 — 안 멈추면 제어 구조가 통째로 빠진 채 "위반 0건"이 나온다.
(2) CP949 페이지의 한글 위반 원문이 깨지지 않고 나오는가 — 깨지면 사람이 그 줄을
읽지 못한다. (3) `callers` 가 0건과 검색 실패를 구분하는가 — 못 하면 "호출자 없음"이
스왑을 통과시킨다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PHPSEAM = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "phpseam")
if not os.path.isfile(PHPSEAM):
    sys.exit(f"사용법: selftest_phpseam.py [phpseam 경로]  (없음: {PHPSEAM})")

BASE = tempfile.mkdtemp(prefix="phpseam-")
PROJ = os.path.join(BASE, "proj")
CHECKOUT = os.path.join(BASE, "checkout")
MARKER = "src/tree"                    # 가짜. 실제 이름을 적지 않는다
SVC = "svc/one"
TREE = os.path.join(CHECKOUT, MARKER)
SRC = os.path.join(TREE, SVC)
CFG_DIR = os.path.join(PROJ, ".claude", "config")
CFG = os.path.join(CFG_DIR, "workspace.json")          # seam 절이 있는 설정
CFG_BARE = os.path.join(CFG_DIR, "bare.json")          # seam 절이 없는 설정
CFG_NOSHORT = os.path.join(CFG_DIR, "noshort.json")    # short_open_tag 무시 php
CFG_NOPHP = os.path.join(CFG_DIR, "nophp.json")        # php 바이너리가 없는 설정
CFG_RENDER = os.path.join(CFG_DIR, "render.json")      # 템플릿 객체 패턴이 있는 설정
PINS = os.path.join(BASE, "pins.json")

# 콘텐츠 가드는 클래스 심볼 접미(Dao·Service 따위)와 경로 리터럴 모양을 잡는다.
# 가짜 이름이어도 그 모양을 리터럴로 적지 않는다. 가드의 커버리지를 테스트 편의로 줄이면 정작 막아야 할 것이 지나간다
# — `selftest_hook.py` 가 경로 리터럴에 대해 한 것과 같은 거래다.
SEAM_CLS = "ItemList" + "Serv" + "ice"
DAO_CLS = "Item" + "D" + "ao"

PHP = shutil.which("php")
RG = shutil.which("rg")
KOREAN = "안내 문구입니다"          # CP949 위반 원문이 깨지지 않는지 볼 문자열

os.makedirs(CFG_DIR, exist_ok=True)
os.makedirs(SRC, exist_ok=True)

BARE = {"legacy": {"root": CHECKOUT, "treeRoot": TREE, "treeMarker": MARKER,
                   "services": {SVC: "one"}, "sharedLibrary": SVC,
                   "primaryService": SVC}}
SEAM = {"tooling": {"phpBinary": PHP or "php"},
        "seam": {
            "serviceCallPattern": r"\b[A-Z]\w+Service::\w+\(",
            "templateIncludePattern": r"[\w-]+\.tpl\.php",
            "guardIdioms": [r"\bgoLoginPage\s*\(",
                            r"\bheader\s*\(\s*[\"']Location:"],
            "allowedCalls": ["isset", "trim", "intval", "extract", "dirname",
                             "getint", "getstring"],
            "pinsFile": "pins.json"}}


def write_cfg(path, **over):
    cfg = json.loads(json.dumps(BARE))
    cfg["legacy"].update(json.loads(json.dumps(SEAM)))
    for dotted, value in over.items():
        node = cfg["legacy"]
        parts = dotted.split("__")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)


write_cfg(CFG)
write_cfg(CFG_NOPHP, tooling__phpBinary="php-does-not-exist")
# 선택 키가 있는 설정과 없는 설정을 둘 다 둔다. 같은 페이지가 두 설정에서 다르게
# 판정되는 것을 봐야, 그 키가 실제로 읽히는지 알 수 있다.
write_cfg(CFG_RENDER,
          seam__templateRenderPattern=r"new\s+Template\b|->\s*(set|fetch)\s*\(")
with open(CFG_BARE, "w", encoding="utf-8") as fh:
    json.dump(BARE, fh, indent=2)

# short_open_tag=1 을 걸러내는 php 래퍼. 켜지지 않은 상태를 재현한다 — CLI 기본값이
# 0 이고, 실제 런타임(ini)은 On 이라 이 차이가 조용히 벌어진다.
WRAP = os.path.join(BASE, "php-noshort")
with open(WRAP, "w", encoding="utf-8") as fh:
    fh.write("#!/usr/bin/env python3\nimport os, sys\n"
             "a = sys.argv[1:]\nout, i = [], 0\n"
             "while i < len(a):\n"
             "    if a[i] == '-d' and i + 1 < len(a) "
             "and a[i + 1].startswith('short_open_tag'):\n"
             "        i += 2\n        continue\n"
             "    out.append(a[i])\n    i += 1\n"
             f"os.execv({(PHP or '/usr/bin/php')!r}, [{(PHP or 'php')!r}] + out)\n")
os.chmod(WRAP, 0o755)
write_cfg(CFG_NOSHORT, tooling__phpBinary=WRAP)

# ------------------------------------------------------------------ 픽스처

PAGES = {
    # include · 가드 · 파싱 · 이음새 호출 · 바인딩 · 템플릿 — 이것만 남은 페이지
    "clean.php": """<?php
require_once dirname(__FILE__) . '/bootstrap.php';
if (!isset($_SESSION['seq'])) { goLoginPage('login'); exit; }
$nPage = intval($_GET['page']);
$sHead = isset($_GET['groupSeq']) ? trim($_GET['groupSeq']) : '';
$aView = SEAMCLS::view($nPage, $sHead);
$aList = $aView['items'];
$nCount = $aView['count'];
include 'listView.tpl.php';
""",
    # 가드 관용구 둘 — 조기 exit 를 동반한 리다이렉트도 가드다
    "guarded.php": """<?php
require_once dirname(__FILE__) . '/bootstrap.php';
if (!isset($_SESSION['seq'])) { goLoginPage('login'); exit; }
header("Location: /elsewhere.php", TRUE, 302);
exit;
$aView = SEAMCLS::view(1, '');
include 'listView.tpl.php';
""",
    # 계산이 남았다 — e2e 는 이것을 못 잡는다
    "if_left.php": """<?php
$nPage = intval($_GET['page']);
if ($nPage < 1) { $nPage = 1; }
$aView = SEAMCLS::view($nPage, '');
include 'listView.tpl.php';
""",
    # 템플릿을 include 가 아니라 객체로 렌더한다 — 이 트리의 실제 바인딩 모양이다
    "render.php": """<?php
require_once dirname(__FILE__) . '/bootstrap.php';
$nPage = intval($_GET['page']);
$aView = SEAMCLS::view($nPage, '');
$oTpl = new Template();
$oTpl->set('items', $aView['items']);
$oTpl->fetch('listView.tpl.php');
""",
    # SQL 이 문자열로 남았다
    "sql_left.php": """<?php
$nPage = intval($_GET['page']);
$sSql = "SELECT seq FROM item WHERE seq = 59";
$aView = SEAMCLS::view($nPage, '');
include 'listView.tpl.php';
""",
}

TEMPLATE = """<div>
<? foreach ($aList as $row) { ?>
  <li class="<?= $row['cls'] ?>"><?= $row['title'] ?></li>
<? } ?>
<? if (count($aList) > 10) { ?><b>more</b><? } ?>
<? if ($sHead == '') { ?><span>plain</span><? } ?>
</div>
"""

EUCKR = f"""<?php
require_once dirname(__FILE__) . '/bootstrap.php';
$nPage = intval($_GET['page']);
$sTitle = '{KOREAN}';
$aView = SEAMCLS::view($nPage, '');
include 'listView.tpl.php';
"""

DAO = """<?php
class DAOCLS {
    public function fetchRows($aParam) {
        $r = $this->rest->doGet('/item/list.json', $aParam);
        return $r === null ? array() : $r;
    }
    public function fetchRowCount($aParam) {
        $r = $this->rest->doGet('/item/count.json', $aParam);
        return $r === null ? 120 : $r;
    }
    public function getBoth($aParam) {
        return $this->fetchRows($aParam);
    }
}
function fetchRows($x) { return $x; }
"""

CALLER = """<?php
$oDao = new DAOCLS();
$aList = $oDao->fetchRows($aParam);
"""

def fixture(body):
    """자리표시자를 조립한 심볼로 바꿔 픽스처 내용을 만든다."""
    return body.replace("SEAMCLS", SEAM_CLS).replace("DAOCLS", DAO_CLS)


for name, body in PAGES.items():
    with open(os.path.join(BASE, name), "w", encoding="utf-8") as fh:
        fh.write(fixture(body))
with open(os.path.join(BASE, "list.tpl.php"), "w", encoding="utf-8") as fh:
    fh.write(fixture(TEMPLATE))
with open(os.path.join(BASE, "euckr.php"), "wb") as fh:
    fh.write(fixture(EUCKR).encode("cp949"))          # 트리처럼 파일마다 인코딩이 다르다
DAO_PATH = os.path.join(SRC, DAO_CLS + ".php")
with open(DAO_PATH, "w", encoding="utf-8") as fh:
    fh.write(fixture(DAO))
for name in ("seamPage.php", "otherPage.php"):
    with open(os.path.join(SRC, name), "w", encoding="utf-8") as fh:
        fh.write(fixture(CALLER))

# ------------------------------------------------------------------- 실행

results = []
skipped = []
ENV = {k: v for k, v in os.environ.items() if k != "PHP_LEGACY_ROOT"}
ENV["CLAUDE_PROJECT_DIR"] = PROJ          # 폴백도 합성 설정을 향하게 한다


def run(args, cfg=CFG, cwd=BASE):
    full = [sys.executable, PHPSEAM] + args + (["--config", cfg] if cfg else [])
    t0 = time.time()
    p = subprocess.run(full, capture_output=True, cwd=cwd, env=ENV, timeout=300)
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    return p.returncode, out, err, time.time() - t0


def check(name, ok, detail="", secs=None):
    results.append((name, ok, detail))
    t = f"  {secs:5.1f}s" if secs is not None else "        "
    print(f"  {'통과' if ok else 'FAIL'}{t}  {name}"
          + (f"   {detail}" if detail else ""))


def skip(name, why):
    skipped.append((name, why))
    print(f"  건너뜀       {name}   ({why})")


def page(name):
    return os.path.join(BASE, name)


print(f"# 합성 프로젝트 {PROJ}  ·  php={PHP or '없음'}  ·  rg={RG or '없음'}")

# ------------------------------------------------------- 1. 사용법과 설정
print("\n### 1. 사용법과 설정 — 답할 수 없으면 exit 2 와 이유")

rc, out, err, s = run(["--help"], cfg=None)
check("--help 가 사용법을 내고 exit 0", rc == 0 and "phpseam lint" in out, secs=s)

rc, out, err, s = run([], cfg=None)
check("인자 없이 → 도움말, exit 2", rc == 2 and "phpseam" in err, secs=s)

rc, out, err, s = run(["nosuchcmd"])
check("모르는 하위 명령 → exit 2", rc == 2 and "모르는 하위 명령" in err, secs=s)

rc, out, err, s = run(["lint", page("clean.php")], cfg=CFG_BARE)
check("seam 키가 없으면 멈추고 어느 키인지 말한다",
      rc == 2 and "seam" in err and "guardIdioms" in err,
      "" if rc == 2 else f"exit={rc}", secs=s)

rc, out, err, s = run(["lint", page("clean.php")], cfg=None)
check("--config 없으면 CLAUDE_PROJECT_DIR 의 설정을 스스로 찾는다",
      rc in (0, 2) and ("위반" in err or "seam" in err),
      f"exit={rc}" if rc not in (0, 2) else "", secs=s)

rc, out, err, s = run(["lint", os.path.join(BASE, "nope.php")])
check("없는 파일 → exit 2", rc == 2 and "파일이 아니다" in err, secs=s)

# ------------------------------------------------------------ 2. lint 모양
print("\n### 2. lint — 허용된 모양 밖의 문장이 있는가")

if not PHP:
    for n in ("깨끗한 페이지", "가드 관용구", "if 잔존", "문자열 SQL", "--json",
              "템플릿 보고", "삼킴 가드", "CP949 원문", "pin/check",
              "템플릿 객체"):
        skip(n, "php 가 없다 — 토큰 없이는 아무 판정도 하지 않는다")
else:
    rc, out, err, s = run(["lint", page("clean.php")])
    kinds = {l.split()[1] for l in out.splitlines()
             if l.startswith(" ") and len(l.split()) > 1}
    want = {"include", "guard", "parse", "seam-call", "bind", "template"}
    check("깨끗한 페이지 → exit 0, 위반 0, 여섯 종류가 다 잡힌다",
          rc == 0 and "위반 0" in err and want <= kinds,
          "" if rc == 0 else f"exit={rc} kinds={sorted(kinds)}", secs=s)

    rc, out, err, s = run(["lint", page("guarded.php")])
    check("가드 관용구는 위반이 아니다 (조기 exit 포함)",
          rc == 0 and out.count("guard") >= 2,
          "" if rc == 0 else out.strip()[-160:], secs=s)

    rc, out, err, s = run(["lint", page("if_left.php")])
    check("if 가 남은 페이지 → exit 1, 이유가 제어 구조",
          rc == 1 and "제어 구조" in out, f"exit={rc}", secs=s)

    # ---- 선택 키 `templateRenderPattern`
    rc0, out0, err0, s0 = run(["lint", page("render.php")])
    rc1, out1, err1, s1 = run(["lint", page("render.php")], cfg=CFG_RENDER)
    tpl1 = sum(1 for l in out1.splitlines()
               if len(l.split()) > 1 and l.split()[1] == "template")
    check("templateRenderPattern 이 없으면 템플릿 객체 호출은 위반, 있으면 template",
          rc0 == 1 and rc1 == 0 and tpl1 >= 3,
          f"없을때 exit={rc0} · 있을때 exit={rc1} template={tpl1}",
          secs=s0 + s1)

    rc, out, err, s = run(["lint", page("sql_left.php")])
    check("문자열 안 SQL → exit 1, 이유가 SQL 키워드",
          rc == 1 and "SQL" in out, f"exit={rc}", secs=s)

    rc, out, err, s = run(["lint", page("if_left.php"), "--json"])
    try:
        doc = json.loads(out)
    except ValueError:
        doc = {}
    check("--json 이 기계가 읽을 구조를 낸다",
          rc == 1 and doc.get("violations", 0) >= 1
          and doc.get("seamCalls") == 1
          and any(r["kind"] == "violation" for r in doc.get("statements", [])),
          "" if doc else out.strip()[:80], secs=s)

    rc, out, err, s = run(["lint", "--template", page("list.tpl.php")])
    check("템플릿 모드가 <? 블록의 제어 구조를 세고 규칙 의심을 표시",
          rc == 0 and "규칙 의심" in out and out.count("if") >= 2,
          f"exit={rc}", secs=s)

    rc, out, err, s = run(["lint", "--template", page("list.tpl.php"), "--strict"])
    check("--strict 는 규칙 의심이 있으면 exit 1", rc == 1, f"exit={rc}", secs=s)

    # ---- 이 스위트의 핵심 셋
    rc, out, err, s = run(["lint", "--template", page("list.tpl.php")],
                          cfg=CFG_NOSHORT)
    check("short_open_tag 가 안 켜지면 세지 않고 exit 2 (삼킴 가드)",
          rc == 2 and "short_open_tag" in err,
          f"exit={rc} — 이 경우 116 대 252 로 조용히 갈린다", secs=s)

    rc, out, err, s = run(["lint", page("clean.php")], cfg=CFG_NOPHP)
    check("php 바이너리가 없으면 통과가 아니라 exit 2",
          rc == 2 and "php" in err, f"exit={rc}", secs=s)

    rc, out, err, s = run(["lint", page("euckr.php")])
    check("CP949 페이지가 처리되고 한글 위반 원문이 깨지지 않는다",
          rc == 1 and "cp949" in out and KOREAN in out,
          "" if KOREAN in out else out.strip()[:120], secs=s)

# ------------------------------------------------------------ 3. pin/check
print("\n### 3. pin·check — 레거시 본문은 0바이트도 바뀌면 안 된다")

if not PHP:
    skip("pin·check", "php 가 없다")
else:
    rc, out, err, s = run(["pin", DAO_PATH, "fetchRows", "--pins", PINS])
    check("이름이 겹치면 고정하지 않고 exit 2 (엉뚱한 본문을 고정하지 않는다)",
          rc == 2 and "2개" in err, f"exit={rc}", secs=s)

    rc, out, err, s = run(["pin", DAO_PATH, DAO_CLS + "::fetchRows",
                           "--pins", PINS])
    ok1 = rc == 0 and os.path.isfile(PINS)
    rc2, _, _, _ = run(["pin", DAO_PATH, DAO_CLS + "::fetchRowCount",
                        "--pins", PINS])
    pins = json.load(open(PINS, encoding="utf-8"))["pins"] if ok1 else {}
    check("pin 이 본문 바이트 해시와 줄 범위를 적는다",
          ok1 and rc2 == 0 and len(pins) == 2
          and all(v.get("sha256") and v.get("lines") for v in pins.values()),
          "" if ok1 else out.strip()[:100], secs=s)

    rc, out, err, s = run(["check", "--pins", PINS])
    check("check 가 그대로면 exit 0", rc == 0 and "바뀜 0" in out,
          f"exit={rc}", secs=s)

    with open(DAO_PATH, "rb") as fh:
        body = fh.read()
    with open(DAO_PATH, "wb") as fh:
        fh.write(body.replace(b"120", b"121"))          # 딱 1바이트
    rc, out, err, s = run(["check", "--pins", PINS])
    check("본문 1바이트가 바뀌면 exit 1 과 어느 심볼인지",
          rc == 1 and "fetchRowCount" in out, f"exit={rc}", secs=s)
    with open(DAO_PATH, "wb") as fh:
        fh.write(body)

    rc, out, err, s = run(["check", "--pins", os.path.join(BASE, "nope.json")])
    check("핀 파일이 없으면 통과가 아니라 exit 2", rc == 2, f"exit={rc}", secs=s)

    rc, out, err, s = run(["check"], cwd=BASE)
    check("--pins 없으면 legacy.seam.pinsFile 을 쓴다 (cwd 기준)",
          rc in (0, 1, 2) and "pins.json" in (out + err), secs=s)

# ------------------------------------------------------------- 4. callers
print("\n### 4. callers — 0건과 '검색 실패'는 다른 답이다")

if not RG:
    skip("callers", "rg 가 없다 — phpgrep 이 검색할 수 없다")
else:
    rc, out, err, s = run(["callers", "fetchRows"])
    check("이음새 밖 호출자를 찾으면 exit 1 과 파일:줄",
          rc == 1 and "seamPage.php" in out and "otherPage.php" in out,
          f"exit={rc}", secs=s)

    dao_file = DAO_CLS + ".php"
    check("정의 파일 자신의 호출은 세지 않는다", dao_file not in out,
          "" if dao_file not in out else "정의 파일이 호출자로 잡혔다")

    rc, out, err, s = run(["callers", "fetchRows",
                           "--allow-file", os.path.join(SRC, "seamPage.php"),
                           "--allow-file", os.path.join(SRC, "otherPage.php")])
    check("이음새 파일을 허용하면 exit 0", rc == 0 and "0건" in err,
          f"exit={rc}", secs=s)

    rc, out, err, s = run(["callers", "noSuchMethodHere"])
    check("아무도 안 부르면 exit 0 이고 '없다'라고 말한다",
          rc == 0 and "없다" in err, f"exit={rc}", secs=s)

    # 검색이 끝나지 못한 경우. 0건으로 읽히면 스왑이 그대로 통과한다.
    broken = os.path.join(CFG_DIR, "broken.json")
    write_cfg(broken)
    doc = json.load(open(broken, encoding="utf-8"))
    doc["legacy"]["root"] = os.path.join(BASE, "nowhere")
    doc["legacy"].pop("treeRoot", None)
    json.dump(doc, open(broken, "w", encoding="utf-8"))
    rc, out, err, s = run(["callers", "fetchRows"], cfg=broken)
    check("검색이 실패하면 0건이 아니라 exit 2",
          rc == 2 and "검색" in err, f"exit={rc}", secs=s)

# ------------------------------------------------------------------ 정리
shutil.rmtree(BASE, ignore_errors=True)
bad = [n for n, ok, _ in results if not ok]
print("-" * 72)
if skipped:
    print(f"건너뜀 {len(skipped)}개 — " + ", ".join(n for n, _ in skipped))
    print("  건너뛴 검사는 통과가 아니다.")
print(f"{len(results) - len(bad)}/{len(results)} 통과"
      + ("" if not bad else "   실패: " + ", ".join(bad)))
sys.exit(1 if bad else 0)
