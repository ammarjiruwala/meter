---
title: Rate Limits | API Docs
description: Understanding and handling API rate limits.
---

The Linq API enforces rate limits to protect Apple’s ecosystem and prevent automated feedback loops between bots.

## Recommended daily volume

We recommend limiting message volume to a combined total of up to **7,000 inbound and outbound messages per day per line**. Volume north of the recommended range has the potential to degrade performance.

There are no hard caps on daily volume (excluding [sandbox accounts](https://dashboard.linqapp.com/sandbox-signup/)). These recommendations are meant to optimize the performance of your lines. We recommend you control volume via onboarding flows you build on your end.

## Per-phone-pair rate limit

The API enforces a rate limit of **30 messages per 60-second window** for each unique sender–recipient pair. This is designed to prevent automated feedback loops where two numbers (i.e. bots) rapidly exchange messages.

When exceeded, the API returns **HTTP `429`** with a `Retry-After` header (seconds until reset) and [error code `1007`](/error/codes/1xxx/1007/index.md). The same value is also available as `retry_after` in the error body. Hitting this limit almost always means a bug — check for retry loops, duplicate sends, or webhook handlers that inadvertently reply to themselves.

## Sandbox limits

[Sandbox accounts](https://dashboard.linqapp.com/sandbox-signup/) are the exception to the “no hard caps” rule:

- **100 messages per day** — Resets at midnight UTC

## Capability check rate limit

[Capability check](/guides/chats/capability-checks/index.md) endpoints (`/v3/capability/check_imessage` and `/v3/capability/check_rcs`) are also rate-limited to prevent abuse (e.g. using them to enumerate which numbers are on iMessage). Excessive calls return the same **HTTP `429`** with `Retry-After` and [error code `1007`](/error/codes/1xxx/1007/index.md).

Capability checks are limited to 1 per 10 seconds. Cache results briefly (minutes, not days) rather than re-checking the same address on every send — capability is stable over short windows and the cache reduces your risk of hitting this limit.

## Rate limit response

When you hit a rate limit, the API returns HTTP `429 Too Many Requests` with a `Retry-After` header and this body:

```
{
  "success": false,
  "error": {
    "status": 429,
    "code": 1007,
    "message": "Rate limited. Try again in 45 seconds.",
    "retry_after": 45,
    "doc_url": "https://docs.linqapp.com/error/codes/1xxx/1007/"
  },
  "trace_id": "trace_abc123def456"
}
```

The `retry_after` field mirrors the `Retry-After` header and is only present on `429` responses. See [Error Codes](/error/index.md) for the full envelope shape used by all error responses.

## Handling rate limits

On a `429` response, prefer the `Retry-After` header when present; fall back to exponential backoff (e.g. 1s → 2s → 4s) otherwise. Do not retry on `429` more than a few times — keep an upper bound and surface the failure if you keep hitting the wall.

> **Tip:** The official [SDKs](/getting-started/sdks/index.md) handle this automatically with exponential backoff. You only need custom retry logic if you’re calling the API directly.

## Best practices

- **Queue messages** — Use a message queue to control send rate rather than sending as fast as possible
- **Monitor usage** — Track your daily message count to avoid hitting limits unexpectedly
- **Batch wisely** — Space out bulk sends rather than sending all at once
- **Use idempotency keys** — Include an `idempotency_key` field in the message body on retries to prevent duplicates (see [Sending Messages](/guides/messaging/sending-messages#idempotency/index.md))

## Other error codes

Rate limits aren’t the only reason requests can fail. See [Error Codes](/error/index.md) for the complete reference, including infrastructure errors (3xxx) that may also require retry logic. See the [Send Message](/api/resources/chats/subresources/messages/methods/send/index.md) and [Create Chat](/api/resources/chats/methods/create/index.md) API references for endpoint details.
