---
title: Key Concepts | API Docs
description: The core resources and vocabulary of the Linq Partner API V3.
---

This page is the shared vocabulary every other guide builds on. Read it once, then skim the linked guides for depth.

## Handles

A **handle** is an addressable endpoint — a phone number in E.164 format (`+14155551234`) or an email address (`user@example.com`). Handles appear on both sides of a conversation: the `from` handle (one of your provisioned numbers) and the recipient handles in `to`.

Handles carry metadata:

- `service` — `iMessage`, `RCS`, or `SMS` (the protocol the handle is reachable on)
- `is_me` — whether this handle is yours
- `status` — for group participants: `active`, `left`, or `removed`

See [Protocol Selection](/guides/messaging/protocol-selection/index.md) for how handles map to delivery services.

## Phone numbers

Your account is provisioned with one or more **phone numbers** (also called “lines”). Every outbound message is sent `from` one of these numbers. Numbers have a `status` (`ACTIVE` or `FLAGGED`) that is surfaced via the [`phone_number.status_updated`](/guides/webhooks/events#phone-number-events/index.md) webhook. Contact your Linq representative to provision additional numbers.

## Chats

A **chat** is the container for a conversation between one of your numbers and one or more recipient handles. Everything else — messages, reactions, typing indicators, participants — hangs off a chat.

- **Direct message chat** — exactly one recipient
- **Group chat** — two or more recipients (maximum **31** handles in `to`); requires iMessage or RCS. MMS group chats are also supported (see [Group Chats](/guides/chats/group-chats/index.md))

Chats are created via `POST /v3/chats` with an initial message. The same endpoint handles both direct and group conversations — the shape of `to` determines which you get.

## Messages and parts

A **message** belongs to a chat and is composed of an ordered `parts` array. Each part is one of:

- `text` — a string value (up to 10,000 characters)
- `media` — an image, video, document, or audio file, referenced by `url` or pre-uploaded `attachment_id`
- `link` — a URL (up to 2,048 characters) that renders as a rich preview; must be the only part in its message

See [Sending Messages](/guides/messaging/sending-messages/index.md) and [Attachments](/guides/messaging/attachments/index.md) for the full part schemas and limits.

## Attachments

An **attachment** is a pre-uploaded file (up to 100 MB) that you can reference by `attachment_id` across multiple messages. Attachments never expire — reuse them freely. Files under 10 MB can skip pre-upload and be inlined via a public HTTPS `url`. See [Attachments](/guides/messaging/attachments/index.md).

## Services and protocols

Linq unifies three messaging services behind one API:

| Service      | Carrier-of-record | Notes                                                                          |
| ------------ | ----------------- | ------------------------------------------------------------------------------ |
| **iMessage** | Apple             | Rich features (effects, tapbacks, read receipts, typing, editing, decorations) |
| **RCS**      | Carrier           | Rich features on Android (reactions, read receipts, typing, group chats)       |
| **SMS/MMS**  | Carrier           | Baseline text-and-MMS fallback with the widest reach                           |

The API picks the best service automatically, or you can pin one with `preferred_service`. See [Protocol Selection](/guides/messaging/protocol-selection/index.md) and use the [capability-check endpoints](/guides/messaging/protocol-selection#checking-capability/index.md) to probe a handle before you send.

## Webhooks

**Webhooks** are your real-time feed of what happens after the API returns. You subscribe to a set of event types at a URL you own, and Linq POSTs envelopes with a stable `event_id`, a request-wide `trace_id`, and an event-specific `data` payload.

- At-least-once delivery — deduplicate with `event_id`
- HMAC-SHA256 signed with your webhook secret
- Versioned via `?version=YYYY-MM-DD` in the subscription URL

See [Webhooks](/guides/webhooks/index.md) for signature verification, the [supported event types](/guides/webhooks/events/index.md), and retry policy.

## Trace IDs

Every API response and webhook payload carries a **trace ID** — the W3C Trace Context `trace-id` (32 hex chars). It’s the single handle you use to correlate an API call, its asynchronous delivery lifecycle, and any related support ticket. See [Debugging](/guides/platform/debugging/index.md) for the full correlation pattern.

## Idempotency

Message sends accept an `idempotency_key` field in the message body (max 255 chars). Send the same key on a retry and Linq returns the original response instead of sending twice. See [Sending Messages](/guides/messaging/sending-messages#idempotency/index.md).

## Rate limits

Two independent limits apply:

- **Recommended daily volume:** 7,000 combined inbound+outbound messages per line per day
- **Per-pair burst limit:** 30 messages per 60-second window per unique sender–recipient pair
- **Sandbox accounts:** 100 messages per day

Exceeding a limit returns HTTP 429 with error code `1007`. See [Rate Limits](/guides/platform/rate-limits/index.md).

## Errors

All errors return a JSON body with a numeric `code`, human-readable `message`, HTTP `status`, and a `doc_url` linking directly to the error reference page. A top-level `trace_id` is also included for debugging. Codes are grouped by range (1xxx client, 2xxx resource, 3xxx server, 4xxx delivery, 5xxx file). See [Error Codes](/error/index.md).

## Next steps

- [Quickstart](/getting-started/quickstart/index.md) — send your first message
- [Sending Messages](/guides/messaging/sending-messages/index.md) — parts, effects, decorations, editing
- [Webhooks](/guides/webhooks/index.md) — real-time events
- [API Reference](/api/index.md) — complete endpoint specification
