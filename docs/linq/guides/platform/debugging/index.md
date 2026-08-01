---
title: Debugging | API Docs
description: Using trace IDs for request tracing and troubleshooting.
---

Every API response and webhook payload includes a trace ID for end-to-end debugging. This guide covers how to use trace IDs and troubleshoot common issues. See [Error Codes](/error/index.md) for the complete error reference.

## Trace IDs

Every API response includes a trace ID in the `X-Trace-ID` response header, following the [W3C Trace Context](https://www.w3.org/TR/trace-context/) standard. Error responses and webhook payloads also include `trace_id` in the response body.

Terminal window

```
# The response includes the trace ID header
< X-Trace-ID: 2eff5df5c6f688733c007523c4d61cd9
```

```
{
  "success": false,
  "error": {
    "status": 400,
    "code": 1001,
    "message": "Missing required field",
    "doc_url": "https://docs.linqapp.com/error/codes/1xxx/1001/"
  },
  "trace_id": "2eff5df5c6f688733c007523c4d61cd9"
}
```

## W3C Trace Context

The trace ID is the 32-character hex trace-id segment of the W3C `traceparent` header. Its structure is:

```
traceparent: 00-<trace-id>-<parent-id>-<flags>
             │   │          │          └─ 2-hex flags (e.g. 01 for sampled)
             │   │          └─ 16-hex span/parent ID
             │   └─ 32-hex trace ID (returned as X-Trace-ID)
             └─ version (currently 00)
```

The `trace_id` field in error bodies and webhook envelopes is the same 32-hex value. You can feed it straight into any OpenTelemetry-compatible tracing backend (Datadog, Honeycomb, Jaeger, Grafana Tempo, etc.) to join your spans with Linq’s internal spans — ask support to enable cross-account trace sharing if you need to inspect Linq-side spans.

**Inbound headers are ignored.** Per W3C security guidance for public APIs, the Linq API generates a fresh trace context for every request. Any client-supplied `traceparent` or `tracestate` headers are discarded and replaced. This prevents forged trace IDs and trace-ID collision across tenants.

## Request correlation

To correlate an API request with your own records:

- **Store the returned `X-Trace-ID`** and map it to your internal request/job ID
- **Log both together** so you can cross-reference during support tickets
- **Capture it on webhook receipt too** — the same trace ID flows through downstream `message.sent` / `message.delivered` events

Use `curl -i` (or the equivalent raw-response accessor in your SDK — `response._response.headers` in TypeScript, `client.<resource>.with_raw_response.<method>` in Python) to read the `X-Trace-ID` header from any response:

Terminal window

```
curl -i -X POST https://api.linqapp.com/api/partner/v3/chats \
  -H "Authorization: Bearer $LINQ_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"from":"+12223334444","to":["+15556667777"],"message":{"parts":[{"type":"text","value":"Hello!"}]}}' \
  | grep -i '^x-trace-id:'
```

## Async processing and webhook correlation

Many operations are processed asynchronously after the API responds. The initial HTTP response tells you the request was accepted; the final outcome arrives via [webhooks](/guides/webhooks/index.md).

The `trace_id` threads the full request lifecycle:

1. You call `POST /v3/chats/{id}/messages` → response body and `X-Trace-ID` header carry `trace_id: abc123...`
2. The message is queued and dispatched to Apple/carrier networks
3. You receive a [`message.sent`](/guides/webhooks/events#message-events/index.md) webhook whose envelope `trace_id` matches `abc123...`
4. On delivery, a [`message.delivered`](/guides/webhooks/events#message-events/index.md) webhook — same `trace_id`
5. On read, [`message.read`](/guides/webhooks/events#message-events/index.md) — same `trace_id`
6. On failure, a [`message.failed`](/guides/webhooks/events#message-events/index.md) webhook — same `trace_id` plus the final `code` / `message`

**Recommended pattern:** store the `trace_id` alongside the message in your database at step 1, then key webhook-handler updates off `trace_id` (or `event_id` for deduplication) so late-arriving events always land on the correct record.

> **Note:** Webhook envelope `trace_id` is always present. The inner `data` object may also echo `message_id`, `chat_id`, and `event_id` for more granular joins. Use `event_id` for deduplication, `trace_id` for end-to-end correlation.

## Common issues

| Symptom                                            | Likely cause                                               | Solution                                                                                                                                               |
| -------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `401 Unauthorized`                                 | Missing or invalid bearer token                            | Check `Authorization: Bearer` header — see [Authentication](/getting-started/authentication/index.md)                                                  |
| `400 E.164 format`                                 | Phone number format wrong                                  | Use `+` prefix with country code: `+12223334444` — see [error 1002](/error/codes/1xxx/1002/index.md)                                                   |
| `403 Phone number denied`                          | Phone not assigned to your account                         | Verify phone assignment with your Linq representative                                                                                                  |
| `409 Chat still creating`                          | Duplicate concurrent create requests                       | Wait and retry, or use [idempotency keys](/guides/messaging/sending-messages#idempotency/index.md)                                                     |
| `429 Rate limit`                                   | Per-pair cap, sandbox daily cap, or capability check limit | Wait the `Retry-After` interval, then check for retry loops or missing caching — see [Rate Limits](/guides/platform/rate-limits/index.md)              |
| `5xx Infrastructure`                               | Transient server error                                     | Retry with exponential backoff — see [3xxx server errors](/error#3xxx--server-errors/index.md)                                                         |
| Webhook not received                               | Endpoint unreachable or returning non-2xx                  | Check endpoint URL, SSL cert, and firewall rules — see [Webhooks](/guides/webhooks/index.md)                                                           |
| No `message.delivered` / `message.read` after send | Message fell back to SMS/MMS                               | SMS and MMS don’t support delivery or read receipts — see [Protocol capabilities](/guides/messaging/protocol-selection#protocol-capabilities/index.md) |
| Duplicate webhooks                                 | At-least-once delivery                                     | Deduplicate using `event_id` — see [Webhook delivery](/guides/webhooks#delivery-guarantees/index.md)                                                   |

## Reporting issues

When contacting Linq support, always include:

1. The **trace ID** from the API response
2. The **timestamp** of the request
3. The **endpoint** you called
4. The **response** you received (status code and body)

This allows the support team to look up the exact request in their systems.
