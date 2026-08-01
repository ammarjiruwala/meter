> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# SDK Overview

> Embed secure, PCI-safe card collection into your web app with the Prava SDK.

*Not sure this is the right path? See [Choosing Your Integration](/choosing-your-integration).*

## What is the Prava SDK?

The **Prava SDK** (`@prava-sdk/core`) is a lightweight browser library for **securely collecting a
card** in your web app. It mounts a PCI-compliant iframe, handles the card entry and authentication
inside it, and hands you back a safe result — the raw card number never touches your page, your
JavaScript, or your servers.

<Note>
  The SDK is the **client-side** piece of a session-based integration. Your **backend** creates the
  session (see the [API Reference](/api-reference/overview)); the SDK renders the secure card form for
  that session. If instead you want an **AI agent** to pay from the command line, use
  [Prava Pay](/prava-pay/overview).
</Note>

<Info>
  The SDK powers the **embedded** integration mode — Prava's card UI inside your own page. Don't want
  to embed? Use **hosted** mode (a redirect, no SDK). See
  [Integration Modes](/sdk/integration-modes) to choose.
</Info>

## What it does (and doesn't)

The SDK's job is deliberately small — one secure operation, done well:

| The SDK handles                                      | Your backend handles                       |
| ---------------------------------------------------- | ------------------------------------------ |
| Rendering the secure card iframe                     | Creating the session (`POST /v1/sessions`) |
| Card entry, validation, and in-iframe authentication | Reading the payment result                 |
| Returning a safe, tokenized result                   | Reporting the final transaction status     |

Everything money-related — mandates, one-time payment credentials, spending limits — is enforced by
Prava and the card network, not by code running in your page. See [Payments](/concepts/payments) and
[Guardrails](/concepts/guardrails) for how that works.

## Install

<CodeGroup>
  ```bash npm theme={null}
  npm install @prava-sdk/core
  ```

  ```bash yarn theme={null}
  yarn add @prava-sdk/core
  ```

  ```bash pnpm theme={null}
  pnpm add @prava-sdk/core
  ```
</CodeGroup>

## Quick start

<Steps>
  <Step title="Initialize with your publishable key">
    ```typescript theme={null}
    import { PravaSDK } from '@prava-sdk/core';

    const prava = new PravaSDK({
      publishableKey: 'pk_test_xxx', // from the Prava Dashboard (sandbox key)
    });
    ```

    The publishable key is safe to ship to the browser. Your **secret key** stays on your server and is
    never used here.
  </Step>

  <Step title="Create a session on your backend">
    Your server creates a session with your secret key and returns the `session_token` and `iframe_url`
    to your frontend:

    ```typescript theme={null}
    // Server-side (never expose your secret key to the browser)
    const session = await fetch('https://sandbox.api.prava.space/v1/sessions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${SECRET_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_id: 'user_123',
        user_email: 'user@example.com',
        total_amount: '49.99',
        currency: 'USD',
        purchase_context: [{
          merchant_details: { name: 'Amazon', url: 'https://amazon.com', country_code_iso2: 'US' },
          product_details: [{ description: 'Wireless Headphones', unit_price: '49.99', quantity: 1 }],
        }],
      }),
    }).then((r) => r.json());
    // → { session_id, session_token, iframe_url, expires_at, order_id }
    ```

    Full request/response details: [Create Session](/api-reference/create-session).
  </Step>

  <Step title="Collect the card in the browser">
    ```typescript theme={null}
    const result = await prava.collectPAN({
      sessionToken: session.session_token,
      iframeUrl: session.iframe_url,
      container: '#card-form',
      onSuccess: (data) => console.log(`Collected •••• ${data.last4}`),
      onError: (err) => console.error(err.code, err.message),
    });
    ```

    ```html theme={null}
    <div id="card-form"></div>
    ```

    See [Collect Card Details](/sdk/cards/collect-pan) for every option and callback.
  </Step>

  <Step title="Read the result on your backend">
    After the card is collected and the transaction runs, your backend reads the outcome and reports the
    final status. See [Get Payment Result](/api-reference/get-payment-result) and
    [Report Status](/api-reference/report-status).
  </Step>
</Steps>

## API surface

The SDK exposes exactly two methods:

| Method                                          | Description                                                                      |
| ----------------------------------------------- | -------------------------------------------------------------------------------- |
| [`collectPAN(options)`](/sdk/cards/collect-pan) | Mounts the secure iframe, collects the card, resolves with a `CollectPANResult`. |
| `destroy()`                                     | Tears down the iframe and listeners. Call it on unmount/cleanup.                 |

```typescript theme={null}
// Clean up when your component unmounts
prava.destroy();
```

## Authentication

| Key                                             | Where it's used                   | Where it lives |
| ----------------------------------------------- | --------------------------------- | -------------- |
| **Publishable key** (`pk_live_*` / `pk_test_*`) | Initialize the SDK in the browser | Frontend       |
| **Secret key** (`sk_*`)                         | Create sessions, read results     | Backend only   |

<Warning>Never put your secret key in client-side code or version control.</Warning>

## Result & error types

```typescript theme={null}
interface CollectPANResult {
  enrollmentId: string;
  last4: string;
  brand: string;      // "visa", "mastercard", …
  expMonth: number;
  expYear: number;
}

interface PravaError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}
```

Error codes, every `collectPAN` option, and validation states are documented on
[Collect Card Details](/sdk/cards/collect-pan) — the canonical `collectPAN` reference.

## Requirements

* **Browsers:** Chrome 80+, Firefox 80+, Safari 14+, Edge 80+.
* **Backend:** Your server implements the session API (`POST /v1/sessions`) with your secret key.
* **Keys:** Obtain `publishableKey` and `secretKey` from the [Prava Dashboard](https://dashboard.prava.space).

## Next steps

<CardGroup cols={2}>
  <Card title="Collect Card Details" icon="credit-card" href="/sdk/cards/collect-pan">
    Every `collectPAN` option, callback, and validation state.
  </Card>

  <Card title="API Reference" icon="server" href="/api-reference/overview">
    Create sessions, read payment results, and report status server-side.
  </Card>

  <Card title="How Prava Works" icon="diagram-project" href="/concepts/how-it-works">
    The lifecycle behind a Prava payment.
  </Card>

  <Card title="Prava Pay (CLI)" icon="terminal" href="/prava-pay/overview">
    Let an AI agent pay from the command line.
  </Card>
</CardGroup>
