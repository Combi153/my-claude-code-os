"""Shared config, encoding and scope helpers for the legacy-reading tools.

A legacy PHP checkout is a per-file mix of CP949 and UTF-8. Nothing here may
assume one of them. CP949 (not EUC-KR) is the right legacy codec: it is a
superset, so choosing it costs nothing, while choosing EUC-KR risks a decode
exception that reaches the caller as an empty result.

**이 모듈에는 환경 상수가 없다.** 어느 디렉터리가 어느 서비스이고, 어느 트리가
공용 라이브러리이고, 무엇이 벤더 번들인지는 전부 `.claude/config/workspace.json`
의 `legacy` 절에서 읽는다. 그 파일은 gitignore 되고, 공개 골격은
`workspace.example.json` 이다. 도구가 이 저장소에서 추적될 수 있는 이유가 그것
이고, 훅 둘이 먼저 같은 거래를 했다.

설정을 못 찾으면 도구는 **조용히 좁은 답을 내지 않고 멈춘다.** 이 도구들이 막으려는
실패가 정확히 "못 찾은 것을 없는 것으로 읽는" 것이므로, 설정 부재가 0건으로
위장하는 경로를 열어두면 도구가 자기 목적을 배반한다.
"""
import json
import os
import sys

TEXT_EXT = (".php", ".inc", ".tpl", ".html", ".htm", ".js", ".css", ".txt", ".xml")

CONFIG_REL = os.path.join(".claude", "config", "workspace.json")

# 어느 체크아웃에나 있는 서드파티 이름들. 회사 정보가 아니므로 여기 남는다.
# 체크아웃마다 다른 벤더 트리는 workspace.json 의 `legacy.vendorGlobs` 가 준다.
GENERIC_BUNDLES = [
    "!**/vendor/**", "!**/node_modules/**", "!**/bower_components/**",
    "!**/[Pp][Hh][Pp][Ee]xcel/**", "!**/phpExcel/**", "!**/namo*/**",
    "!**/CodeIgniter*/**", "!**/AdminLTE*/**", "!**/ckeditor/**",
    "!**/sheetjs/**",
]
# Real code, but rarely the answer. Excluded by default and named in the scope
# line so a narrow result is never mistaken for an absent one.
SIDE_GLOBS = [
    "!**/test/**", "!**/tests/**", "!**/old/**", "!**/backup/**",
    "!**/*_bak/**", "!**/*_back/**", "!**/*_del/**", "!**/*_old/**",
]


# ------------------------------------------------------------------ config

def _walk_up_for(start, rel):
    """First ancestor of `start` (inclusive) that contains `rel`."""
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, rel)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def project_dir():
    """The OS checkout that holds `.claude/config/workspace.json`.

    세 곳을 본다 — `CLAUDE_PROJECT_DIR`, 이 파일 자신의 위치에서 위로, 작업
    디렉터리에서 위로. 두 번째가 핵심이다. 이 모듈은 프로젝트의 `.claude/scripts/`
    에 놓이므로 자기 경로가 곧 프로젝트의 답이고, 그래서 호출자는 어디에 서 있든
    절대경로 하나로 이 도구들을 부를 수 있다. 호출자가 매번 기억해야 하는 값은
    도구가 스스로 알 수 있는 값이면 안 된다.
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        d = os.path.abspath(os.path.expanduser(env))
        if os.path.isfile(os.path.join(d, CONFIG_REL)):
            return d
    here = os.path.dirname(os.path.abspath(__file__))
    return _walk_up_for(here, CONFIG_REL) or _walk_up_for(os.getcwd(), CONFIG_REL)


_cfg_cache = None
_cfg_reason = None


def config():
    """The `legacy` section of workspace.json. `{}` when it cannot be read.

    실패 이유는 `config_problem()` 이 갖고 있다. 이유 없는 빈 설정을 돌려주면
    호출자가 "설정이 비었다"와 "설정을 못 찾았다"를 구분할 수 없다.
    """
    global _cfg_cache, _cfg_reason
    if _cfg_cache is not None:
        return _cfg_cache
    root = project_dir()
    if not root:
        _cfg_cache, _cfg_reason = {}, (
            f"{CONFIG_REL} 을 찾지 못했다. 이 도구는 프로젝트의 .claude/scripts/ "
            "안에 있어야 자기 위치로 프로젝트를 찾는다.")
        return _cfg_cache
    path = os.path.join(root, CONFIG_REL)
    try:
        with open(path, encoding="utf-8") as fh:
            lg = json.load(fh).get("legacy") or {}
    except (OSError, ValueError) as exc:
        _cfg_cache, _cfg_reason = {}, f"{path} 를 읽을 수 없다: {exc}"
        return _cfg_cache
    missing = [k for k in ("root", "treeMarker", "services", "primaryService")
               if not lg.get(k)]
    if missing:
        _cfg_cache, _cfg_reason = {}, (
            f"{path} 의 legacy 절에 {', '.join(missing)} 가 없다. "
            "workspace.example.json 의 `_tooling` 항목을 참고해 채워라.")
        return _cfg_cache
    _cfg_cache = lg
    return _cfg_cache


def config_problem():
    """Why `config()` came back empty, or None."""
    config()
    return _cfg_reason


def require_config(tool):
    """Config, or exit with the reason. 좁은 답보다 멈추는 것이 낫다."""
    lg = config()
    if not lg:
        sys.exit(f"{tool}: {config_problem()}")
    return lg


# ------------------------------------------------------------------- scope

def _services():
    return list((config().get("services") or {}).items())


def shared_library():
    """The tree every service loads, relative to treeRoot. `''` if unset."""
    return config().get("sharedLibrary") or ""


def primary_service():
    """(prefix, name) of the service being migrated, or None."""
    lg = config()
    p = lg.get("primaryService")
    if not p:
        return None
    return p, (lg.get("services") or {}).get(p, p)


def bundle_globs():
    """Vendored trees to fold out of a search.

    Generic names are in this module; the checkout's own vendored trees come
    from config. Both are excludes, so a wrong entry costs one folded line
    rather than a hidden answer.
    """
    return GENERIC_BUNDLES + ["!" + g.lstrip("!")
                              for g in (config().get("vendorGlobs") or [])]


def runtime_for_prefix(prefix):
    """{'php': ..., 'image': ..., 'howto': ...} for a service prefix, or None."""
    return (config().get("runtimes") or {}).get(prefix)


# Module-level aliases. 기존 도구들이 상수로 import 하던 이름을 그대로 유지해,
# 설정으로 옮기는 변경이 호출부까지 번지지 않게 한다.
SERVICES = _services()
PHPLIB = shared_library()
SOLE_SERVICE = primary_service()
BUNDLE_GLOBS = bundle_globs()


def checkout_root():
    """The legacy checkout root, verified by `treeMarker`.

    `PHP_LEGACY_ROOT` 가 최우선이다. 다른 체크아웃을 가리켜야 할 때 쓴다. 값이
    가리키는 곳에 마커가 없으면 조용히 무시하지 않고 알린 뒤 설정값으로 넘어간다.
    오타가 "트리 밖에 있다"로 위장하는 것이 이 함수가 막으려는 실패다.
    """
    lg = config()
    marker = lg.get("treeMarker") or ""
    env = os.environ.get("PHP_LEGACY_ROOT")
    if env:
        d = os.path.abspath(os.path.expanduser(env))
        if marker and os.path.isdir(os.path.join(d, marker)):
            return d
        print(f"PHP_LEGACY_ROOT={env} 아래에 {marker or '<treeMarker 미설정>'} "
              "가 없다. 무시하고 설정값을 쓴다.", file=sys.stderr)
    root = lg.get("root")
    if not root:
        return None
    root = os.path.abspath(os.path.expanduser(root))
    if marker and not os.path.isdir(os.path.join(root, marker)):
        print(f"workspace.json 의 legacy.root 아래에 {marker} 가 없다.",
              file=sys.stderr)
        return None
    return root


def tree_root():
    """The source tree root the service prefixes are relative to."""
    lg = config()
    explicit = lg.get("treeRoot")
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    root = checkout_root()
    return os.path.join(root, lg["treeMarker"]) if root else None


def service_of(path, root=None):
    """Which service tree a path belongs to. Returns (prefix, name) or None."""
    root = root or tree_root()
    if not root:
        return None
    rel = os.path.relpath(os.path.abspath(path), root)
    if rel.startswith(".."):
        return None
    for prefix, name in _services():
        if rel == prefix or rel.startswith(prefix + "/"):
            return prefix, name
    return None


def current_service(cwd=None):
    """The service the caller is standing in.

    트리 밖이거나 서비스가 아닌 곳에 서 있으면 이관 대상 서비스로 떨어진다. 이
    OS 는 체크아웃보다 한 단계 위에서 돌고 전역 규칙이 `cd` 를 금지하므로, 그
    경우가 기본이지 예외가 아니다. 호출자가 항상 사용한 범위를 출력하니 이 기본값은
    감춰지지 않는다.
    """
    return service_of(cwd or os.getcwd()) or primary_service()


# ---------------------------------------------------------------- encoding

def detect(data):
    """Return 'ascii' | 'utf-8' | 'cp949' | None (undecodable)."""
    if not data:
        return "ascii"
    if all(b < 0x80 for b in data):
        return "ascii"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        data.decode("cp949")
        return "cp949"
    except UnicodeDecodeError:
        pass
    return None


def read_text(path):
    """Return (text, encoding). Undecodable files fall back to cp949/replace."""
    with open(path, "rb") as fh:
        raw = fh.read()
    enc = detect(raw)
    if enc is None:
        return raw.decode("cp949", "replace"), "unknown"
    return raw.decode("ascii" if enc == "ascii" else enc), enc


def sibling_encoding(path):
    """Dominant non-ascii encoding among neighbouring files.

    Used when the target file is pure ASCII and we are about to add Korean:
    a file should match the encoding of the files around it.
    """
    d = os.path.dirname(os.path.abspath(path))
    counts = {"utf-8": 0, "cp949": 0}
    try:
        names = os.listdir(d)
    except OSError:
        return None
    for name in names[:400]:
        p = os.path.join(d, name)
        if not os.path.isfile(p) or not name.lower().endswith(TEXT_EXT):
            continue
        try:
            with open(p, "rb") as fh:
                enc = detect(fh.read(65536))
        except OSError:
            continue
        if enc in counts:
            counts[enc] += 1
    if counts["utf-8"] == counts["cp949"] == 0:
        return None
    return "utf-8" if counts["utf-8"] >= counts["cp949"] else "cp949"


# ------------------------------------------------------------- work dirs

def state_dir(*parts):
    """A directory under the project's gitignored `.claude/.state/`.

    인덱스와 계측 로그가 여기 산다. 레거시 체크아웃 안에 두면 체크아웃이 다시
    만들어질 때 함께 사라지고, 계측은 오래 두고 값을 재야 의미가 있다. 편집
    작업본은 여기 오지 않는다 — 그것은 회사 소스를 디코드한 사본이므로 공개
    저장소 디렉터리 안이 아니라 트리 안에 남는다.
    """
    root = project_dir()
    if not root:
        return None
    d = os.path.join(root, ".claude", ".state", *parts)
    os.makedirs(d, exist_ok=True)
    return d
