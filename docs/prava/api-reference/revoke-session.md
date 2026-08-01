> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Revoke Session

> Revoke an active payment session

Revoke a payment session before it is used. Revocation is immediate and cannot be undone — a revoked session can no longer collect a card or produce credentials.

`POST /v1/sessions/{id}/revoke` · Authenticated with your secret key.

## Path parameters

<ParamField path="id" type="string" required>
  The `session_id` returned by [Create Session](/api-reference/create-session).
</ParamField>

## Response

<ResponseField name="success" type="boolean">
  Always `true` on successful revocation.
</ResponseField>

## Notes

* Once revoked, the session token can no longer be used for any SDK operations.
* Any in-progress card collection or intent registration (the step that creates the payment's spending
  permission) within the session will fail.
* Revocation is **immediate and irreversible**.

## Error responses

| Status | Code        | Cause                                                        |
| ------ | ----------- | ------------------------------------------------------------ |
| 401    | `AUTH_1001` | Invalid API key                                              |
| 401    | `AUTH_1002` | Missing or invalid Authorization header                      |
| 404    | `NOT_FOUND` | Session not found or doesn't belong to your merchant account |

<RequestExample>
  ```bash cURL theme={null}
  curl -X POST https://sandbox.api.prava.space/v1/sessions/sess_123/revoke \
    -H "Authorization: Bearer sk_test_..."
  ```

  ```python Python theme={null}
  import requests

  resp = requests.post(
      "https://sandbox.api.prava.space/v1/sessions/sess_123/revoke",
      headers={"Authorization": "Bearer sk_test_..."},
  )
  ```

  ```javascript JavaScript theme={null}
  const resp = await fetch("https://sandbox.api.prava.space/v1/sessions/sess_123/revoke", {
    method: "POST",
    headers: {
      Authorization: "Bearer sk_test_...",
    },
  });
  ```
</RequestExample>

<ResponseExample>
  ```json 200 Success theme={null}
  { "success": true }
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
