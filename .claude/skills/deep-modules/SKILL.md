---
name: deep-modules
description: Use when designing a feature, adding a module, or changing anything that crosses a module boundary in this repo — enforces simple interfaces over complex internals, and the split where the user owns boundaries and interfaces while the AI owns what happens inside. Triggers on "which modules will change", "audit my code for shallow modules", or any interface change.
---

# Deep Modules + Interface-Focused Design

A deep module is a simple interface hiding substantial implementation. A shallow
module is an interface almost as complicated as the thing it wraps — it costs more
to learn than it saves.

Depth is the goal. Small module count is not.

## Ownership

| Owned by the **user** | Owned by the **AI** |
|---|---|
| Module boundaries — what exists | Implementation inside a module |
| Interfaces — the public surface | Internal structure and helpers |
| Interface-level tests | Tests for internals (proposed, per `tdd-workflow`) |
| Whether a new module is justified | Spotting shallowness and proposing refactors |

**Do not change a public interface without the user's agreement.** Widening a
signature, adding a parameter, or leaking an internal type outward is a boundary
change, not an implementation detail. Propose it and wait.

Inside a module, work freely.

## Designing a Feature

Ask, in this order:

1. **Which modules will change?**
2. **How will their interfaces change?** — if the answer is "a lot", the boundary
   is probably wrong; say so before writing code.
3. **What interface-level tests do we need?** — these belong to the user.

Name modules and their public functions in `DOMAIN_TERMS.md` vocabulary. A module
named for a concept not in that file is a sign the concept was never pinned down.

## Signs of Shallowness

Raise these when you see them:

- A function that only forwards arguments to one other function
- A caller that must set up internal state before calling, or clean up after
- An interface exposing types the caller shouldn't need to know exist
- A module whose docs must explain internals for the interface to make sense
- Two modules that always change together

## Auditing

On "audit my code for shallow modules": report each candidate with what its
interface currently costs a caller, what it hides, and the specific deepening
change proposed. Rank by what the user gains. Do not refactor until they pick.

## Teaching

The user is learning this way of working, not just using it. Make the reasoning visible.

- **Never propose one interface.** Show two or three shapes it could take, what
  each costs the caller in things they must know, and which you would pick and
  why. The user decides knowing the trade, not just the recommendation.
- **State what is being traded, not just added.** When you want to widen an
  interface or add a parameter, say what the caller now has to understand that
  they did not before. This is the moment depth is won or lost — make it visible
  every time rather than letting the interface drift wider by small steps.
- **Point at the concept in the real code.** When something in the actual repo
  demonstrates depth or shallowness, say so as it comes up. Worked examples from
  their own code beat explanation in the abstract.

## Precedence

This skill is the project-specific way to apply the user's global rules in
`~/.claude/rules/`. Where this skill and a global rule conflict, **this skill wins
for this repo**. Where it is unclear which applies, ask the user — do not choose
silently.
