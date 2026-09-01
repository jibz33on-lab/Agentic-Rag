---
name: tdd-workflow
description: Use for every feature or bugfix in this repo, before writing implementation code — the AI proposes a failing test first, the user reviews it, and only then does implementation begin. Triggers on "propose the first test", "help me implement just enough", or any request to build or change behaviour.
---

# TDD as an AI Workflow

Tests are the specification. They come first, and the user approves them before
they count.

## Who Does What

This is the part that must not blur:

| Step | Owner |
|------|-------|
| Propose the failing test | **AI** |
| Review and approve the test | **User** |
| Put the approved test in the codebase | **User**, or AI once the user confirms |
| Implement just enough to pass | AI, with the user |
| Refactor while green | AI, with the user |

**The AI proposes tests; it never adopts them unilaterally.** Writing a test into
the repo before the user has agreed to it means the AI has quietly written the
spec. Show the test, wait, then add it.

## The Loop

1. **Propose one failing test.** One behaviour, not a suite. Show it and stop.
2. **Wait for the user's review.** They may correct the behaviour, the name, or
   the level it sits at. Their correction is the specification changing — take it
   as given.
3. **Get it into the codebase.** The user adds it, or the AI adds it after an
   explicit confirmation.
4. **Watch it fail.** Run it. A test that passes before implementation is testing
   nothing — say so and fix the test.
5. **Implement the minimum to make it pass.** No extra features, no speculative
   generality.
6. **Refactor while green.** Run tests after each change.
7. **Repeat for the next small behaviour.**

## Naming

Test names state the behaviour, in `DOMAIN_TERMS.md` vocabulary:
`returns_empty_list_when_no_chunk_matches_query`, not `test_retrieval_2`.

Arrange-Act-Assert inside the body.

## Coverage

CI fails under 80% (`uv run pytest --cov`). Treat that as the floor, not the
goal — the loop above is what produces coverage; chasing the number directly
produces tests that assert nothing.

## Relationship to Other Skills

`deep-modules` decides *what level* a test sits at: the user owns interface-level
tests, so a proposed test that crosses a module boundary needs their sign-off on
the interface first. When a proposed test would require changing an interface,
stop and raise it rather than reshaping the interface to suit the test.

## Teaching

The user is learning this way of working, not just using it. Make the reasoning visible.

- **Every proposed test comes with its argument.** State the behaviour it pins
  down and what would silently break without it. A test the user cannot justify
  is a test they cannot maintain.
- **Say what the test does not cover.** Name the neighbouring cases deliberately
  left for later, so the gaps are chosen rather than forgotten.
- **Explain the level you chose.** Say whether this is an interface-level test or
  an internal one, and why it belongs there — that is the `deep-modules`
  ownership split showing up in practice.
- **When a test fails, explain the failure before fixing it.** The error message
  is the lesson; jumping to a fix skips it.

## Precedence

This skill is the project-specific way to apply the user's global rules in
`~/.claude/rules/` (including `testing.md`). Where this skill and a global rule
conflict, **this skill wins for this repo**. Where it is unclear which applies,
ask the user — do not choose silently.
