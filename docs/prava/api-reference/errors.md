> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Errors

> Every error code the Prava API can return — status, cause, and how to recover.

All errors share one envelope:

```json theme={null}
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": {}
  }
}
```

`details` is optional; it's included for validation errors to specify which fields failed. Every response
also carries an `X-Response-ID` header; include it when contacting
[support@prava.space](mailto:support@prava.space).

## Authentication & validation

These can occur on **any** endpoint:

| Status | Code              | Cause                                                       | Recovery                                                                           |
| ------ | ----------------- | ----------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 401    | `AUTH_1001`       | Invalid or missing API key                                  | Use `Authorization: Bearer sk_…` with a valid secret key for the right environment |
| 401    | `AUTH_1002`       | Missing or invalid Authorization header                     | Include the header exactly as `Bearer sk_…`                                        |
| 401    | `AUTH_1003`       | Session has expired                                         | Create a new session                                                               |
| 401    | `AUTH_1004`       | Session has been revoked                                    | Create a new session                                                               |
| 400    | `VAL_2001`        | Request failed schema validation                            | Check `details` for the failing fields                                             |
| 400    | `INVALID_REQUEST` | A required field is missing (e.g. `customer_id`, `card_id`) | Include the named field                                                            |

## Create Session — `POST /v1/sessions`

| Status | Code                    | Cause                                             | Recovery                                                               |
| ------ | ----------------------- | ------------------------------------------------- | ---------------------------------------------------------------------- |
| 429    | `TRIES_EXHAUSTED`       | Your account's session allowance is depleted      | Contact [support@prava.space](mailto:support@prava.space)              |
| 500    | `MERCHANT_LOOKUP_ERROR` | Your merchant account couldn't be resolved        | Retry; if persistent, contact support with the `X-Response-ID`         |
| 500    | `CONFIG_ERROR`          | Merchant account is missing payment configuration | Contact support; this is an account-setup issue, not a request problem |
| 400    | `CARD_NOT_FOUND`        | A pre-selected card doesn't exist                 | Verify via [List Cards](/api-reference/list-cards)                     |
| 400    | `CARD_INACTIVE`         | A pre-selected card is not active                 | Choose an active card                                                  |
| 500    | `SESSION_CREATE_ERROR`  | Internal failure creating the session             | Retry; then support                                                    |

## Payment Result — `GET /v1/sessions/{sessionId}/payment-result`

| Status | Code        | Cause                                                | Recovery                                       |
| ------ | ----------- | ---------------------------------------------------- | ---------------------------------------------- |
| 404    | `NOT_FOUND` | Session not found, or it belongs to another merchant | Verify the session ID and which key created it |

## Report Status — `POST /v1/sessions/{sessionId}/report-status`

| Status | Code                       | Cause                                             | Recovery                                                      |
| ------ | -------------------------- | ------------------------------------------------- | ------------------------------------------------------------- |
| 404    | `NOT_FOUND`                | Session / order / transaction reference not found | Verify the session ID and `txn_ref_id`                        |
| 400    | `INVALID_STATE`            | No transaction awaiting a result                  | It may already be reported, or the cardholder hasn't finished |
| 400    | `MANDATE_EXPIRED`          | The mandate has expired                           | Create a new session                                          |
| 400    | `PRODUCT_NOT_FOUND`        | Product not found by the given ID                 | Verify `product_id` / `product_ref_id`                        |
| 502    | `VISA_CONFIRMATION_FAILED` | Card-network confirmation failed                  | Retry; then support                                           |
| 500    | `REPORT_STATUS_ERROR`      | Internal error                                    | Contact support with the `X-Response-ID`                      |

## Cards — `GET /v1/listCards` · `POST /v1/deleteCard`

| Status | Code                    | Cause                                 | Recovery                                                          |
| ------ | ----------------------- | ------------------------------------- | ----------------------------------------------------------------- |
| 404    | `CUSTOMER_NOT_FOUND`    | No customer for the given identifier  | Verify `customer_id` (the `user_id` you used at session creation) |
| 404    | `NOT_FOUND`             | Card not found (delete)               | Verify `card_id` via [List Cards](/api-reference/list-cards)      |
| 502    | `NETWORK_DELETE_FAILED` | Card-network deletion failed (delete) | Retry                                                             |

## Revoke Session — `POST /v1/sessions/{id}/revoke`

| Status | Code            | Cause                            | Recovery                               |
| ------ | --------------- | -------------------------------- | -------------------------------------- |
| 404    | `NOT_FOUND`     | Session not found                | Verify the session ID                  |
| 400    | `INVALID_STATE` | Session not in a revocable state | It may already be completed or expired |

## Mandates — `/v1/mandates/*`

Mandate routes authenticate with a secret key **or** an agent Ed25519 signature; a missing/invalid credential returns `401 AUTH_REQUIRED`.

| Status | Code                           | Cause                                                                  | Recovery                                                               |
| ------ | ------------------------------ | ---------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| 401    | `AUTH_REQUIRED`                | Missing or invalid credentials                                         | Send a valid secret key or agent signature                             |
| 403    | `MANDATE_FORBIDDEN`            | The caller doesn't own this mandate                                    | Act only on mandates owned by the calling agent/merchant               |
| 403    | `MANDATE_MERCHANT_NOT_ALLOWED` | A charge fell outside a `listed` mandate's merchant                    | Charge only at the mandate's merchant, or use an `any`-scope mandate   |
| 404    | `MANDATE_NOT_FOUND`            | No mandate with that id for the caller                                 | Verify the mandate id via [List Mandates](/api-reference/mandate-list) |
| 409    | `MANDATE_NOT_ACTIVE`           | Charged a mandate that isn't `active` (e.g. paused, consumed, expired) | Resume it, or set up a new mandate                                     |
| 409    | `MANDATE_INVALID_TRANSITION`   | An illegal lifecycle change (e.g. resume a cancelled mandate)          | Only pause `active`, resume `paused`, cancel `active`/`paused`         |
| 409    | `NO_INSTRUCTION` / `NO_ORDER`  | The mandate is missing its underlying instruction/order (charge)       | Re-run mandate setup                                                   |
| 500    | `NO_TOKEN`                     | Credential minting failed (charge)                                     | Retry; then support                                                    |

Reporting a charge (`/charges/{txnId}/report`) can additionally return `404 CHARGE_NOT_FOUND`, `409 CHARGE_NOT_REPORTABLE` / `CHARGE_NO_TLI`, `502 VISA_CONFIRMATION_FAILED`, or `500 MANDATE_CHARGE_REPORT_DB_FAILED`.

<Note>
  `THRESHOLD_EXCEEDED` is **not** a Prava error code — it's a Visa decline (an over-cap charge) surfaced in a failed charge's `errorCode` / `errorMessage`, not in the error envelope. See [Charge a Mandate](/api-reference/mandate-charge).
</Note>

<Note>
  The **SDK** has its own client-side error codes (`SDK_ALREADY_ACTIVE`, `INVALID_CONFIG`,
  `IFRAME_LOAD_ERROR`, `SDK_INIT_ERROR`); see
  [Collect Card Details](/sdk/cards/collect-pan). CLI errors are mapped on the
  [Prava Pay troubleshooting page](/prava-pay/troubleshooting).
</Note>
