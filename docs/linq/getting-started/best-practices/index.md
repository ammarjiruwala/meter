---
title: Best Practices | API Docs
description: Recommended patterns for healthy iMessage conversations using the Linq API.
---

Follow this flow for every new contact to maintain healthy iMessage conversations and optimal deliverability.

## Messaging flow

1. **Set up your contact card** — configure your name and photo via the [Contact Cards](/guides/contact-cards/index.md) endpoints for your numbers. This is a one-time setup per number.
2. **Receive an inbound message first** — wait for the recipient to initiate or respond before sharing your card. See [Sending Messages](/guides/messaging/sending-messages/index.md).
3. **Send an outbound message** — there must be at least one outbound message in the chat before sharing.
4. **Share your contact card** — call the share endpoint so the recipient is prompted to save your name and photo. See [Sharing Contact Card](/guides/chats/share-contact-card/index.md). There’s no confirmation the user saved it, so call the share endpoint once per day after the first outbound activity on that chat — this keeps giving them the option if they dismissed it.
5. **Elicit 3+ responses early** — aim to get at least three replies from a new user as soon as possible to keep the conversation healthy.
6. **Maintain a 1:2 inbound:outbound ratio** — a message reciprocity ratio of 1 inbound for every 2 outbound messages leads to optimal deliverability.
7. **Honor opt-out language** — immediately stop messaging any user who sends stop, unsubscribe, or expresses negative sentiment.

## Tips

DO

- Design for inbound-first messaging
- Space messages naturally
- Make interactions conversational
- Share contact cards early
- Round-robin new users across lines to balance load

DON'T

- Exceed 7,000 messages/day per line
- Include links or media in your first message
- Keep fallback lines dormant
- Bombard non-responders
- Segment Android users to separate lines
- Use iMessage for cold outreach

## Review your setup with an agent

Copy this prompt into your own AI coding agent to check your integration against the guidelines above.

Audit your Linq integration Copy prompt

```
You are auditing a codebase that integrates with the Linq Partner API
(iMessage / RCS / SMS messaging). Verify it follows Linq's best practices for
deliverability, chat health, and line reputation. This is READ-ONLY — do not
change code unless I ask.

Step 1 — Ground yourself in Linq's public docs. Start with the index at
https://docs.linqapp.com/llms.txt, then fetch the pages you need — at minimum
Best Practices, Chat Health, Phone Reputation, Sending Messages, and Webhooks,
plus the /v3 API reference for the endpoints below. (https://docs.linqapp.com/llms-full.txt
has every page in one file, but it is large — prefer the index and targeted
pages.) If you cannot fetch these, stop and tell me rather than auditing from
memory.

Step 2 — Locate the integration. Search the codebase for the Linq base URL
(api.linqapp.com/api/partner), "/v3/" request paths, an official SDK — Node
`@linqapp/sdk`, Python `linq-python` (imported as `linq`), or Go
`github.com/linq-team/linq-go` — and the inbound webhook handler, so you know
where sending, onboarding, and webhook handling live.

Step 3 — Audit against these requirements. Each item is something my code is
supposed to do — confirm whether it actually does, and cite the file and line:

Opt-out (compliance — most important)
- The code should scan every inbound message on the message.received webhook for
  opt-out keywords — STOP, UNSUBSCRIBE, OPTOUT, CANCEL, END, QUIT (exact,
  case-sensitive) — plus any clear "stop messaging me" intent, and a match
  should immediately stop all outbound to that recipient. Linq does not suppress
  these sends for you.
- The code should treat a chat whose health_status is OPTED_OUT as terminal —
  never send — until Linq clears the status. Linq clears it when the recipient
  sends an opt-in keyword (START, OPTIN, or UNSTOP) or keeps replying on the
  chat, so the code should gate on the current health_status rather than
  tracking opt-in keywords itself.

Sending & line selection
- The code should send with POST /v3/messages using `to` and NO `from`. Linq
  then picks the best line, load-balances across your pool, reuses the
  recipient's existing healthy line, and fails over off a flagged line
  automatically (see from_selection.reason in the response).
- The code should NOT call GET /v3/available_number (or pin a fixed `from`)
  before each send — that defeats the automatic load-balancing and failover.

Onboarding new users
- The code should use GET /v3/available_number when onboarding a NEW user, to
  get the best available line (and its vcf_url contact card) to show them — e.g.
  a number or deeplink shown at signup — so new users spread evenly across the
  pool. That is what available_number is for; it is not a per-message call.

Contact card
- The code should create the contact card once per line with
  POST /v3/contact_card (initial setup only — later changes use
  PATCH /v3/contact_card), and share it through the dedicated
  POST /v3/chats/{chatId}/share_contact_card endpoint.
- New contacts should be inbound-first — let the recipient message first. The
  card should be shared only after at least one outbound message exists in the
  chat, and re-shared about once a day, since there's no confirmation the user
  saved it.

Health & reputation gating
- Before sending, the code should check the chat's health_status and the line's
  reputation from GET /v3/phone_numbers, and slow or pause on AT_RISK /
  CRITICAL. It should also handle the phone_number.status_updated webhook to
  react when a line's reputation changes.
- New users should onboard onto HEALTHY lines. The code should NOT migrate users
  off an AT_RISK line to escape the status — improve engagement and let the line
  recover instead.

Engagement & cadence
- Outbound should be built to get replies (aim for 3+ replies early and roughly
  a 1:2 inbound:outbound ratio). When a recipient stops replying, the code
  should slow down and then stop, rather than keep messaging someone who isn't
  responding.

Volume & ramp
- The code should keep each line under ~7,000 messages/day (inbound + outbound).
  That is a performance guideline, not a reputation threshold — steady high
  volume with healthy reply rates is fine.
- The code should not start roughly 50 or more brand-new conversations per line
  in a rolling 24 hours. Check bulk import, list upload, and campaign kickoff
  paths for anything that opens a whole audience at once, and confirm first
  contact is spread across days and across lines.
- The code should ramp a line's daily volume gradually rather than jumping
  several-fold above what that line has recently been sending. Look for
  scheduled or triggered sends that can take a quiet line to a large day in one
  step.

Step 4 — Report:
1. A table: Check | Status (pass / gap / n/a / unknown) | Where (file:line) | Fix.
2. A short action list, highest deliverability and compliance risk first.
Ground every finding in code you actually read. If you cannot determine an item,
mark it unknown rather than guessing.
```
