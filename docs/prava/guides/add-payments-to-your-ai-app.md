> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Add Payments to Your AI App

> The end-to-end tutorial: from a fresh dashboard account to a completed, reported payment inside your own application.

This is the complete integration, start to finish. When you're done, your AI app can take a purchase
your agent proposes, collect the user's card **without touching it**, receive one-time credentials,
and complete the checkout.

**What you'll build:** one backend endpoint that creates sessions, one frontend surface that collects
the card, and one backend callback that reads the result and reports the outcome.

<Note>
  Prefer zero frontend code? The [REST checkout walkthrough](/guides/rest-checkout-walkthrough) does
  the same flow with hosted card entry and nothing but cURL.
</Note>

## Prerequisites (all self-serve)

1. Sign up at [dashboard.prava.space](https://dashboard.prava.space) and create an API key; you get
   `pk_test_*` + `sk_test_*` instantly ([Quickstart](/quickstart) has the details).
2. Install the SDK: `npm install @prava-sdk/core`.

<Tip>
  Building with an AI coding agent? Install the **prava-sdk-integration skill** and your agent knows
  this whole flow, with ready-made templates:

  ```bash theme={null}
  npx --yes skills add https://github.com/Prava-Payments/prava-skills \
    --skill prava-sdk-integration --global --yes --full-depth
  ```
</Tip>

## Step 1 — Backend: create a session

Your server pins the order and returns the session to your frontend. The secret key never leaves the
server.

<CodeGroup>
  ```typescript Next.js (app router) theme={null}
  // app/api/prava/session/route.ts
  export async function POST(req: Request) {
    const { userId, email, amount, merchant, items } = await req.json();

    const res = await fetch('https://sandbox.api.prava.space/v1/sessions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${process.env.PRAVA_SECRET_KEY}`, // sk_test_…
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_id: userId,
        user_email: email,
        total_amount: amount,            // e.g. "49.99"
        currency: 'USD',
        integration_type: 'embedding',   // card UI inside your page
        purchase_context: [{
          merchant_details: merchant,    // destination merchant, not your app: { name, url, country_code_iso2 }
          product_details: items,        // [{ description, unit_price, quantity }]
        }],
      }),
    });

    const session = await res.json();
    // → { session_id, session_token, iframe_url, order_id, expires_at }
    return Response.json({
      sessionId: session.session_id,
      sessionToken: session.session_token,
      iframeUrl: session.iframe_url,
    });
  }
  ```

  ```typescript Express theme={null}
  // server.ts
  import express from 'express';
  const app = express();
  app.use(express.json());

  app.post('/api/prava/session', async (req, res) => {
    const { userId, email, amount, merchant, items } = req.body;

    const r = await fetch('https://sandbox.api.prava.space/v1/sessions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${process.env.PRAVA_SECRET_KEY}`, // sk_test_…
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_id: userId,
        user_email: email,
        total_amount: amount,
        currency: 'USD',
        integration_type: 'embedding',
        purchase_context: [{
          merchant_details: merchant,
          product_details: items,
        }],
      }),
    });

    const session = await r.json();
    res.json({
      sessionId: session.session_id,
      sessionToken: session.session_token,
      iframeUrl: session.iframe_url,
    });
  });

  app.listen(3000);
  ```
</CodeGroup>

Full request schema: [Create Session](/api-reference/create-session). Sessions expire after
**15 minutes**: create them when the user is ready to pay, not earlier.

## Step 2 — Frontend: collect the card

Mount Prava's PCI-compliant iframe in your page. The raw card number never touches your DOM,
JavaScript, or servers.

<CodeGroup>
  ```tsx React theme={null}
  import { useEffect, useRef } from 'react';
  import { PravaSDK } from '@prava-sdk/core';

  export function PayWithPrava({ order }: { order: OrderInput }) {
    const prava = useRef(new PravaSDK({ publishableKey: 'pk_test_xxx' }));

    useEffect(() => () => prava.current.destroy(), []); // cleanup on unmount

    async function collect() {
      const { sessionId, sessionToken, iframeUrl } = await fetch('/api/prava/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(order),
      }).then((r) => r.json());

      await prava.current.collectPAN({
        sessionToken,
        iframeUrl,
        container: '#card-form',
        onSuccess: async (card) => {
          // card = { enrollmentId, last4, brand, expMonth, expYear }
          await fetch(`/api/prava/complete?sessionId=${sessionId}`, { method: 'POST' });
        },
        onError: (err) => console.error(err.code, err.message),
      });
    }

    return (
      <>
        <div id="card-form" />
        <button onClick={collect}>Pay securely</button>
      </>
    );
  }
  ```

  ```html Vanilla JS theme={null}
  <div id="card-form"></div>
  <button id="pay">Pay securely</button>

  <script type="module">
    import { PravaSDK } from 'https://esm.sh/@prava-sdk/core';

    const prava = new PravaSDK({ publishableKey: 'pk_test_xxx' });

    document.getElementById('pay').addEventListener('click', async () => {
      const { sessionId, sessionToken, iframeUrl } =
        await fetch('/api/prava/session', { method: 'POST' }).then((r) => r.json());

      await prava.collectPAN({
        sessionToken,
        iframeUrl,
        container: '#card-form',
        onSuccess: () =>
          fetch(`/api/prava/complete?sessionId=${sessionId}`, { method: 'POST' }),
        onError: (err) => console.error(err.code, err.message),
      });
    });
  </script>
  ```
</CodeGroup>

The user enters the card and approves with a **passkey** (Touch ID / Face ID) inside the iframe.
Prava handles the authentication, mandate registration (recording the user's permission to pay),
and tokenization (swapping the real card for one-time credentials);
[none of that is your code](/concepts/payments#what-prava-does-for-you-in-the-middle). Every option
and callback: [Collect Card Details](/sdk/cards/collect-pan).

## Step 3 — Backend: get the credentials and check out

After collection, poll the payment result. When a line item reaches `awaiting_result` it carries the
one-time credentials.

```typescript theme={null}
// Poll until the credentials are ready (they arrive right after card entry completes)
async function getCredentials(sessionId: string) {
  const r = await fetch(
    `https://sandbox.api.prava.space/v1/sessions/${sessionId}/payment-result`,
    { headers: { Authorization: `Bearer ${process.env.PRAVA_SECRET_KEY}` } },
  );
  const result = await r.json();

  if (result.status !== 'awaiting_result') return null; // keep polling ('pending')

  const li = result.transactions[0].line_items[0];
  return {
    txnRefId: li.txn_ref_id,
    cardNumber: li.token,        // one-time virtual card number
    cvv: li.dynamic_cvv,         // single-use CVV
    expMonth: li.expiry_month,
    expYear: li.expiry_year,
  };
}
```

Use these exactly like normal card details at the merchant's checkout: your agent fills the payment
form, or your backend calls the merchant's payment API. They're **single-use, merchant-locked, and
amount-scoped**, so use them promptly.

## Step 4 — Backend: report the outcome

Always close the loop, whether the checkout succeeded or failed:

```typescript theme={null}
await fetch(
  `https://sandbox.api.prava.space/v1/sessions/${sessionId}/report-status`,
  {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.PRAVA_SECRET_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      txn_ref_id: credentials.txnRefId,
      txn_status: 'APPROVED', // or 'DECLINED' if the checkout failed
    }),
  },
);
```

This updates transaction records and relays the outcome to the card network; the payment result's
`status` becomes `completed`. Details: [Report Status](/api-reference/report-status).

## Step 5 — Test it

Run the whole flow in sandbox with a [test card](/api-reference/test-cards). See
[Testing in Sandbox](/api-reference/testing) for the checklist and what behaves differently.

## Ship it

<CardGroup cols={2}>
  <Card title="Go-live checklist" icon="rocket" href="/guides/go-live-checklist">
    Swap to live keys and what needs Prava's sign-off.
  </Card>

  <Card title="Errors reference" icon="triangle-exclamation" href="/api-reference/errors">
    Every code you might hit along this flow, with recovery steps.
  </Card>
</CardGroup>
