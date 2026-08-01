> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Charge a Mandate

> Mint single-use card credentials against an active mandate — no passkey.

Mint fresh single-use card credentials against an active mandate — **no passkey**. Merchant callers receive plaintext `credentials`; agent callers receive an `encrypted_payload` (credentials encrypted to the agent's public key).

`POST /v1/mandates/{id}/charge` · Authenticated with your secret key (merchants) or Ed25519 signature (agents).

Need to **create** a mandate first? Mandate creation is part of the Session APIs — [create a mandate](/api-reference/create-session#mandate-setup) with a `mandate_setup` block on Create Session.

<Note>
  Charging is available to **merchants** (secret key) and **agents** (Ed25519
  signature). It is deliberately **not** exposed over [MCP](/mcp/tools#mandates).
  See [Mandates](/concepts/mandates) for the model.
</Note>

## Path parameters

<ParamField path="id" type="string" required>The mandate id (from [List Mandates](/api-reference/mandate-list)).</ParamField>

## Body

<ParamField body="amount" type="string" required>
  Charge amount as a decimal string with up to 2 decimals, e.g. `"40.00"`. The per-charge cap is enforced by the card network — an over-cap charge is declined (`THRESHOLD_EXCEEDED`).
</ParamField>

<ParamField body="reference" type="string">
  Idempotency key (max 255). The same mandate id + `reference` returns the original charge (`deduplicated: true`) instead of minting again. Omit it and every call is a distinct charge. A *failed* charge clears its key, so a retry after failure is not deduplicated.
</ParamField>

<ParamField body="purchase_context" type="object[]">
  Optional per-charge product details (exactly one entry, same shape as [Create Session](/api-reference/create-session)). Omit to reuse the mandate's setup context. Currency always comes from the mandate, never the charge.
</ParamField>

## Response

<ResponseField name="mandateId" type="string" />

<ResponseField name="instructionId" type="string" />

<ResponseField name="transactionId" type="string">Pass this to [Report a Mandate Charge](/api-reference/mandate-report).</ResponseField>

<ResponseField name="orderId" type="string" />

<ResponseField name="status" type="string">`awaiting_result` or `failed`.</ResponseField>
<ResponseField name="fetchStatus" type="string">`SUCCESS` or `FAILURE`.</ResponseField>
<ResponseField name="credentials" type="object">Merchant callers: `{ token, dynamicCvv, expiryMonth, expiryYear }`.</ResponseField>
<ResponseField name="encrypted_payload" type="object">Agent callers: `{ ephemeral_public_key, iv, auth_tag, data }`, decrypted client-side.</ResponseField>

<ResponseField name="errorCode" type="string" />

<ResponseField name="errorMessage" type="string">e.g. `THRESHOLD_EXCEEDED` on an over-cap decline.</ResponseField>
<ResponseField name="deduplicated" type="boolean">True when a prior charge with the same `reference` was returned.</ResponseField>

## Notes

* The mandate must be `active`. Charging a non-active mandate returns `409 MANDATE_NOT_ACTIVE`.
* An over-cap charge is a normal outcome: `status: "failed"` with an `errorMessage` such as `THRESHOLD_EXCEEDED`. The amount cap is enforced at the card-network level.
* A charge outside a `listed` mandate's merchant returns `403 MANDATE_MERCHANT_NOT_ALLOWED`.
* After checkout, settle the outcome with [Report a Mandate Charge](/api-reference/mandate-report).

## Error responses

| Status | Code                           | Cause                                                                   |
| ------ | ------------------------------ | ----------------------------------------------------------------------- |
| 400    | `VAL_2001`                     | Missing or invalid `amount`                                             |
| 401    | `AUTH_REQUIRED`                | Missing or invalid credentials                                          |
| 403    | `MANDATE_FORBIDDEN`            | Caller does not own this mandate                                        |
| 403    | `MANDATE_MERCHANT_NOT_ALLOWED` | Listed-scope mandate; the charge names a merchant not on the allow-list |
| 409    | `MANDATE_NOT_ACTIVE`           | Mandate is not `active`                                                 |
| 409    | `NO_INSTRUCTION` / `NO_ORDER`  | Mandate is missing its instruction/order                                |
| 500    | `NO_TOKEN`                     | Credential minting failed                                               |

<RequestExample>
  ```bash cURL theme={null}
  curl -X POST https://sandbox.api.prava.space/v1/mandates/mdt_123/charge \
    -H "Authorization: Bearer sk_test_..." \
    -H "Content-Type: application/json" \
    -d '{ "amount": "40.00", "reference": "invoice_2026_07" }'
  ```

  ```python Python theme={null}
  import requests

  resp = requests.post(
      "https://sandbox.api.prava.space/v1/mandates/mdt_123/charge",
      headers={"Authorization": "Bearer sk_test_..."},
      json={"amount": "40.00", "reference": "invoice_2026_07"},
  )
  ```

  ```javascript JavaScript theme={null}
  const resp = await fetch("https://sandbox.api.prava.space/v1/mandates/mdt_123/charge", {
    method: "POST",
    headers: {
      Authorization: "Bearer sk_test_...",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      amount: "40.00",
      reference: "invoice_2026_07",
    }),
  });
  ```
</RequestExample>

<ResponseExample>
  ```json 200 Success theme={null}
  {
    "mandateId": "mdt_123",
    "instructionId": "ins_1",
    "transactionId": "txn_9",
    "orderId": "ord_9",
    "status": "awaiting_result",
    "fetchStatus": "SUCCESS",
    "credentials": { "token": "4111111111111111", "dynamicCvv": "123", "expiryMonth": "12", "expiryYear": "2030" },
    "deduplicated": false
  }
  ```

  ```json 403 Forbidden theme={null}
  {
    "error": { "code": "MANDATE_FORBIDDEN", "message": "Caller does not own this mandate" }
  }
  ```

  ```json 409 Mandate Not Active theme={null}
  {
    "error": { "code": "MANDATE_NOT_ACTIVE", "message": "Mandate is not active" }
  }
  ```
</ResponseExample>
