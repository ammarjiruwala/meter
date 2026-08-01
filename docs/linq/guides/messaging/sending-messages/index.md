---
title: Sending Messages | API Docs
description: How to send text, media, and rich messages with the Linq API.
---

The Linq API lets you send messages containing text, media, or a mix of both across iMessage, RCS, and SMS.

## Starting a conversation

To message a new recipient, create a chat with an initial message. The API creates the conversation and sends the message in a single request:

- [cURL](#tab-panel-121)
- [TypeScript](#tab-panel-122)
- [Python](#tab-panel-123)
- [Go](#tab-panel-124)

Terminal window

```
curl -X POST https://api.linqapp.com/api/partner/v3/chats \
  -H "Authorization: Bearer $LINQ_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
      "from": "+12052535597",
      "to": [
        "+12052532136"
      ],
      "message": {
        "parts": [
          {
            "type": "text",
            "value": "Hello! How can I help you today?"
          }
        ]
      }
    }'
```

```
await client.chats.create({
  from: "+12052535597",
  to: ["+12052532136"],
  message: {
    parts: [
      {
        type: "text",
        value: "Hello! How can I help you today?",
      },
    ],
  },
});
```

```
client.chats.create(
    from_="+12052535597",
    to=["+12052532136"],
    message={
        "parts": [
            {
                "type": "text",
                "value": "Hello! How can I help you today?",
            },
        ],
    },
)
```

```
client.Chats.Create(context.TODO(), linq.ChatNewParams{
  From: linq.F("+12052535597"),
  To: linq.F([]string{"+12052532136"}),
  Message: linq.F(map[string]any{
    Parts: linq.F([]any{
      map[string]any{
        Type: linq.F("text"),
        Value: linq.F("Hello! How can I help you today?"),
      },
    }),
  }),
})
```

A few constraints on this request:

- `from` must be a phone number assigned to your account.
- `to` accepts an array — one recipient for a direct message, multiple for a [group chat](/guides/chats/group-chats/index.md).
- The first outbound message must not contain links. `link` parts and text parts containing URLs are rejected on `POST /v3/chats` — send the initial message without links, then follow up with a [link preview](/guides/messaging/rich-link-previews/index.md) using the returned chat ID.

See the [Create Chat](/api/resources/chats/methods/create/index.md) endpoint for the full request schema.

## Sending to an existing chat

Once you have a chat ID, post follow-up messages directly to it. The request body is a `message` object with a `parts` array — see the [Send Message API reference](/api/resources/chats/subresources/messages/methods/send/index.md) for the full schema and language-specific examples.

## Message parts

Messages use a `parts` array where each part is `text`, `media`, or `link`. You can mix text and media in a single message; link parts must be sent on their own.

**Text part:**

```
{ "type": "text", "value": "Hello!" }
```

**Media part (direct URL):**

```
{
  "type": "media",
  "url": "https://example.com/photo.jpg"
}
```

**Media part (pre-uploaded attachment):**

```
{
  "type": "media",
  "attachment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Link part (rich link preview):**

```
{
  "type": "link",
  "value": "https://linqapp.com"
}
```

**Mixed message (text + image) — full request body:**

```
{
  "message": {
    "parts": [
      { "type": "text", "value": "Check out this photo!" },
      { "type": "media", "url": "https://example.com/photo.jpg" }
    ]
  }
}
```

> **Note:** Media parts reference the file by `url` or `attachment_id`. MIME type is inferred server-side — you do not need to pass a `mime_type` field.

**Limits:**

- Up to **100 parts** per message
- Up to **40 public-URL media parts** per message (pre-uploaded attachments are exempt)
- Text `value` max length: **10,000** characters
- Link `value` (URL) max length: **2,048** characters
- Link parts must be the **only** part in a message — they render as a rich preview on iMessage and RCS
- Consecutive text parts are **not allowed** — separate them with media or send as individual messages

See [Attachments](/guides/messaging/attachments/index.md) for details on sending media files.

## Text decorations

Apply inline styles and animations to character ranges within a text part using the `text_decorations` array. Each decoration specifies a `range: [start, end)` (inclusive–exclusive, measured in UTF-16 code units) and exactly one of `style` or `animation`. Decorations are iMessage-only and ignored on RCS and SMS (see [Protocol Selection](/guides/messaging/protocol-selection/index.md)).

```
{
  "type": "text",
  "value": "Hello world",
  "text_decorations": [
    { "range": [0, 5], "style": "bold" },
    { "range": [6, 11], "animation": "shake" }
  ]
}
```

**Styles:** `bold`, `italic`, `strikethrough`, `underline`

**Animations:** `big`, `small`, `shake`, `nod`, `explode`, `ripple`, `bloom`, `jitter`

Style ranges may overlap (e.g. bold + italic on the same characters), but animation ranges must not overlap with other animations or styles.

## Replying to messages

Thread messages by referencing a specific message ID:

- [cURL](#tab-panel-125)
- [TypeScript](#tab-panel-126)
- [Python](#tab-panel-127)
- [Go](#tab-panel-128)

Terminal window

```
curl -X POST https://api.linqapp.com/api/partner/v3/chats/{chatId}/messages \
  -H "Authorization: Bearer $LINQ_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
      "message": {
        "parts": [
          {
            "type": "text",
            "value": "Great point!"
          }
        ],
        "reply_to": {
          "message_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
          "part_index": 0
        }
      }
    }'
```

```
await client.chats.messages.send({chatId}, {
  message: {
    parts: [
      {
        type: "text",
        value: "Great point!",
      },
    ],
    reply_to: {
      message_id: "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      part_index: 0,
    },
  },
});
```

```
client.chats.messages.send(
    {chat_id},
    message={
        "parts": [
            {
                "type": "text",
                "value": "Great point!",
            },
        ],
        "reply_to": {
            "message_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            "part_index": 0,
        },
    },
)
```

```
client.Chats.Messages.Send(context.TODO(), {chatId}, linq.ChatMessageSendParams{
  Message: linq.F(map[string]any{
    Parts: linq.F([]any{
      map[string]any{
        Type: linq.F("text"),
        Value: linq.F("Great point!"),
      },
    }),
    ReplyTo: linq.F(map[string]any{
      MessageId: linq.F("6ba7b810-9dad-11d1-80b4-00c04fd430c8"),
      PartIndex: linq.F(0),
    }),
  }),
})
```

The `part_index` field is optional — use it to reply to a specific part of a multipart message (0-indexed). To walk a thread after building it, see [Message Details → Get thread messages](/guides/messaging/message-details#get-thread-messages/index.md).

## Message effects

Add iMessage screen or bubble effects (confetti, fireworks, slam, invisible ink, etc.) by including an `effect` object inside `message`. iMessage only — silently ignored on RCS and SMS. See [Message Effects](/guides/messaging/message-effects/index.md) for the full list and an example.

## Protocol selection

Force a specific delivery protocol with `preferred_service` (`iMessage`, `RCS`, or `SMS`) inside `message`. If omitted, the API picks the best available. See [Protocol Selection](/guides/messaging/protocol-selection/index.md) for behavior and tradeoffs.

## Idempotency

Include an `idempotency_key` field inside the `message` object to prevent duplicate sends on retries. It goes inside the `message` body, not as an HTTP header. Maximum length is 255 characters.

- [cURL](#tab-panel-129)
- [TypeScript](#tab-panel-130)
- [Python](#tab-panel-131)
- [Go](#tab-panel-132)

Terminal window

```
curl -X POST https://api.linqapp.com/api/partner/v3/chats/{chatId}/messages \
  -H "Authorization: Bearer $LINQ_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
      "message": {
        "parts": [
          {
            "type": "text",
            "value": "This won't be sent twice"
          }
        ],
        "idempotency_key": "unique-request-id-123"
      }
    }'
```

```
await client.chats.messages.send({chatId}, {
  message: {
    parts: [
      {
        type: "text",
        value: "This won't be sent twice",
      },
    ],
    idempotency_key: "unique-request-id-123",
  },
});
```

```
client.chats.messages.send(
    {chat_id},
    message={
        "parts": [
            {
                "type": "text",
                "value": "This won't be sent twice",
            },
        ],
        "idempotency_key": "unique-request-id-123",
    },
)
```

```
client.Chats.Messages.Send(context.TODO(), {chatId}, linq.ChatMessageSendParams{
  Message: linq.F(map[string]any{
    Parts: linq.F([]any{
      map[string]any{
        Type: linq.F("text"),
        Value: linq.F("This won't be sent twice"),
      },
    }),
    IdempotencyKey: linq.F("unique-request-id-123"),
  }),
})
```

The same applies when creating a chat (`POST /v3/chats`) — the key goes inside the nested `message` object:

```
{
  "from": "+12223334444",
  "to": ["+15556667777"],
  "message": {
    "parts": [{ "type": "text", "value": "Hello" }],
    "idempotency_key": "unique-request-id-123"
  }
}
```

If a message with the same key has already been processed, the API returns the original response instead of sending again.

> **Tip:** Use UUIDs or other globally unique values as idempotency keys, and always set one in production to handle network retries safely. The official [SDKs](/getting-started/sdks/index.md) accept the key via a method option.

## Editing messages

Edit a single text part of a previously sent message by passing `part_index` (0-based) and the new `text`. Only text parts are editable. iMessage only — listen for the [`message.edited`](/guides/webhooks/events#message-events/index.md) webhook to confirm the edit was applied. Editable up to **5 times** within **15 minutes** of the original send. See the [Edit Message API reference](/api/resources/messages/methods/update/index.md).

## Deleting messages

Delete removes a message from Linq’s records but does **not** unsend it — recipients still see the message on their device. See the [Delete Message API reference](/api/resources/messages/methods/delete/index.md).
