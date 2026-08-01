---
title: Protocol Selection | API Docs
description: Choose between iMessage, RCS, and SMS for message delivery.
---

The Linq API supports sending messages via iMessage, RCS, and SMS. You can let the API automatically select the best protocol or explicitly choose one. See the [Create Chat](/api/resources/chats/methods/create/index.md) API reference for the full specification.

## Automatic selection (default)

When `preferred_service` is omitted, the API uses the full fallback chain: **iMessage → RCS → SMS**.

## Explicit protocol selection

Use `preferred_service` inside the `message` object to control which protocol is used:

| Value      | Behavior                                                                             |
| ---------- | ------------------------------------------------------------------------------------ |
| `iMessage` | iMessage only. No fallback — send fails if the recipient is unavailable on iMessage. |
| `RCS`      | RCS if supported, otherwise SMS. Never uses iMessage.                                |
| `SMS`      | RCS if supported, otherwise SMS. Never uses iMessage.                                |

> **`preferred_service` vs `service`:** `preferred_service` is what you requested. The `service` field on the response is what was actually used for delivery.

- [cURL](#tab-panel-97)
- [TypeScript](#tab-panel-98)
- [Python](#tab-panel-99)
- [Go](#tab-panel-100)

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
        "preferred_service": "iMessage",
        "parts": [
          {
            "type": "text",
            "value": "Sent via iMessage only"
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
    preferred_service: "iMessage",
    parts: [
      {
        type: "text",
        value: "Sent via iMessage only",
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
        "preferred_service": "iMessage",
        "parts": [
            {
                "type": "text",
                "value": "Sent via iMessage only",
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
    PreferredService: linq.F("iMessage"),
    Parts: linq.F([]any{
      map[string]any{
        Type: linq.F("text"),
        Value: linq.F("Sent via iMessage only"),
      },
    }),
  }),
})
```

## Protocol capabilities

Not all features are available on every protocol:

| Feature                                                            | iMessage | RCS     | SMS |
| ------------------------------------------------------------------ | -------- | ------- | --- |
| Text messages                                                      | Yes      | Yes     | Yes |
| Images & video                                                     | Yes      | Yes     | MMS |
| Read receipts                                                      | Yes      | Yes     | No  |
| Delivery receipts                                                  | Yes      | Yes     | No  |
| [Typing indicators](/guides/chats/typing-indicators/index.md)      | Yes      | No      | No  |
| [Reactions](/guides/messaging/reactions/index.md) / tapbacks       | Yes      | Yes     | No  |
| [Message effects](/guides/messaging/message-effects/index.md)      | Yes      | No      | No  |
| [Group chats](/guides/chats/group-chats/index.md)                  | Yes      | Yes     | MMS |
| Message threading                                                  | Yes      | No      | No  |
| Rich link previews                                                 | Yes      | Yes     | No  |
| [Voice memos](/guides/messaging/voice-memos/index.md)              | Yes      | Yes     | No  |
| [File attachments](/guides/messaging/attachments/index.md) (100MB) | Yes      | Limited | No  |
| Text decorations                                                   | Yes      | No      | No  |
| [Location sharing](/guides/location-sharing/index.md)              | Yes      | No      | No  |

## When to choose a protocol

- **iMessage** — When you need iMessage-only features like message effects or text decorations. Be aware: delivery fails if the recipient isn’t on iMessage.
- **RCS** — When you want rich messaging on Android (reactions, read receipts, threading) but still want SMS as a fallback.
- **SMS** — Equivalent to RCS in behavior: uses RCS if supported, otherwise SMS. Never iMessage.
- **Omit** — Best for maximum reach. The API picks the richest available protocol automatically.

> **Note:** Use the capability check endpoints to verify recipient support before specifying `iMessage`. See [Capability Checks](/guides/chats/capability-checks/index.md) for details.
