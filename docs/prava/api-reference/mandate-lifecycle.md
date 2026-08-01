> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Pause, Resume & Cancel

> Lifecycle actions for a mandate — suspend, reactivate, or revoke.

Three lifecycle actions change a mandate's status. Each is a `POST` to the mandate by id, takes no body (dashboard callers pass `dashboard_user_id`), and returns the updated [mandate](/api-reference/mandate-list).

`POST /v1/mandates/{id}/pause` · `/resume` · `/cancel` — control-plane operations.

Need to **create** a mandate? Mandate creation is part of the Session APIs — [create a mandate](/api-reference/create-session#mandate-setup) with a `mandate_setup` block on Create Session.

## Endpoints

| Action     | Endpoint                        | Allowed from       | Result                                            |
| ---------- | ------------------------------- | ------------------ | ------------------------------------------------- |
| **Pause**  | `POST /v1/mandates/{id}/pause`  | `active`           | `paused` — no charges until resumed               |
| **Resume** | `POST /v1/mandates/{id}/resume` | `paused`           | `active`                                          |
| **Cancel** | `POST /v1/mandates/{id}/cancel` | `active`, `paused` | `cancelled` (terminal) — stops all future charges |

## Path parameters

<ParamField path="id" type="string" required>The mandate id.</ParamField>

## Response

Returns the updated mandate object (see [List Mandates](/api-reference/mandate-list)).

## Notes

* Legal transitions only: pause from `active`, resume from `paused`, cancel from `active` or `paused`. Any other transition returns `409 MANDATE_INVALID_TRANSITION`.
* `cancel` is terminal and local to Prava — it revokes the authorization so no further charges can be minted. **Past charges are unaffected.**
* Only the mandate's owner can act on it — a mismatched caller gets `403 MANDATE_FORBIDDEN`.
* The same actions are available to owners in the dashboard at [pay.prava.space](https://pay.prava.space) and to agents via [`prava mandate cancel`](/prava-pay/mandates#prava-mandate-cancel) / the [MCP tools](/mcp/tools#mandates).

## Error responses

| Status | Code                         | Cause                                            |
| ------ | ---------------------------- | ------------------------------------------------ |
| 403    | `MANDATE_FORBIDDEN`          | Caller does not own this mandate                 |
| 409    | `MANDATE_INVALID_TRANSITION` | The mandate's current status forbids this action |

<RequestExample>
  ```bash Pause theme={null}
  curl -X POST https://sandbox.api.prava.space/v1/mandates/mdt_123/pause \
    -H "Authorization: Bearer sk_test_..."
  ```

  ```bash Resume theme={null}
  curl -X POST https://sandbox.api.prava.space/v1/mandates/mdt_123/resume \
    -H "Authorization: Bearer sk_test_..."
  ```

  ```bash Cancel theme={null}
  curl -X POST https://sandbox.api.prava.space/v1/mandates/mdt_123/cancel \
    -H "Authorization: Bearer sk_test_..."
  ```

  ```python Python theme={null}
  import requests

  resp = requests.post(
      "https://sandbox.api.prava.space/v1/mandates/mdt_123/pause",
      headers={"Authorization": "Bearer sk_test_..."},
  )
  ```

  ```javascript JavaScript theme={null}
  const resp = await fetch("https://sandbox.api.prava.space/v1/mandates/mdt_123/pause", {
    method: "POST",
    headers: {
      Authorization: "Bearer sk_test_...",
    },
  });
  ```
</RequestExample>

<ResponseExample>
  ```json 200 Success theme={null}
  { "id": "mdt_123", "status": "paused", "state": "available", "merchantScope": "listed", "approvedAmount": "40.00", "currency": "USD" }
  ```

  ```json 403 Forbidden theme={null}
  {
    "error": { "code": "MANDATE_FORBIDDEN", "message": "Caller does not own this mandate" }
  }
  ```

  ```json 409 Invalid Transition theme={null}
  {
    "error": { "code": "MANDATE_INVALID_TRANSITION", "message": "The mandate's current status forbids this action" }
  }
  ```
</ResponseExample>
