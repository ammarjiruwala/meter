> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Report Status

> Report payment execution outcome back to Prava

Report the payment execution outcome back to Prava. Always report after you attempt the charge with the credentials — it updates transaction records and relays the outcome to the card network.

`POST /v1/sessions/{sessionId}/report-status` · Authenticated with your secret key.

<Note>
  **Always report status** after checkout execution. Report `DECLINED` if a payment token was used but checkout failed.
</Note>

## Path parameters

<ParamField path="sessionId" type="string" required>The session id from [Create Session](/api-reference/create-session).</ParamField>

## Body

<ParamField body="txn_ref_id" type="string" required>The line-item reference from [Get Payment Result](/api-reference/get-payment-result).</ParamField>
<ParamField body="txn_status" type="string" required>`APPROVED` or `DECLINED`.</ParamField>
<ParamField body="txn_type" type="string" default="PURCHASE">Transaction type.</ParamField>
<ParamField body="authorization_code" type="string">Authorization code from your processor, max 128 chars.</ParamField>
<ParamField body="response_code" type="string">Processor response code, max 2 chars (e.g. `"00"` for approved).</ParamField>
<ParamField body="amount_paid" type="string">Override the total paid, if different from the original.</ParamField>

<ParamField body="product_statuses" type="object[]">
  Optional per-product status overrides; informational (the overall mandate status follows `txn_status`).

  <Expandable title="product_statuses[] properties">
    <ParamField body="status" type="string" required>`COMPLETED`, `FAILED`, `CANCELED`, `INPROGRESS`, `PENDING`, or `ONHOLD`.</ParamField>
    <ParamField body="product_id" type="string">Your external product id, max 50. Provide this **or** `product_ref_id`.</ParamField>
    <ParamField body="product_ref_id" type="string">Prava's internal product ref, max 50. Provide this **or** `product_id`.</ParamField>
    <ParamField body="amount_paid" type="string">Amount paid for this product.</ParamField>
  </Expandable>
</ParamField>

## Response

<ResponseField name="status" type="string">Always `"confirmed"`.</ResponseField>

<ResponseField name="txn_ref_id" type="string" />

<ResponseField name="txn_status" type="string">`APPROVED` or `DECLINED`.</ResponseField>
<ResponseField name="visa_confirmation" type="string">`SUCCESS` or `FAILURE`.</ResponseField>

## Notes

* A mandate is the spending permission created when the cardholder approved the payment. Reporting a **one-time** mandate charge as `APPROVED` consumes the mandate (it can't be reused); a **recurring** mandate stays `active` for future charges. See [Mandates](/concepts/mandates).
* `product_statuses` is optional and informational; the overall mandate status follows `txn_status`.

## Error responses

| Status | Code                       | Cause                                             | Resolution                                      |
| ------ | -------------------------- | ------------------------------------------------- | ----------------------------------------------- |
| 401    | `AUTH_1001`                | Invalid API key                                   | Check your secret key                           |
| 401    | `AUTH_1002`                | Missing or invalid Authorization header           | Include `Authorization: Bearer sk_xxx`          |
| 404    | `NOT_FOUND`                | Session / order / transaction reference not found | Verify the session ID and `txn_ref_id`          |
| 400    | `INVALID_STATE`            | No transaction awaiting payment result            | May already be reported, or not yet ready       |
| 400    | `MANDATE_EXPIRED`          | Mandate has expired                               | Register a new intent                           |
| 400    | `PRODUCT_NOT_FOUND`        | Product not found by the given ID                 | Verify `product_id` or `product_ref_id`         |
| 502    | `VISA_CONFIRMATION_FAILED` | Card network confirmation failed                  | Retry or contact support                        |
| 500    | `REPORT_STATUS_ERROR`      | Internal error                                    | Contact support with the `X-Response-ID` header |

<RequestExample>
  ```bash cURL theme={null}
  curl -X POST https://sandbox.api.prava.space/v1/sessions/sess_123/report-status \
    -H "Authorization: Bearer sk_test_..." \
    -H "Content-Type: application/json" \
    -d '{ "txn_ref_id": "tli_1", "txn_status": "APPROVED", "authorization_code": "OK123", "response_code": "00" }'
  ```

  ```python Python theme={null}
  import requests

  resp = requests.post(
      "https://sandbox.api.prava.space/v1/sessions/sess_123/report-status",
      headers={"Authorization": "Bearer sk_test_..."},
      json={
          "txn_ref_id": "tli_1",
          "txn_status": "APPROVED",
          "authorization_code": "OK123",
          "response_code": "00",
      },
  )
  ```

  ```javascript JavaScript theme={null}
  const resp = await fetch("https://sandbox.api.prava.space/v1/sessions/sess_123/report-status", {
    method: "POST",
    headers: {
      Authorization: "Bearer sk_test_...",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      txn_ref_id: "tli_1",
      txn_status: "APPROVED",
      authorization_code: "OK123",
      response_code: "00",
    }),
  });
  ```
</RequestExample>

<ResponseExample>
  ```json 200 Success theme={null}
  { "status": "confirmed", "txn_ref_id": "tli_1", "txn_status": "APPROVED", "visa_confirmation": "SUCCESS" }
  ```

  ```json 400 Invalid State theme={null}
  {
    "error": { "code": "INVALID_STATE", "message": "No transaction awaiting payment result" }
  }
  ```

  ```json 404 Not Found theme={null}
  {
    "error": { "code": "NOT_FOUND", "message": "Session or txn_ref_id not found" }
  }
  ```
</ResponseExample>
