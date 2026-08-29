# my-claude-code-os

Assignment repository for the 4-week course "나만의 Claude OS 만들기" (Build Your Own Claude OS).
Each week: build skills, subagents, hooks, and orchestrators, then open a PR from a personal
branch for review.

## The OS being built

An OS that migrates legacy PHP to a new stack (Next / Spring).
It is meant to run against the company codebase.

## This repository is public

The course is unrelated to the company. The OS is meant to be published; company code is not.

`php_legacy/` and `cs-system/` are company repositories checked out inside this directory.
They are gitignored and must stay that way.

- Never move content from `php_legacy/` or `cs-system/` into a tracked file of this repository.
  This covers code as well as internal domains, issue IDs, and people's names.
- Never commit logs or reports produced by running the OS against company code.

## Working rules

1. Every Claude OS file (e.g. markdown under `.claude/`) must live inside this project.
2. Write skills (`SKILL.md`) in English. The frontmatter `description` stays Korean —
   it carries the Korean phrases that trigger the skill.
3. This is a hands-on course. Explain the reasoning while working, so the collaboration
   itself is something to learn from.
