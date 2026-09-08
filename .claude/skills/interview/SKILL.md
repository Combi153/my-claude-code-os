---
name: interview
description: |
  사용자가 `/interview` 로 직접 부를 때만 쓴다. 흐릿한 지시의 이유를 코드와 기록에서 먼저 복원하고, 남는 빈칸만 물어서 실행 가능한 브리프로 만든다.
  스스로 발동하지 않는다. 지시가 모호해 보인다는 판단으로 이 스킬을 꺼내지 말고, 다른 스킬이나 서브에이전트도 이 스킬을 부르지 않는다.
  멈출 시점을 정하는 것은 사용자의 몫이다.
---

# Interview

Recover the *why* behind a hazy instruction before anything gets built — from the record first, from the user only where the record runs out.

## 이 스킬은 사용자만 부른다

Everything else in this repo wants to be triggered. This one does not.

An interview that fires on its own puts an interrogation gate in front of every task, and the cost lands on work that would have been cheaper to just *do* and show. So the judgment "this instruction is too hazy to act on" belongs to the user, not to a description match. If the user did not type `/interview`, do not run it.

No other skill and no subagent dispatches this. It is a front door, not a phase.

## 무엇을 인터뷰하는가

1. An argument was given → interview that instruction.
2. No argument → interview the **user's immediately preceding instruction**. This is the common case: the user said something, saw work about to start, and pulled the brake.
3. Neither exists → ask what they want to do. This is the only question allowed before reading anything.

## 묻기 전에 읽는다

The user invoking this skill is telling you they are not certain what they want either. Asking "왜 하시려는 건가요?" hands the uncertainty straight back and gets nothing. **Form a hypothesis from the record, then let the user knock it down.**

Read, in this order, and stop when the why is recoverable:

- `git log` — commit messages in this repo are Korean prose that states intent, not just a change. `git log --oneline -15 -- <path>` and `git log --grep=<term>` are usually enough to see why something is the way it is.
- `docs/memo.md`, `docs/first-run-retrospective.md` — the user's recorded intentions, doubts, and unresolved questions. An instruction often traces directly back to a line here.
- `docs/legacy-migration-os.md` — decisions and the reasoning behind them.
- The slice ledger and the **"제외" section** of `<docs.root>/slice-candidates.md` (root from `.claude/config/workspace.json`). Proposing something already ruled out is a regression, not a suggestion.
- The conversation so far.

Delegate a wide sweep to `Explore` so the transcript stays readable, but keep the interview itself in the main thread — the dialogue is the point.

Mark every piece of evidence as **확인** (read it, with `file:line`) or **추론** (inferred). A hypothesis presented as a fact cannot be corrected.

## 막힌 층을 짚는다

Haziness sits in one of three places, and treating the wrong one wastes the round:

| 층 | 증상 | 
|---|---|
| **무엇을** | The instruction itself has several readings — "정리해줘" could be refactoring, a screen change, data repair, or documentation |
| **왜** | What to do is clear, the reason for doing it now is not |
| **어떻게** | The reason is clear, several implementations survive it |

**Usually the why decides the what.** Once you know why, "정리" resolves on its own — so go after the why first even when the reading looks like the problem.

Do not hand the reading candidates over as a question. Use them as the instrument for extracting the why:

> "정리"가 (1) 리팩터링 (2) 화면 개편 (3) 데이터 정합성 중 무엇인지에 따라 완전히 다른 일이 됩니다. 직전 커밋이 X 라서 저는 (1)로 읽었습니다.

That one sentence narrows the reading and the reason together, and it is easy to say "아니야" to.

## 짐작을 부정하기 쉽게 내놓는다

- **짐작** — one sentence.
- **근거** — `file:line`, marked 확인/추론.
- **틀렸다면** — what single word from the user would change it.

"모르겠다" is a legitimate answer and must not be pushed back on. It means the why is not recoverable from the user, which is itself a finding — carry it to 실패 결론 below.

## 어떻게 — 옵션으로 준다

Once the why is settled, the remaining fork goes to the user as choices, via `AskUserQuestion`:

- 2–4 options, the recommended one first, labelled `(추천)`.
- Each option's description carries **why you would pick it and what it costs** — that is where the reasoning lives, not in prose above the question.
- Show the options you **discarded**, one line each. A user who sees what you rejected can catch a misreading you cannot.
- At most 3 questions in a round.

**Only options that came out of reading the code.** If the choices read like "빠르게 vs 안전하게", you have not read enough yet — go back.

## 언제 끝나는가

A reason is sufficient when **it eliminates at least one plausible option.** If every option still survives what you have learned, you have background, not a reason — one more round.

Hard cap: **2 rounds.** If it has not narrowed by then, state the assumption you are proceeding under and write the brief anyway. Do not keep asking.

## 출력 — 브리프

Five lines, in the chat. Do not create a document; this skill produces no artifact tree. (The exception: handing off to `legacy-slice` Phase 0, which wants it as a file.)

- **목적** — the why, in one sentence.
- **근거** — 확인/추론 marked.
- **고른 것** — the option, and why it beat the others.
- **버린 것** — one line.
- **안 하는 것** — the scope you are explicitly leaving alone.

That last line carries more weight than the rest. Scope drift is the failure mode this skill exists to prevent.

**Then stop.** Choosing what to do is the whole job here — same rule `slice-scout` follows. The user says go, and the work starts in a fresh turn.

## 인터뷰는 실패로 끝날 수 있다

Success is not "the instruction got specific". It is **the next action is decided** — and these count:

- **복원 불가** — the why is not in the code and not in the user's head. Name *who* to ask and *what* to ask them. For a legacy feature nobody here built, this is the honest answer more often than not.
- **지금 하면 안 된다** — the interview surfaced a reason to not do it, or to do something else first. Say so.

## 금지

1. **파일을 고치지 않는다.** Read only. `/interview` means *not yet*; an interview that edits on the way through has stopped being one.
2. **억지 질문을 만들지 않는다.** If the instruction is already clear, say how you read it and list the assumptions you would otherwise have applied silently — then ask for a go. Surfacing invisible assumptions is worth more than a manufactured question.
3. **일반론 옵션 금지.** See above.
4. **다른 스킬의 일을 하지 않는다.** Picking a slice is `slice-scout`; migrating it is `legacy-slice`; auditing is `boundary-audit`. Hand off with the brief.
