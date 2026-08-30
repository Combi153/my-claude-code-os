---
name: local-stack
description: |
  동등성 루프가 돌 수 있도록 로컬 스택을 띄운다. 레거시 PHP 컨테이너와 새 백엔드(proxy/fixity)를
  기동하고 health 를 확인하며, 마이그레이션 토글을 켜고 끄고 현재 값을 읽는다.
  "로컬 띄워", "스택 기동", "서버 켜줘", "토글 켜/꺼", "지금 어느 경로로 도는지",
  "환경 상태" 등에 트리거.
---

# Local stack

Bring up the environment the equivalence loop runs against, and control the toggle
that decides which backend path is live.

The loop needs the legacy edit to take effect immediately. Running against a shared dev
server would put a deploy inside every iteration and put other people's work at risk,
so the loop runs locally: the containers mount the working copy, so a swap is live the
moment it is written.

## 상수

Read `.claude/config/workspace.json`. Nothing environment-specific belongs in this file.

If `upstreamOs.skillsDir` names an existing directory with the skills listed there,
prefer those for starting the backend — they carry operational detail (VPN
prerequisites, trust stores, port collisions with sibling services) that is not
worth duplicating. Fall back to the direct commands below when they are absent.

## 선행 조건

The containers run locally but the data does not. The legacy runtime and the new
backend both talk to a remote database, and the backend may pull its connection
settings from a remote config service — so network reach to those is a precondition,
not a detail. A stack that boots without it looks healthy and returns nothing, which
costs an hour of debugging the wrong layer.

Check reachability **before** reporting the stack as up: load one legacy page that
requires data, and call one backend endpoint that touches the database. Two green
health endpoints prove only that two processes are listening.

## 기동

**레거시 컨테이너** — `docker compose up -d` in the configured compose dir. The
containers mount the source tree, so no rebuild is needed after a code edit; only a
change to the *environment* requires recreating the container that serves the surface.

**백엔드** — start the data-layer module first, wait for its health endpoint, then the
gateway module. The gateway is wired to the data layer by a configured URL; if a port
was reassigned, that URL moves with it or the gateway comes up healthy and returns
nothing.

Verify each with its health endpoint before reporting up. A process that started is not
a service that works.

## 토글

The toggle is an environment variable per slice, read by the legacy switch helper.
Its naming and values are in `workspace.json` → `legacy.switch`.

Three operations, and all three matter to the loop:

| 동작 | 방법 |
|---|---|
| **읽기** | Ask the running application, not the config file. Config says what should be true; only the process says what is true. |
| **켜기/끄기** | Write the compose env file and recreate the container that serves the surface. |
| **확인** | Read it back after recreating, before running any test. |

**Environment delivery is not uniform.** Different surfaces are served by different
containers, and a PHP-FPM pool may strip environment it was not told to pass through.
So never infer the live value from the file you just wrote — read it back from the
application. A test run against the wrong toggle state produces a confident, wrong
equivalence result, which is worse than a failure.

## 상태

`bash .claude/skills/legacy-slice/status.sh` reports ports, health, running containers,
and known slices. Run it before and after any change here.

## 정리

Leave the toggle **off** at the end of a session unless the user asked otherwise. An
unreviewed code path left live in a service someone else may use tomorrow is not a
default worth having.

Do not stop containers the user did not ask you to stop, and do not kill a process on a
port without showing what is holding it — a sibling service may share the port range.
