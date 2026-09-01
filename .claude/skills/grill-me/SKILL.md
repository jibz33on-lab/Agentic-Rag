---
name: grill-me
description: Use before writing any code for a non-trivial feature, and whenever the user says "Start feature:" — interviews the user one question at a time until the design is settled, then writes a short PRD. Blocks all code proposals until the user says "Design is clear."
---

# Grill Me (Design Before Code)

Interview the user about the design until you both share one clear concept. No code until they release you.

## The Rule

**Do not propose, sketch, or write code until the user says exactly: "Design is clear."**

This holds even when the implementation seems obvious to you. An obvious implementation of a misunderstood design is wasted work.

## How to Run the Session

1. **Ask one question at a time.** Wait for the answer before asking the next. Never batch questions into a list — the user cannot think about six things at once, and batching produces shallow answers.
2. **Interview relentlessly.** Keep going until the design is genuinely settled, not until it feels polite to stop. Politeness is not a stopping condition.
3. **Walk each branch of the design tree.** When an answer opens a new decision, follow it down before returning to the trunk.
4. **Resolve dependencies between decisions.** When one choice constrains another, say so explicitly: "Because you chose X, Y is now forced — do you accept that?"
5. **Use the project's vocabulary.** Read `DOMAIN_TERMS.md` at the repo root and use those exact terms throughout the interview. If a needed term is missing or ambiguous, stop and pin it down there before continuing — see the `ubiquitous-language` skill.

## What to Ask About

Cover these before considering the design settled:

- **Purpose** — what problem this solves, and who hits that problem
- **Boundaries** — what is explicitly out of scope for this feature
- **Modules** — which modules change, and how their interfaces change
- **Data** — what comes in, what goes out, what is persisted
- **Failure** — what goes wrong, and what should happen when it does
- **Done** — how we will know it works

## Triggers

Start a session when the user says **"Start feature: \<name\>"**, or when they ask for a non-trivial feature without having designed it.

If you are unsure whether something counts as non-trivial, ask: "Do you want to grill this one, or is it small enough to just build?" Let the user decide — do not skip the session on your own judgment.

## Ending the Session

When the user says **"Design is clear"**, stop asking questions and write a short PRD covering:

- **Problem** — one or two sentences
- **Scope** — what is in, and what is explicitly out
- **Design** — the shared concept you arrived at
- **Interfaces** — modules touched and how their interfaces change
- **Open questions** — anything deliberately deferred

Keep it short enough to read in one sitting. It is a shared record of the decision, not a specification document.

## Teaching

The user is learning this way of working, not just using it. Make the reasoning visible.

- **Say why you are asking, not just what.** Every question comes with the decision
  it feeds and what goes wrong if we guess. "What happens when a source is
  unreachable mid-run?" lands better as "I need to know whether a failed source
  aborts the whole `ingestion_job` or gets skipped, because that decides whether
  the job is restartable."
- **Name the branch you are on.** Say when a question opens a sub-decision and
  when you are returning to the trunk, so the shape of the design tree is visible
  rather than implied.
- **Show what an answer just ruled out.** When a choice closes off alternatives,
  say which ones and why — that is where the real design content is.

## Precedence

This skill is the project-specific way to apply the user's global rules in
`~/.claude/rules/`. Where this skill and a global rule conflict, **this skill wins
for this repo**. Where it is unclear which applies, ask the user — do not choose
silently.
