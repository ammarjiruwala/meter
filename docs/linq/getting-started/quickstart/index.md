---
title: Quickstart | API Docs
description: Send your first message in under 5 minutes.
---

This guide walks you through sending your first message with the Linq Partner API.

## Prerequisites

Before you begin, make sure you have:

- A **bearer token** from your Linq representative
- At least one **phone number** provisioned on your account
- A recipient phone number in **E.164 format** (e.g., `+15556667777`)

## 1. Set up your coding agent (optional)

The [Linq plugin](/getting-started/ai-agents/index.md) teaches Claude Code or Cursor how Linq works, and gives it a `search_docs` tool and an `execute` tool that runs against your account. Skip this if you’d rather call the API directly — the rest of the guide works either way.

Authenticate once. Both the CLI and the plugin read the same credential:

Terminal window

```
npm install -g @linqapp/cli@latest
linq login --token <your-bearer-token>
```

- [Claude Code](#tab-panel-7)
- [Cursor](#tab-panel-8)

```
/plugin marketplace add linq-team/linq-ai
/plugin install linq@linq-ai
```

Reload with `/reload-plugins`, then confirm with `claude mcp list` — expect `plugin:linq:linq … ✔ Connected`.

Terminal window

```
git clone https://github.com/linq-team/linq-ai
mkdir -p ~/.cursor/plugins/local
rsync -a --exclude .git --exclude node_modules linq-ai/ ~/.cursor/plugins/local/linq/
```

Then run **Developer: Reload Window**.

Now ask for what you want in plain language — `Add Linq messaging to this app, I already have an API key` — and the agent writes the code in the sections below for you. See [AI coding agents](/getting-started/ai-agents/index.md) for Codex, troubleshooting, and what each skill covers.

execute sends real messages

The plugin’s `execute` tool runs against your live account, so a send delivers a real message to a real phone.

Not using the plugin?

Point any LLM or coding agent at [`llms-full.txt`](https://docs.linqapp.com/llms-full.txt) — the complete docs in a single file. See [LLM-friendly docs](/guides/resources/faq#llm-friendly-docs/index.md).

## 2. Install an SDK (optional)

- [TypeScript](#tab-panel-9)
- [Python](#tab-panel-10)
- [cURL](#tab-panel-11)

Terminal window

```
npm install @linqapp/sdk
```

Terminal window

```
pip install linq-python
```

No installation needed — use `curl` from your terminal.

## 3. Send your first message

Create a chat and send a message in a single request:

- [cURL](#tab-panel-12)
- [TypeScript](#tab-panel-13)
- [Python](#tab-panel-14)

Terminal window

```
curl -X POST https://api.linqapp.com/api/partner/v3/chats \
  -H "Authorization: Bearer $LINQ_API_KEY" \
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

```
import LinqAPIV3 from '@linqapp/sdk';


const client = new LinqAPIV3({
  apiKey: process.env.LINQ_API_KEY,
});


const chat = await client.chats.create({
  from: '+12223334444',
  to: ['+15556667777'],
  message: {
    parts: [
      { type: 'text', value: 'Hello from Linq!' }
    ],
  },
});


console.log('Chat created:', chat.id);
console.log('Message ID:', chat.last_message?.id);
```

```
import os
from linq import LinqAPIV3


client = LinqAPIV3(api_key=os.environ["LINQ_API_KEY"])


chat = client.chats.create(
    from_="+12223334444",
    to=["+15556667777"],
    message={
        "parts": [
            {"type": "text", "value": "Hello from Linq!"}
        ]
    },
)


print(f"Chat created: {chat.id}")
print(f"Message ID: {chat.last_message.id}")
```

You’ll receive a response with the chat details and message status:

```
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "is_group": false,
  "last_message": {
    "id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
    "parts": [
      { "type": "text", "value": "Hello from Linq!" }
    ],
    "sent_at": "2026-02-05T19:52:17.219Z",
    "service": "iMessage"
  }
}
```

## 4. Send a follow-up message

Once you have a chat ID, send additional messages to the same conversation:

- [cURL](#tab-panel-15)
- [TypeScript](#tab-panel-16)
- [Python](#tab-panel-17)

Terminal window

```
curl -X POST https://api.linqapp.com/api/partner/v3/chats/{chat_id}/messages \
  -H "Authorization: Bearer $LINQ_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "parts": [
      { "type": "text", "value": "Following up!" }
    ]
  }'
```

```
const message = await client.chats.messages.send(chat.id, {
  parts: [
    { type: 'text', value: 'Following up!' }
  ],
});
```

```
message = client.chats.messages.send(
    chat.id,
    parts=[{"type": "text", "value": "Following up!"}],
)
```

## 5. Set up webhooks

To receive real-time notifications when messages are delivered, read, or received, create a webhook subscription:

- [cURL](#tab-panel-18)
- [TypeScript](#tab-panel-19)
- [Python](#tab-panel-20)

Terminal window

```
curl -X POST https://api.linqapp.com/api/partner/v3/webhook-subscriptions \
  -H "Authorization: Bearer $LINQ_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "https://your-server.com/webhook?version=2026-02-03",
    "subscribed_events": [
      "message.sent",
      "message.received",
      "message.delivered",
      "message.read",
      "message.failed"
    ]
  }'
```

```
const subscription = await client.webhookSubscriptions.create({
  target_url: 'https://your-server.com/webhook?version=2026-02-03',
  subscribed_events: [
    'message.sent',
    'message.received',
    'message.delivered',
    'message.read',
    'message.failed',
  ],
});
```

```
subscription = client.webhook_subscriptions.create(
    target_url="https://your-server.com/webhook?version=2026-02-03",
    subscribed_events=[
        "message.sent",
        "message.received",
        "message.delivered",
        "message.read",
        "message.failed",
    ],
)
```

> **Tip:** If no version is specified, the subscription uses the latest available version at creation time. Pass `?version=YYYY-MM-DD` explicitly to pin a specific payload format. See [Webhooks → Versioning](/guides/webhooks#webhook-versioning/index.md) and [Signature verification](/guides/webhooks#signature-verification/index.md).

## 6. Review your setup with an agent

Copy this prompt into your own AI coding agent to check your integration against Linq’s best practices.

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

Before you scale

[Best Practices](/getting-started/best-practices/index.md) covers the flow behind this audit — contact cards, inbound-first messaging, reply pacing, and opt-out handling.

## Next steps

- [Best Practices](/getting-started/best-practices/index.md) — Patterns for healthy conversations and deliverability
- [AI coding agents](/getting-started/ai-agents/index.md) — Full plugin setup for Claude Code, Cursor, and Codex
- [Sending Messages](/guides/messaging/sending-messages/index.md) — Text, media, threading, and effects
- [Attachments](/guides/messaging/attachments/index.md) — Send images, videos, and documents
- [Webhooks](/guides/webhooks/index.md) — Signature verification and event handling
- [Group Chats](/guides/chats/group-chats/index.md) — Multi-participant conversations
- [Error Codes](/error/index.md) — Troubleshooting API errors
- [API Reference](/api/index.md) — Complete endpoint specification
