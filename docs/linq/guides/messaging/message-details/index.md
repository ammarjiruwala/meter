---
title: Message Details | API Docs
description: Retrieve a single message or every message in a thread.
---

Once a message has been sent, you can fetch its current state by ID or walk an entire reply thread. For sending, editing, deleting, and replying, see [Sending Messages](/guides/messaging/sending-messages/index.md).

## Get a single message

Fetch one message by ID, including its parts, reactions, delivery metadata, and thread pointer. See the [Retrieve Message API reference](/api/resources/messages/methods/retrieve/index.md).

## Get thread messages

Given any message ID in a thread, retrieve the originator and all replies. Threads are built by passing [`reply_to`](/guides/messaging/sending-messages#replying-to-messages/index.md) when sending. If the supplied message isn’t part of a thread, a single-message result is returned. See the [List Messages Thread API reference](/api/resources/messages/methods/list_messages_thread/index.md).

**Query parameters:**

- `cursor` — pagination cursor from the previous response’s `next_cursor`. Omit for the first page.
- `limit` — page size (max 100).
- `order` — `asc` (oldest first, default) or `desc`.

## Related

- [Sending Messages](/guides/messaging/sending-messages/index.md) — post, edit, delete, and reply
- [Reactions](/guides/messaging/reactions/index.md) — the reactions attached to each message part
- [API Reference: Messages](/api/resources/messages/index.md)
