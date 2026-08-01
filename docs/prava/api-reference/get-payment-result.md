> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Payment Result

> Retrieve payment credentials and transaction status for a session

A polling endpoint: after the cardholder completes card entry and passkey approval on Prava's secure surface, poll it to read the outcome and, when ready, the single-use credentials.

`GET /v1/sessions/{sessionId}/payment-result` · Authenticated with your secret key.

## Path parameters

<ParamField path="sessionId" type="string" required>The session id from [Create Session](/api-reference/create-session).</ParamField>

## Response

<ResponseField name="session_id" type="string" />

<ResponseField name="order_id" type="string | null" />

<ResponseField name="status" type="string">Overall session status: `pending`, `awaiting_result`, `completed`, or `failed`.</ResponseField>

<ResponseField name="transactions" type="object[]">
  <Expandable title="transaction properties">
    <ResponseField name="txn_id" type="string" />

    <ResponseField name="status" type="string">`pending` | `awaiting_result` | `completed` | `failed`.</ResponseField>

    <ResponseField name="line_items" type="object[]">
      <Expandable title="line_item properties">
        <ResponseField name="txn_ref_id" type="string">Line-item reference — pass this to [Report Status](/api-reference/report-status).</ResponseField>

        <ResponseField name="merchant_name" type="string | null" />

        <ResponseField name="merchant_url" type="string | null" />

        <ResponseField name="total_amount" type="string" />

        <ResponseField name="status" type="string" />

        <ResponseField name="token" type="string | null">Virtual card number (network token) your agent uses at checkout. **Only present when `status` is `awaiting_result`.**</ResponseField>
        <ResponseField name="dynamic_cvv" type="string | null">Single-use CVV. **Only present when `status` is `awaiting_result`.**</ResponseField>

        <ResponseField name="expiry_month" type="string | null" />

        <ResponseField name="expiry_year" type="string | null" />

        <ResponseField name="products" type="object[]">
          <Expandable title="product properties">
            <ResponseField name="product_ref_id" type="string" />

            <ResponseField name="external_product_id" type="string | null" />

            <ResponseField name="name" type="string" />

            <ResponseField name="unit_price" type="string" />

            <ResponseField name="quantity" type="number" />
          </Expandable>
        </ResponseField>
      </Expandable>
    </ResponseField>

    <ResponseField name="error" type="object">Present only when the transaction failed: `{ code, message }`.</ResponseField>
  </Expandable>
</ResponseField>

## Notes

* The `token` and `dynamic_cvv` fields contain the virtual card credentials your agent uses at checkout.
* Prava performs a lazy mandate expiry check on every request — expired mandates are reflected in the status.
* After using the credentials at checkout, report the outcome via [Report Status](/api-reference/report-status).

## Error responses

| Status | Code        | Cause                                                        |
| ------ | ----------- | ------------------------------------------------------------ |
| 401    | `AUTH_1001` | Invalid API key                                              |
| 401    | `AUTH_1002` | Missing or invalid Authorization header                      |
| 404    | `NOT_FOUND` | Session not found or doesn't belong to your merchant account |

<RequestExample>
  ```bash cURL theme={null}
  curl "https://sandbox.api.prava.space/v1/sessions/sess_123/payment-result" \
    -H "Authorization: Bearer sk_test_..."
  ```

  ```python Python theme={null}
  import requests

  resp = requests.get(
      "https://sandbox.api.prava.space/v1/sessions/sess_123/payment-result",
      headers={"Authorization": "Bearer sk_test_..."},
  )
  ```

  ```javascript JavaScript theme={null}
  const resp = await fetch("https://sandbox.api.prava.space/v1/sessions/sess_123/payment-result", {
    headers: {
      Authorization: "Bearer sk_test_...",
    },
  });
  ```
</RequestExample>

<ResponseExample>
  ```json 200 Success theme={null}
  {
    "session_id": "sess_123",
    "order_id": "ord_4a1b",
    "status": "awaiting_result",
    "transactions": [
      {
        "txn_id": "txn_1",
        "status": "awaiting_result",
        "line_items": [
          {
            "txn_ref_id": "tli_1",
            "merchant_name": "Acme Store",
            "total_amount": "49.99",
            "status": "awaiting_result",
            "token": "4111111111111111",
            "dynamic_cvv": "123",
            "expiry_month": "12",
            "expiry_year": "2030",
            "products": []
          }
        ]
      }
    ]
  }
  ```

  ```json 401 Unauthorized theme={null}
  {
    "error": { "code": "AUTH_1002", "message": "Missing or invalid Authorization header" }
  }
  ```

  ```json 404 Not Found theme={null}
  {
    "error": { "code": "NOT_FOUND", "message": "Session not found" }
  }
  ```
</ResponseExample>
