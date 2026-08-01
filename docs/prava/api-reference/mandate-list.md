> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# List Mandates

> List the standing mandates on an account, with approved and remaining amounts.

List the caller's mandates. Merchant keys pass `customer_id`; control-plane callers (dashboard) scope by `dashboard_user_id` (+ `agent_id`).

`GET /v1/mandates` · Authenticated with your secret key.

Need to **create** a mandate? Mandate creation is part of the Session APIs — [create a mandate](/api-reference/create-session#mandate-setup) with a `mandate_setup` block on Create Session.

## Query parameters

<ParamField query="customer_id" type="string">Filter to one customer — the `external_user_id` (the `user_id` used at session creation) or a `cus_` id.</ParamField>
<ParamField query="standing_only" type="boolean">When `true`, return only standing mandates (exclude the transient per-checkout mandates that every ordinary checkout creates internally).</ParamField>

## Response

<ResponseField name="mandates" type="object[]">
  <Expandable title="mandate properties">
    <ResponseField name="id" type="string">Mandate id (`mdt_…`).</ResponseField>

    <ResponseField name="agentId" type="string" />

    <ResponseField name="customerId" type="string" />

    <ResponseField name="externalUserId" type="string" />

    <ResponseField name="state" type="string">Display-derived usability: `available`, `consumed`, or `expired`.</ResponseField>
    <ResponseField name="status" type="string">`pending`, `active`, `paused`, `consumed`, `cancelled`, or `expired`.</ResponseField>
    <ResponseField name="recurringFrequency" type="string">`one_time`, `weekly`, `monthly`, `yearly`.</ResponseField>
    <ResponseField name="merchantScope" type="string">`any` or `listed`.</ResponseField>

    <ResponseField name="merchantName" type="string" />

    <ResponseField name="approvedAmount" type="string">Authorized per-charge cap.</ResponseField>
    <ResponseField name="remaining" type="string">Remaining spend this window — indicative for display; the enforced ceiling is the amount cap at the card-network level.</ResponseField>

    <ResponseField name="currency" type="string" />

    <ResponseField name="validUntil" type="string | null" />

    <ResponseField name="renewsAt" type="string | null">Next cycle boundary for recurring mandates.</ResponseField>
    <ResponseField name="lastCharge" type="object | null">`{ status, at }`.</ResponseField>

    <ResponseField name="createdAt" type="string" />

    <ResponseField name="updatedAt" type="string" />
  </Expandable>
</ResponseField>

## Notes

* Use the returned `id` with [Get a Mandate](/api-reference/mandate-get), [Charge a Mandate](/api-reference/mandate-charge), or the [lifecycle actions](/api-reference/mandate-lifecycle).

## Error responses

| Status | Code            | Cause                              |
| ------ | --------------- | ---------------------------------- |
| 401    | `AUTH_REQUIRED` | Missing or invalid credentials     |
| 403    | `FORBIDDEN`     | Caller may not list these mandates |

<RequestExample>
  ```bash cURL theme={null}
  curl "https://sandbox.api.prava.space/v1/mandates?customer_id=user_123&standing_only=true" \
    -H "Authorization: Bearer sk_test_..."
  ```

  ```python Python theme={null}
  import requests

  resp = requests.get(
      "https://sandbox.api.prava.space/v1/mandates",
      headers={"Authorization": "Bearer sk_test_..."},
      params={"customer_id": "user_123", "standing_only": "true"},
  )
  ```

  ```javascript JavaScript theme={null}
  const resp = await fetch(
    "https://sandbox.api.prava.space/v1/mandates?customer_id=user_123&standing_only=true",
    {
      headers: {
        Authorization: "Bearer sk_test_...",
      },
    }
  );
  ```
</RequestExample>

<ResponseExample>
  ```json 200 Success theme={null}
  {
    "mandates": [
      {
        "id": "mdt_123",
        "status": "active",
        "state": "available",
        "recurringFrequency": "monthly",
        "merchantScope": "listed",
        "merchantName": "Acme Store",
        "approvedAmount": "40.00",
        "remaining": "40.00",
        "currency": "USD",
        "validUntil": "2027-07-26T00:00:00Z",
        "renewsAt": "2026-08-26T00:00:00Z",
        "lastCharge": null,
        "createdAt": "2026-07-26T00:00:00Z",
        "updatedAt": "2026-07-26T00:00:00Z"
      }
    ]
  }
  ```

  ```json 401 Unauthorized theme={null}
  {
    "error": { "code": "AUTH_REQUIRED", "message": "Missing or invalid credentials" }
  }
  ```

  ```json 403 Forbidden theme={null}
  {
    "error": { "code": "FORBIDDEN", "message": "Caller may not list these mandates" }
  }
  ```
</ResponseExample>
