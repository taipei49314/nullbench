# nullbench — North Star (stage M5)

> Adopted 2026-09-02 (estate task T-45). This document coordinates the next
> stage. It does not amend the frozen M2 PRD: M5 work ships behind version
> bumps and CHANGELOG entries like everything else.

## One line

nullbench earns its name only when it has completed one real experiment:
**decisions frozen before the draw exists, scored against chance after,
no backfill, verifiable by anyone.**

## Why this, why now (evidence)

1. **The core promise is currently impossible to exercise.** `freeze_period`
   refuses any period not already present in `draws.jsonl`, so every existing
   path (demo, golden path, taiwan ingest) freezes *known* outcomes — replay.
   The `late` flag was always written `False`.
2. **M0–M4 built a tamper-hostile lab that has never run a real experiment.**
   60 + 27 + 6 tests green; vault notary shipped; tripwire pins this repo as a
   judge — all infrastructure, zero prospective freezes.
3. **Estate classification:** independent-verifier line, merging forbidden
   (estate T-13/T-20). Value must come from independent existence, not
   integration. Adding features dilutes; using it proves it.

## The single north-star metric

> **prospective streak** — consecutive periods where the freeze happened while
> the outcome did not yet exist (`outcome_hash = null`, period absent from
> `draws.jsonl` at freeze time), settled after ingest, with seal verify and
> vault verify green. **Target: ≥ 26.**

Proxy events (meter = ledger + vault receipts only, never verbal claims):

- freeze row with `outcome_hash: null` and the period provably absent from
  `draws.jsonl` when frozen
- one contiguous vault receipt per period
- the pre-registered formal look at n = 26 (α = 0.005) completed

Product success does **not** require rejecting H0. A strategy losing to
chance, shown honestly, is the product working.

## Stage exits (M5, 0.9.x lineage)

| Phase | Exit |
|-------|------|
| **M5.0 honesty pass** | Replay freezes labeled (`late=true`); reports warn when freezes are replay; demo/docs say replay; CLAIM_POLICY gains M5 language (0.8.3) — **shipped** |
| **M5.1 prospective freeze** | `freeze --next`: period absent from draws, `outcome_hash` null — enforced by the semantic audit (0.9.0 on master; the 0.9.0 tag is void, never published to PyPI) — **shipped** |
| **M5.2 prospective settle** | settle proves the draw entered `draws.jsonl` *after* the freeze (evidence recorded in the ledger row: `draw_entered_after_freeze`, freeze `line_hash`es, known-draw counts; semantic audit enforces) — **shipped** (no version bump; 0.9.0 tag remains void) |
| **M5.3 cycle command** | `nullbench cycle`: ingest → settle pending → freeze next → notarize → report — **this PR, pending merge; no version bump** |
| **M5.4 first public study** | Taiwan Super Lotto + Lotto649 studies in parallel, formal endpoint pre-registered, receipt every period |
| **M5.5 exit claim** | n=26 look done, end-to-end vault verify green, public report — only then may this repo claim "completed a real prospective experiment" |

## Non-goals (this stage)

- No prediction, ever.
- No agent-decision generalization — `GameSpec` stays k-of-n lottery-shaped;
  revisit only after M5.5.
- No multi-tenant SaaS.
- No download/star chasing — local-first, no telemetry; vanity metrics
  conflict with CLAIM_POLICY.
- No tripwire integration changes — federal pin per estate T-20; re-pinning
  is that repo's decision.

## Process rules

- Claim the estate LEDGER task before touching this repo; remote is the
  single truth.
- Frozen M2 docs change only via version bump + CHANGELOG; CLAIM_POLICY
  amendments accumulate (as the 0.8.0 M4 amendment did).
- tripwire stays pinned v0.8.2 until its own repo decides otherwise.
