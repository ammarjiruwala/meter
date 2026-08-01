# Visa Intelligent Commerce (VIC) — Track Rules

> ⚠️ **NOT SOURCED.** The VIC track rules have not been collected. Nothing below is a quoted
> requirement — it's our reading of what we already have, flagged as such.
>
> Someone needs to read the actual rules. We are submitting to this track.

## Owner

Tanay (PLAN.md Phase 0 — "commit … the Visa VIC track rules").

## What we need

- [ ] The official track rules / judging criteria from the organizers
- [ ] Eligibility: does VIC require direct Visa API usage, or does Visa-tokenized payment *via
      Prava* qualify?
- [ ] Any required demo elements or submission fields specific to this track
- [ ] Deadline and submission channel (may differ from the main track)

## Why we think we qualify (unconfirmed)

Our Prava integration is Visa tokenization underneath — see
[`prava/concepts/mandates.md`](./prava/concepts/mandates.md) and
[`prava/concepts/guardrails.md`](./prava/concepts/guardrails.md):

- Cards are tokenized with Visa; we never see a PAN.
- The session flow yields a **16-digit Visa network token** plus a single-use **dynamic CVV**.
- Our mandate flow is delegated authority with hard limits — approved amount, `max_charges`,
  `merchant_scope: listed` — which is the shape of agent-initiated commerce VIC is about.
- **VERIFIED:** an over-cap charge is refused with `THRESHOLD_EXCEEDED`. An agent that gets told
  "no" by the network is the strongest evidence we're inside the rails, not around them.

If the track requires calling Visa APIs directly rather than through Prava, we need to know that
now, not at submission.

## Angle for the pitch (if eligible)

Meter is an autonomous agent spending real money at 3 AM with no human awake. The control isn't a
human approving each charge — it's the mandate envelope the human signed once. The Treasurer can
top up $50/month across listed merchants and *cannot* do anything else. That's the VIC thesis.
