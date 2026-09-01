---
name: ubiquitous-language
description: Use at the start of any conversation about this repo, and whenever a domain word appears that could mean two things — loads the shared vocabulary from DOMAIN_TERMS.md and requires those exact terms in conversation, code, comments, tests, and docs. Triggers on "use the terms from DOMAIN_TERMS", "let's clarify this term", or any ambiguous or missing domain word.
---

# Ubiquitous Language (Shared Vocabulary)

One word per concept, used everywhere. `DOMAIN_TERMS.md` at the repo root is the
source of truth.

## The Rule

**Read `DOMAIN_TERMS.md` before naming anything.** Use those exact terms in
conversation, code, comments, tests, docs, and commit messages. Do not invent a
synonym because it reads better in a sentence — a synonym is a second concept as
far as the reader is concerned.

Terms are `snake_case` and double as code identifiers. A `chunk` in conversation
is the `chunk` in the code.

## When a Term Is Missing or Ambiguous

Stop. Do not pick a meaning and carry on — an unstated definition becomes a
permanent inconsistency the moment it reaches code.

1. Say which word is unclear and what the competing readings are.
2. Propose a one-line definition, plus a note on what it is *not*.
3. Get the user's agreement.
4. Add it to `DOMAIN_TERMS.md` before writing code that uses it.

The boundary between two neighbouring terms is where the confusion lives — spend
the words there.

## When the Code and the Terms Disagree

If existing code uses a different name than `DOMAIN_TERMS.md`, that is a defect.
Say so and ask whether to rename the code or amend the term. Do not silently
follow the code.

## Teaching

The user is learning this way of working, not just using it. Make the reasoning visible.

- **Show both readings before proposing one.** When a term is ambiguous, spell out
  each meaning and what it would do to the code downstream — different function
  names, different module boundaries, different tests. Ambiguity is cheap to
  discuss now and expensive to discover in the code later.
- **Say what a definition excludes.** The useful half of a definition is usually
  what it rules out, especially against the neighbouring term.
- **Point at the cost of getting it wrong.** Name the rename that would be needed
  across code, tests and docs if the term shifts meaning later.

## Precedence

This skill is the project-specific way to apply the user's global rules in
`~/.claude/rules/`. Where this skill and a global rule conflict, **this skill wins
for this repo**. Where it is unclear which applies, ask the user — do not choose
silently.
