---
title: Error Codes | API Docs
description: Complete reference of Linq API error codes with troubleshooting guides.
---

All API errors return a consistent JSON envelope with a nested `error` object, a `success: false` flag, and a top-level `trace_id` for debugging. The `error` object includes a `doc_url` linking directly to the error code reference page.

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

On `429` responses, `error` also includes a `retry_after` integer (seconds to wait before retrying).

> **Tip:** Always include the `trace_id` from error responses when contacting Linq support. See [Debugging](/guides/platform/debugging/index.md) for more on trace IDs.

## Error code ranges

| Range                                | Category               | Retry?                              |
| ------------------------------------ | ---------------------- | ----------------------------------- |
| [1xxx](#1xxx--clientrequest-errors)  | Client/Request Errors  | No — fix the request                |
| [2xxx](#2xxx--resource-errors)       | Resource Errors        | No — fix auth or resource reference |
| [3xxx](#3xxx--server-errors)         | Server Errors          | Yes — retry with backoff            |
| [4xxx](#4xxx--delivery-errors)       | Delivery Errors        | Sometimes — depends on cause        |
| [5xxx](#5xxx--attachmentfile-errors) | Attachment/File Errors | Sometimes — depends on cause        |

## 1xxx — Client/Request Errors

| Code                                    | Message                              | HTTP | Troubleshooting                                                                                                   |
| --------------------------------------- | ------------------------------------ | ---- | ----------------------------------------------------------------------------------------------------------------- |
| [1001](/error/codes/1xxx/1001/index.md) | Missing required field               | 400  | Check the API docs for the required fields on the endpoint you are calling                                        |
| [1002](/error/codes/1xxx/1002/index.md) | Phone number must be in E.164 format | 400  | Include the country code with a `+` prefix (e.g., `+14155551234` for a US number)                                 |
| [1003](/error/codes/1xxx/1003/index.md) | Invalid request body                 | 400  | Validate your JSON syntax using a linter or validator                                                             |
| [1004](/error/codes/1xxx/1004/index.md) | Invalid message content              | 400  | Ensure the `parts` array contains valid `text`, `media`, or `link` parts                                          |
| [1005](/error/codes/1xxx/1005/index.md) | Invalid parameter value              | 400  | Review the parameter against the API spec to confirm accepted values, formats, and constraints                    |
| [1006](/error/codes/1xxx/1006/index.md) | Cannot update direct message chats   | 409  | Only group chats support updates — verify the chat you are trying to update is a group chat, not a direct message |
| [1007](/error/codes/1xxx/1007/index.md) | Rate limit exceeded                  | 429  | Respect the `Retry-After` interval before retrying the request.                                                   |
| [1008](/error/codes/1xxx/1008/index.md) | Invalid iMessage app message         | 400  | `app.name` is required, and `app.team_id` must be 10 uppercase alphanumeric characters                            |

## 2xxx — Resource Errors

| Code                                    | Message                                              | HTTP | Troubleshooting                                                                                                                |
| --------------------------------------- | ---------------------------------------------------- | ---- | ------------------------------------------------------------------------------------------------------------------------------ |
| [2001](/error/codes/2xxx/2001/index.md) | Chat not found                                       | 404  | Verify the chat ID is a correct UUID returned from `POST /v3/chats` or `GET /v3/chats`                                         |
| [2002](/error/codes/2xxx/2002/index.md) | Message not found                                    | 404  | Verify the message ID is correct                                                                                               |
| [2003](/error/codes/2xxx/2003/index.md) | Attachment not found                                 | 404  | Verify the attachment ID is correct                                                                                            |
| [2004](/error/codes/2xxx/2004/index.md) | Unauthorized                                         | 401  | Include a valid Bearer token in the `Authorization` header (e.g., `Authorization: Bearer your-api-key`)                        |
| [2005](/error/codes/2xxx/2005/index.md) | Access denied                                        | 403  | Verify the resource (chat, attachment, subscription) belongs to your partner account.                                          |
| [2006](/error/codes/2xxx/2006/index.md) | Phone number permission denied                       | 403  | Verify the phone number is assigned to your account                                                                            |
| [2007](/error/codes/2xxx/2007/index.md) | Attachment not ready                                 | 404  | Wait a few seconds and retry the request                                                                                       |
| [2008](/error/codes/2xxx/2008/index.md) | Recipient not allowed                                | 403  | In sandbox mode, recipients must message you first before you can send to them                                                 |
| [2009](/error/codes/2xxx/2009/index.md) | The chat is still being created                      | 409  | Wait a few seconds and retry the request                                                                                       |
| [2010](/error/codes/2xxx/2010/index.md) | Webhook subscription not found                       | 404  | Verify the subscription ID is a correct UUID returned from `POST /v3/webhook-subscriptions` or `GET /v3/webhook-subscriptions` |
| [2011](/error/codes/2xxx/2011/index.md) | Feature not available                                | 403  | Contact support to enable this feature for your account                                                                        |
| [2012](/error/codes/2xxx/2012/index.md) | Contact card not found                               | 404  | Verify the phone number is in E.164 format and matches a line assigned to your account.                                        |
| [2013](/error/codes/2xxx/2013/index.md) | This chat is unavailable                             | 409  | Check the chat status — you cannot interact with or perform actions on a chat after leaving it                                 |
| [2014](/error/codes/2xxx/2014/index.md) | A contact card already exists for this phone number  | 409  | Use `PATCH /v3/contact_card?phone_number={phone_number}` to update the existing card instead of `POST` to create a new one.    |
| [2015](/error/codes/2xxx/2015/index.md) | Operation conflicts with current state               | 409  | Refresh the resource before retrying (e.g., re-fetch the chat or message)                                                      |
| [2016](/error/codes/2xxx/2016/index.md) | Operation not supported in group chats               | 409  | Open the 1:1 chat with the intended recipient and retry there                                                                  |
| [2017](/error/codes/2xxx/2017/index.md) | Operation not supported on this chat’s service type  | 409  | Check `service` on the chat before calling, and retry on a chat whose service supports the operation                           |
| [2018](/error/codes/2xxx/2018/index.md) | iMessage app messages can only be sent over iMessage | 409  | Omit `preferred_service` — it defaults to iMessage for app parts — or set it to `iMessage`                                     |
| [2019](/error/codes/2xxx/2019/index.md) | Phone number not found                               | 404  | Verify the phone number ID against `GET /v3/phone_numbers` — it is the `id` of the line, not the number itself                 |
| [2021](/error/codes/2xxx/2021/index.md) | Payment request not found                            | 404  | Verify the ID against `GET /v3/payment_requests` — it is the `id` from the create response, not the Stripe checkout session    |
| [2022](/error/codes/2xxx/2022/index.md) | Contact card setup failed                            | 500  | Retry the same `POST` or `PATCH /v3/contact_card` call after a few seconds — this is a transient failure, not a bad request    |

## 3xxx — Server Errors

These are transient errors. Retry with exponential backoff (start at 1 second, max 30 seconds). The official [SDKs](/getting-started/sdks/index.md) handle retries automatically.

| Code                                    | Message                            | HTTP | Troubleshooting                                                                    |
| --------------------------------------- | ---------------------------------- | ---- | ---------------------------------------------------------------------------------- |
| [3001](/error/codes/3xxx/3001/index.md) | Server connection error            | 500  | Retry the request after 1-5 seconds                                                |
| [3002](/error/codes/3xxx/3002/index.md) | Server operation failed            | 500  | Retry the request after 1-5 seconds                                                |
| [3003](/error/codes/3xxx/3003/index.md) | Service connection error           | 500  | Retry the request after 1-5 seconds                                                |
| [3004](/error/codes/3xxx/3004/index.md) | Service operation failed           | 500  | Retry the request after 1-5 seconds                                                |
| [3005](/error/codes/3xxx/3005/index.md) | Network timeout                    | 504  | Retry the request after a short delay                                              |
| [3006](/error/codes/3xxx/3006/index.md) | Internal server error              | 500  | If the error persists, contact support with the `trace_id` from the error response |
| [3007](/error/codes/3xxx/3007/index.md) | Maximum delivery attempts exceeded | 500  | Check recipient availability and try again later                                   |

## 4xxx — Delivery Errors

| Code                                    | Message                                      | HTTP | Troubleshooting                                                                                                                                                                  |
| --------------------------------------- | -------------------------------------------- | ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [4001](/error/codes/4xxx/4001/index.md) | Delivery failed                              | 500  | Try sending the message again                                                                                                                                                    |
| [4002](/error/codes/4xxx/4002/index.md) | Phone not available                          | 500  | Check the status of the sender line in your dashboard.                                                                                                                           |
| [4003](/error/codes/4xxx/4003/index.md) | Webhook delivery failed                      | 500  | Ensure your endpoint is publicly reachable                                                                                                                                       |
| [4004](/error/codes/4xxx/4004/index.md) | Service unavailable                          | 503  | Retry the request after 30 seconds                                                                                                                                               |
| [4005](/error/codes/4xxx/4005/index.md) | Recipient does not support this message type | 422  | Confirm the recipient is iMessage-capable before sending app messages — see the [iMessage capability check](/guides/messaging/protocol-selection#protocol-capabilities/index.md) |

## 5xxx — Attachment/File Errors

| Code                                    | Message                                        | HTTP | Troubleshooting                                                 |
| --------------------------------------- | ---------------------------------------------- | ---- | --------------------------------------------------------------- |
| [5001](/error/codes/5xxx/5001/index.md) | File upload failed                             | 500  | Retry the upload (or the message that contained the attachment) |
| [5002](/error/codes/5xxx/5002/index.md) | File download failed                           | 500  | Ensure the URL is publicly accessible                           |
| [5003](/error/codes/5xxx/5003/index.md) | Failed to generate file URL                    | 500  | Retry the request                                               |
| [5004](/error/codes/5xxx/5004/index.md) | Invalid file type                              | 400  | Supported file types include JPEG, PNG, GIF, MP4, and PDF       |
| [5005](/error/codes/5xxx/5005/index.md) | File too large                                 | 400  | Reduce or compress the file before uploading                    |
| [5006](/error/codes/5xxx/5006/index.md) | Content type mismatch                          | 400  | Ensure the URL extension matches the actual file type           |
| [5007](/error/codes/5xxx/5007/index.md) | Failed to download image from the provided URL | 400  | Ensure the URL is publicly accessible and returns a valid image |
