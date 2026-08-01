---
title: Introduction | API Docs
description: Integrate iMessage, RCS, and SMS messaging directly into your applications.
---

Still on V2?

Migrate to V3 and unlock delivery receipts, trace IDs, message effects, custom reactions, and more. See the [V2 → V3 migration guide](/guides/resources/migration-v2-to-v3/index.md).

The Linq Partner API is a RESTful API at `https://api.linqapp.com/api/partner/v3` that provides programmatic access to iMessage, RCS, and SMS messaging infrastructure.

> **New to Linq?** Start with the [Quickstart](/getting-started/quickstart/index.md) to send your first message in under 5 minutes, or explore the [API Reference](/api/index.md) for the complete endpoint specification.

Building with an AI agent?

Feed these docs straight to your LLM or coding agent: [`llms-full.txt`](https://docs.linqapp.com/llms-full.txt) is the complete documentation in one file, and [`llms.txt`](https://docs.linqapp.com/llms.txt) is a concise index. More in [LLM-friendly docs](/guides/resources/faq#llm-friendly-docs/index.md).

## Prerequisites

To use the Linq Partner API, you’ll need:

- A **bearer token** provisioned by your Linq representative
- One or more **phone numbers** assigned to your account
- An endpoint URL for receiving **webhooks** (optional but recommended)

For step-by-step setup, see [Quickstart](/getting-started/quickstart/index.md).

## What you can build

The Linq Partner API supports a wide range of messaging use cases:

- **Customer support** — Route conversations, send rich media, and integrate with your support stack
- **Sales engagement** — Personalized outreach with read receipts and delivery tracking
- **Appointment reminders** — Automated notifications with confirmation workflows
- **Order notifications** — Shipping updates, delivery confirmations, and feedback collection
- **AI-powered agents** — Build conversational AI that communicates over iMessage, RCS, and SMS

See [open-source examples](/guides/resources/example/index.md) for real-world implementations.

## Key capabilities

| Feature                | Description                                                                                    |
| ---------------------- | ---------------------------------------------------------------------------------------------- |
| **Unified messaging**  | Send via iMessage, RCS, or SMS from a single API with automatic or explicit protocol selection |
| **Rich media**         | Share images, videos, documents, voice memos, and contact cards up to 100MB                    |
| **Group chats**        | Create and manage group conversations with participant controls                                |
| **Message threading**  | Reply to specific messages within a conversation                                               |
| **Reactions**          | Add built-in tapbacks or any custom Unicode emoji to messages                                  |
| **Message effects**    | Confetti, fireworks, slam, gentle, invisible ink, and more (iMessage)                          |
| **Typing indicators**  | Show and receive real-time typing status                                                       |
| **Real-time webhooks** | Instant notifications for delivery, read receipts, reactions, and incoming messages            |
| **Built-in debugging** | W3C trace IDs on every request for end-to-end observability                                    |

## Authentication

All requests require a bearer token in the `Authorization` header:

```
Authorization: Bearer YOUR_TOKEN
```

For details on token management and security best practices, see [Authentication](/getting-started/authentication/index.md).

## Quick example

Send a message with a single API call:

Terminal window

```
curl -X POST https://api.linqapp.com/api/partner/v3/chats \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "from": "+12223334444",
    "to": ["+15556667777"],
    "message": {
      "parts": [
        { "type": "text", "value": "Hello from Linq!" }
      ]
    }
  }'
```

## Handle formats

- **Phone numbers** must be in E.164 format: `+12223334444`
- **Email addresses** use standard format: `user@example.com`
- No spaces, dashes, or parentheses in phone numbers

## Next steps

Quickstart

Send your first message in under 5 minutes. [Get started →](/getting-started/quickstart/index.md)

Sending Messages

Text, media, threading, effects, and protocol selection. [Learn more →](/guides/messaging/sending-messages/index.md)

Webhooks

Real-time event notifications with signature verification. [Set up webhooks →](/guides/webhooks/index.md)

API Reference

Complete endpoint specification with request and response schemas. [View reference →](/api/index.md)

Client SDKs

Official TypeScript and Python SDKs with type safety and automatic retries. [Install SDKs →](/getting-started/sdks/index.md)

Error Codes

Complete error reference with troubleshooting guidance. [View errors →](/error/index.md)
