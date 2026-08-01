> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# API Reference

> Server-side REST API for Prava Payments

*Not sure this is the right path? See [Choosing Your Integration](/choosing-your-integration).*

## Overview

The Prava REST API is used for server-side operations: creating sessions, managing cards, retrieving payment results, and reporting status. All server-side requests are authenticated using your **secret key**.

<Warning>
  Never expose your secret key in client-side code, version control, or logs. Use it only in server-to-server requests.
</Warning>

## Base URLs

| Environment    | Base URL                          | Key Prefix  |
| -------------- | --------------------------------- | ----------- |
| **Sandbox**    | `https://sandbox.api.prava.space` | `sk_test_*` |
| **Production** | `https://api.prava.space`         | `sk_live_*` |

<Tip>
  Use the **sandbox** URL with your `sk_test_*` key during development. Switch to the **production** URL with `sk_live_*` when you're ready to go live.
</Tip>

<Note>
  These are the only **API** hosts. [dashboard.prava.space](https://dashboard.prava.space) (developer
  console) and [pay.prava.space](https://pay.prava.space) (agent-owner wallet) are web UIs; never send
  API requests to them.
</Note>

## Authentication

All API requests require a Bearer token using your secret key:

```bash theme={null}
Authorization: Bearer sk_test_xxx
```

## Response Format

All requests and responses are JSON. Monetary amounts are always decimal strings (e.g. `"49.99"`), never numbers. Every response includes an `X-Response-ID` header for debugging:

```
X-Response-ID: resp_a1b2c3d4e5f6
```

Include this ID when contacting support to help trace issues.

## Error Response Format

All errors follow a consistent structure:

```json theme={null}
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": {}
  }
}
```

The `details` field is optional and included for validation errors to specify which fields failed.

### Common Error Codes

| Status | Code            | Description                                      |
| ------ | --------------- | ------------------------------------------------ |
| 401    | `AUTH_1001`     | Invalid API key                                  |
| 400    | `VAL_2001`      | Validation error (check `details` for specifics) |
| 404    | `NOT_FOUND`     | Requested resource not found                     |
| 400    | `INVALID_STATE` | Operation not allowed in current state           |

The full catalog (every code, per endpoint, with recovery steps) is on the
[Errors](/api-reference/errors) page.

## The payment journey

A complete payment is **three API calls and one non-API step**. Nothing else is required:

<Steps>
  <Step title="Create a session — POST /v1/sessions">
    Your backend pins the order: customer, merchant, amount, line items. Returns `session_token` and
    `iframe_url`. → [Create Session](/api-reference/create-session)
  </Step>

  <Step title="The cardholder enters their card (no API call)">
    This step happens on Prava's secure surface, not through the API: redirect the cardholder to the
    `iframe_url` (**hosted**) or mount it in your page with
    [`collectPAN`](/sdk/cards/collect-pan) (**embedded**). Card entry and passkey approval (a biometric
    confirmation on the cardholder's device) happen here. Prava handles authentication, mandate
    registration (the spending permission recorded with the card network), and tokenization (swapping
    the card number for a secure stand-in) for you.
  </Step>

  <Step title="Poll the result — GET /v1/sessions/{sessionId}/payment-result">
    Once the cardholder finishes, this returns the one-time credentials: `token` (virtual card number)
    and `dynamic_cvv`. Use them at the merchant checkout like a normal card.
    → [Get Payment Result](/api-reference/get-payment-result)
  </Step>

  <Step title="Report the outcome — POST /v1/sessions/{sessionId}/report-status">
    Tell Prava whether the checkout succeeded (`APPROVED`) or failed (`DECLINED`) so transaction records
    and the card network stay in sync. → [Report Status](/api-reference/report-status)
  </Step>
</Steps>

### Supporting endpoints

<CardGroup cols={2}>
  <Card title="Revoke Session" icon="ban" href="/api-reference/revoke-session">
    Cancel a session before it's used
  </Card>

  <Card title="List Cards" icon="credit-card" href="/api-reference/list-cards">
    Retrieve a customer's enrolled cards
  </Card>
</CardGroup>
