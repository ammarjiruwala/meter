> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Report a Mandate Charge

> Settle a mandate charge outcome (APPROVED / DECLINED) with the card network.

Reconcile a mandate charge outcome and settle it with the card network. Call this after checking out with the credentials from [Charge a Mandate](/api-reference/mandate-charge).

`POST /v1/mandates/{id}/charges/{txnId}/report` · Authenticated with your secret key (merchants) or Ed25519 signature (agents).

Need to **create** a mandate? Mandate creation is part of the Session APIs — [create a mandate](/api-reference/create-session#mandate-setup) with a `mandate_setup` block on Create Session.

## Path parameters

<ParamField path="id" type="string" required>The mandate id.</ParamField>
<ParamField path="txnId" type="string" required>The `transactionId` returned from [Charge a Mandate](/api-reference/mandate-charge).</ParamField>

## Body

<ParamField body="txn_status" type="string" required>`APPROVED` or `DECLINED`.</ParamField>
<ParamField body="txn_type" type="string" required>`PURCHASE`.</ParamField>
<ParamField body="authorization_code" type="string">Authorization code from your processor, max 128. Optional; recorded when supplied.</ParamField>
<ParamField body="response_code" type="string">Processor response code, max 2. Optional.</ParamField>
<ParamField body="amount_paid" type="string">Amount paid, decimal string. Optional.</ParamField>

## Response

<ResponseField name="mandateId" type="string" />

<ResponseField name="transactionId" type="string" />

<ResponseField name="orderId" type="string" />

<ResponseField name="status" type="string">`completed` or `failed`.</ResponseField>
<ResponseField name="mandateStatus" type="string">The mandate's status after settlement.</ResponseField>
<ResponseField name="visaConfirmation" type="string">`SUCCESS` or `FAILURE`.</ResponseField>

## Notes

* Reporting a one-time mandate charge as `APPROVED` moves the mandate to `consumed`; recurring mandates stay `active`.
* `authorization_code`, `response_code`, and `amount_paid` are optional and recorded when supplied.

## Error responses

| Status | Code                                                         | Cause                               |
| ------ | ------------------------------------------------------------ | ----------------------------------- |
| 401    | `AUTH_REQUIRED`                                              | Missing or invalid credentials      |
| 403    | `MANDATE_FORBIDDEN`                                          | Caller does not own this mandate    |
| 404    | `MANDATE_NOT_FOUND` / `CHARGE_NOT_FOUND`                     | Mandate or charge not found         |
| 409    | `CHARGE_NOT_REPORTABLE` / `CHARGE_NO_TLI` / `NO_INSTRUCTION` | Charge is not in a reportable state |
| 502    | `VISA_CONFIRMATION_FAILED`                                   | Visa confirmation failed            |
| 500    | `MANDATE_CHARGE_REPORT_DB_FAILED`                            | Persistence failed                  |

<RequestExample>
  ```bash cURL theme={null}
  curl -X POST https://sandbox.api.prava.space/v1/mandates/mdt_123/charges/txn_9/report \
    -H "Authorization: Bearer sk_test_..." \
    -H "Content-Type: application/json" \
    -d '{ "txn_status": "APPROVED", "txn_type": "PURCHASE", "authorization_code": "OK123", "response_code": "00", "amount_paid": "40.00" }'
  ```

  ```python Python theme={null}
  import requests

  resp = requests.post(
      "https://sandbox.api.prava.space/v1/mandates/mdt_123/charges/txn_9/report",
      headers={"Authorization": "Bearer sk_test_..."},
      json={
          "txn_status": "APPROVED",
          "txn_type": "PURCHASE",
          "authorization_code": "OK123",
          "response_code": "00",
          "amount_paid": "40.00",
      },
  )
  ```

  ```javascript JavaScript theme={null}
  const resp = await fetch(
    "https://sandbox.api.prava.space/v1/mandates/mdt_123/charges/txn_9/report",
    {
      method: "POST",
      headers: {
        Authorization: "Bearer sk_test_...",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        txn_status: "APPROVED",
        txn_type: "PURCHASE",
        authorization_code: "OK123",
        response_code: "00",
        amount_paid: "40.00",
      }),
    }
  );
  ```
</RequestExample>

<ResponseExample>
  ```json 200 Success theme={null}
  {
    "mandateId": "mdt_123",
    "transactionId": "txn_9",
    "orderId": "ord_9",
    "status": "completed",
    "mandateStatus": "active",
    "visaConfirmation": "SUCCESS"
  }
  ```

  ```json 404 Not Found theme={null}
  {
    "error": { "code": "CHARGE_NOT_FOUND", "message": "Charge not found" }
  }
  ```

  ```json 409 Not Reportable theme={null}
  {
    "error": { "code": "CHARGE_NOT_REPORTABLE", "message": "Charge is not in a reportable state" }
  }
  ```
</ResponseExample>
