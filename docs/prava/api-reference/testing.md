> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Testing in Sandbox

> How to exercise the full payment flow in sandbox before going live.

Sandbox is **self-serve**: sign up at [dashboard.prava.space](https://dashboard.prava.space), create
`pk_test_*`/`sk_test_*` keys, and you can create sessions immediately against
`https://sandbox.api.prava.space`.

## Health check

Confirm connectivity before anything else:

```bash theme={null}
curl https://sandbox.api.prava.space/health
# → { "status": "ok", "timestamp": "…" }
```

## Test cards

Test card numbers and the test OTP live on their own reference page, organized by card network:
[Test Cards](/api-reference/test-cards).

## What behaves differently in sandbox

| Area           | Sandbox behavior                                                                                                                       |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **Charges**    | No real money moves; the card network runs in test mode                                                                                |
| **Card entry** | The secure surface is served from `sandbox.collect.prava.space`                                                                        |
| **Passkeys**   | Real WebAuthn prompts: you'll use actual Touch ID / Face ID / a security key. Supported: Chrome 80+, Safari 14+, Firefox 80+, Edge 80+ |
| **Sessions**   | Same 15-minute expiry as production                                                                                                    |
| **Keys**       | Only `sk_test_*` / `pk_test_*` work on the sandbox host                                                                                |

<Note>
  **Prava Pay (CLI) has no separate sandbox host.** The CLI talks to the live API; agent-linked
  payments use real cards. Sandbox environments apply to the **SDK/API integration path**.
</Note>

## A full sandbox test run

1. [Create a session](/api-reference/create-session) with your `sk_test_*` key.
2. Open the returned `iframe_url` (hosted) or mount [`collectPAN`](/sdk/cards/collect-pan) (embedded)
   and enter a [test card](/api-reference/test-cards).
3. Approve with a passkey when prompted.
4. Poll [Get Payment Result](/api-reference/get-payment-result) until `status` is `awaiting_result`;
   the line items now carry `token` + `dynamic_cvv`.
5. [Report Status](/api-reference/report-status) with `APPROVED` or `DECLINED`.
6. Verify the final state: payment result `status` becomes `completed` (or `failed`).

Anything unexpected? Check [Errors](/api-reference/errors).
