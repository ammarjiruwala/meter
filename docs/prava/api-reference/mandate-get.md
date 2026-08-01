> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Get a Mandate

> Retrieve one mandate with its balance and full charge history.

Retrieve one mandate with its derived balance and full charge history.

`GET /v1/mandates/{id}` · Authenticated with your secret key.

Need to **create** a mandate? Mandate creation is part of the Session APIs — [create a mandate](/api-reference/create-session#mandate-setup) with a `mandate_setup` block on Create Session.

## Path parameters

<ParamField path="id" type="string" required>The mandate id.</ParamField>

## Response

Everything in the [List Mandates](/api-reference/mandate-list) mandate object, plus:

<ResponseField name="spent" type="string">Cumulative amount charged.</ResponseField>

<ResponseField name="chargeCount" type="integer" />

<ResponseField name="charges" type="object[]">
  <Expandable title="charge properties">
    <ResponseField name="transactionId" type="string" />

    <ResponseField name="amount" type="string" />

    <ResponseField name="currency" type="string" />

    <ResponseField name="status" type="string" />

    <ResponseField name="reference" type="string | null">Idempotency reference supplied at charge time.</ResponseField>

    <ResponseField name="createdAt" type="string" />
  </Expandable>
</ResponseField>

## Error responses

| Status | Code                | Cause                            |
| ------ | ------------------- | -------------------------------- |
| 401    | `AUTH_REQUIRED`     | Missing or invalid credentials   |
| 403    | `MANDATE_FORBIDDEN` | Caller does not own this mandate |
| 404    | `MANDATE_NOT_FOUND` | No such mandate                  |

<RequestExample>
  ```bash cURL theme={null}
  curl "https://sandbox.api.prava.space/v1/mandates/mdt_123" \
    -H "Authorization: Bearer sk_test_..."
  ```

  ```python Python theme={null}
  import requests

  resp = requests.get(
      "https://sandbox.api.prava.space/v1/mandates/mdt_123",
      headers={"Authorization": "Bearer sk_test_..."},
  )
  ```

  ```javascript JavaScript theme={null}
  const resp = await fetch("https://sandbox.api.prava.space/v1/mandates/mdt_123", {
    headers: {
      Authorization: "Bearer sk_test_...",
    },
  });
  ```
</RequestExample>

<ResponseExample>
  ```json 200 Success theme={null}
  {
    "id": "mdt_123",
    "status": "active",
    "approvedAmount": "40.00",
    "currency": "USD",
    "spent": "40.00",
    "chargeCount": 1,
    "charges": [
      { "transactionId": "txn_9", "amount": "40.00", "currency": "USD", "status": "completed", "reference": "invoice_2026_07", "createdAt": "2026-07-26T00:00:00Z" }
    ]
  }
  ```

  ```json 403 Forbidden theme={null}
  {
    "error": { "code": "MANDATE_FORBIDDEN", "message": "Caller does not own this mandate" }
  }
  ```

  ```json 404 Not Found theme={null}
  {
    "error": { "code": "MANDATE_NOT_FOUND", "message": "No such mandate" }
  }
  ```
</ResponseExample>
