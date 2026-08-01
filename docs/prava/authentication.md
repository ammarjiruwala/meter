> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Authentication & Environments

> Learn how to authenticate your requests and use Prava environments.

<Note>
  **Two portals, two audiences.** [dashboard.prava.space](https://dashboard.prava.space) is the
  [**developer console**](/dashboard): sign up, create API keys, switch to
  production. [pay.prava.space](https://pay.prava.space) is the
  [**Prava Pay dashboard**](/prava-pay/your-wallet) for agent *owners*: approve agent links, enroll
  cards, set spending controls. A developer integrating the API only needs the console; an agent
  owner only needs the Prava Pay dashboard.
</Note>

## Authentication Model

Prava uses a **dual-key system** with two distinct authentication modes depending on where the request originates.

### Merchant Secret Key (Server-to-Server)

Used for backend operations like creating sessions and listing cards.

* Include the key as a Bearer token: `Authorization: Bearer sk_test_xxx` or `Authorization: Bearer sk_live_xxx`
* **Never** expose secret keys in client-side code, version control, or logs.
* Rotate keys immediately if compromised.

### Publishable Key (Client-Side)

Used to initialize the SDK in the browser.

* Passed during SDK initialization: `new PravaSDK({ publishableKey: 'pk_test_xxx' })`
* Safe to include in frontend code — scoped to client-side operations only.

| Key Type            | Prefix                    | Usage                                          | Location     |
| ------------------- | ------------------------- | ---------------------------------------------- | ------------ |
| **Publishable Key** | `pk_live_*` / `pk_test_*` | Initialize SDK, client-side operations         | Frontend     |
| **Secret Key**      | `sk_live_*` / `sk_test_*` | Create sessions, list cards, server operations | Backend only |

### Session-Based Auth

After creating a session via the backend (`POST /v1/sessions`), the returned `session_token` authenticates all subsequent operations within that session (card collection, transactions, FIDO authentication; FIDO is the standard behind passkeys). Session tokens are:

* **Short-lived**: expire after a configured duration.
* **Single-use**: tied to a specific merchant, customer, and order.
* **Revocable**: can be revoked via `POST /v1/sessions/:id/revoke`.

## Environments

| Environment    | Key Prefix                | Base URL                          | Purpose                 |
| -------------- | ------------------------- | --------------------------------- | ----------------------- |
| **Sandbox**    | `pk_test_*` / `sk_test_*` | `https://sandbox.api.prava.space` | Development and testing |
| **Production** | `pk_live_*` / `sk_live_*` | `https://api.prava.space`         | Live transactions       |

<Note>
  Sandbox is self-serve: start building immediately. Switching to **production** is done from the
  [Prava Dashboard](https://dashboard.prava.space) and may require some additional verification; contact
  [support@prava.space](mailto:support@prava.space) when you're ready to go live.
</Note>

## Response Headers

Every API response includes an `X-Response-ID` header — a unique identifier for that request. Include this ID when contacting support to help us trace issues quickly.

```
X-Response-ID: resp_a1b2c3d4e5f6
```

## Webhooks

Webhook **event delivery is coming soon**. Today you can already configure a `webhook_url` on your
merchant account and you receive a `webhook_secret` (`whsec_…`) at merchant creation. Keep it safe;
it will be used to verify event signatures once delivery ships.

Until then, poll [Get Payment Result](/api-reference/get-payment-result) for payment outcomes; the
[API journey](/api-reference/overview) is fully synchronous and complete without webhooks.
