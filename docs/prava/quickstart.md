> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Quickstart

> Start building with Prava

Getting started with Prava is **self-serve**. Sign up at the
[Prava Dashboard](https://dashboard.prava.space) ([what it offers](/dashboard)),
create an API key, and you'll have sandbox credentials in a few minutes, with no invite code and no waiting.

<Tip>
  **Want to see Prava in action first?** Try the [Interactive Playground](https://playground.prava.space/) to visualize the full payment flow before you build.
</Tip>

## Set up your account

<Steps>
  <Step title="Sign up">
    Go to [dashboard.prava.space](https://dashboard.prava.space) and create an account with your email
    (one-time code) or Google. You'll land in the dashboard right away.
  </Step>

  <Step title="Create an API key">
    In the dashboard, create an API key by entering your **entity name** (and optional website). Prava
    provisions your merchant and issues your keys instantly:

    * A **publishable key** (`pk_test_*`) — safe for the browser, used to initialize the SDK.
    * A **secret key** (`sk_test_*`) — server-side only, used to create sessions.

    New keys are **sandbox** by default. See [Authentication & Environments](/authentication) for how keys and environments work.
  </Step>
</Steps>

<Note>
  **Going to production?** Production is a separate environment you switch to from the dashboard, and
  going live may require some additional verification. Reach out at
  [support@prava.space](mailto:support@prava.space) when you're ready. You can build and
  test everything in sandbox first.
</Note>

## Create your first session

A session is the workspace for a single payment. Once you have your credentials, create a session
from your backend:

```bash theme={null}
curl -X POST https://sandbox.api.prava.space/v1/sessions \
  -H "Authorization: Bearer sk_test_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "user_email": "user@example.com",
    "total_amount": "49.99",
    "currency": "USD",
    "purchase_context": [{
      "merchant_details": {
        "name": "Your Store",
        "url": "https://yourstore.com",
        "country_code_iso2": "US"
      },
      "product_details": [{
        "description": "Example Product",
        "unit_price": "49.99",
        "quantity": 1
      }]
    }]
  }'
```

The response gives you a `session_token` and an `iframe_url`.

## Choose how to collect the card

From that one session you can collect the card two ways:

* **Hosted (default)**: redirect the cardholder to the `iframe_url`; Prava returns them to your
  `callback_url` when done. No frontend SDK needed.
* **Embedded**: set `integration_type: "embedding"` on the session and mount Prava's card UI inside
  your own page with the SDK (below).

See [Integration Modes](/sdk/integration-modes) for a side-by-side comparison and the hosted snippet.

## Embed the card form (embedded mode)

```typescript theme={null}
import { PravaSDK } from '@prava-sdk/core';

const prava = new PravaSDK({
  publishableKey: 'pk_test_xxx',
});

await prava.collectPAN({
  sessionToken: session.session_token,
  iframeUrl: session.iframe_url,
  container: '#card-form',
  onSuccess: (data) => console.log(`Collected: ${data.brand} •••• ${data.last4}`),
  onError: (err) => console.error(err.code, err.message),
});
```

See the [SDK Overview](/sdk/overview) for the full API reference.

## Where next

<CardGroup cols={3}>
  <Card title="Full tutorial" icon="wand-magic-sparkles" href="/guides/add-payments-to-your-ai-app">
    The complete integration in your app: backend, frontend, credentials, reporting.
  </Card>

  <Card title="Pure REST walkthrough" icon="terminal" href="/guides/rest-checkout-walkthrough">
    The same flow with hosted card entry and nothing but cURL.
  </Card>

  <Card title="Test it in sandbox" icon="flask" href="/api-reference/testing">
    Test cards, sandbox behaviors, and a full test run.
  </Card>
</CardGroup>
