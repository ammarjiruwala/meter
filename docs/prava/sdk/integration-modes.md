> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Integration Modes

> Two ways to collect a card from one session — embedded (SDK) or hosted (redirect).

Every card collection starts the same way: your backend creates a **session**
([`POST /v1/sessions`](/api-reference/create-session)) and gets back a `session_token` and an
`iframe_url`. From there you choose **how** the cardholder enters their card — and you pick by setting
one field, `integration_type`, on the session.

<CardGroup cols={2}>
  <Card title="Embedded" icon="window-maximize">
    Prava's card UI runs **inside your app** via the [SDK](/sdk/overview). You control the surrounding
    page and get the result in-app.
  </Card>

  <Card title="Hosted (default)" icon="up-right-from-square">
    You **redirect** the cardholder to a Prava-hosted page. No SDK, minimal code — Prava returns them to
    your `callback_url` when done.
  </Card>
</CardGroup>

<Note>
  Either way, the card is entered on **Prava's secure surface** and tokenized — your app never touches
  the raw card number. There is no mode where you collect the PAN yourself.
</Note>

## At a glance

|                           | **Embedded** (`"embedding"`)                     | **Hosted** (`"full_checkout"`, default)              |
| ------------------------- | ------------------------------------------------ | ---------------------------------------------------- |
| SDK required              | Yes (`@prava-sdk/core`)                          | No                                                   |
| Where the card UI renders | An iframe inside your page                       | A full Prava-hosted page you redirect to             |
| What you build            | A container + SDK wiring                         | A redirect + a `callback_url` route                  |
| How you get the result    | `onSuccess` callback, in-app                     | Prava redirects the user to your `callback_url`      |
| Best when                 | You want the flow to feel native to your product | You want the fastest, lowest-maintenance integration |

Both modes use the **same session** and the **same `iframe_url`** — embed it, or open it directly.

<Warning>
  **Use `iframe_url` exactly as returned.** It already carries the `?session=` identifier. Don't
  rebuild the URL or add your own `session` / `session_token` query params — the value in `?session=`
  must be the **`session_id`** (`sess_…`), never the `session_token` (the JWT). Passing the token there
  makes the iframe report `Session preview failed: 404`.
</Warning>

## Embedded mode

Create the session with `integration_type: "embedding"`, then mount the card UI with the SDK.

```typescript theme={null}
// 1. Backend: create the session
const session = await createSession({
  /* user_id, user_email, total_amount, currency, purchase_context … */
  integration_type: 'embedding',
});

// 2. Frontend: mount Prava's secure iframe in your page
import { PravaSDK } from '@prava-sdk/core';

const prava = new PravaSDK({ publishableKey: 'pk_test_xxx' });

await prava.collectPAN({
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

The result arrives in `onSuccess` without leaving your page. See
[Collect Card Details](/sdk/cards/collect-pan) for every option and callback, and remember to call
`prava.destroy()` on cleanup.

## Hosted mode (default)

Leave `integration_type` off (it defaults to `"full_checkout"`) and give Prava a `callback_url`. Then
send the cardholder to the returned `iframe_url` — no SDK needed.

```typescript theme={null}
// 1. Backend: create the session (hosted is the default)
const session = await createSession({
  /* user_id, user_email, total_amount, currency, purchase_context … */
  callback_url: 'https://yourapp.com/checkout/complete', // must be https
});

// 2. Frontend: send the user to the hosted page.
// iframe_url already contains ?session=<session_id> — use it verbatim.
window.location.href = session.iframe_url; // or window.open(session.iframe_url, '_blank')
```

When the cardholder finishes, Prava redirects them back to your `callback_url`. Your backend then reads
the outcome with [Get Payment Result](/api-reference/get-payment-result) and reports the final status
with [Report Status](/api-reference/report-status).

<Warning>
  `callback_url` must be an **https** URL. Without it, a hosted checkout has nowhere to return the user.
</Warning>

## Which should I use?

<CardGroup cols={2}>
  <Card title="Choose Embedded" icon="puzzle-piece">
    You want the card step to feel native, keep the user on your page, and react to the result in-app.
  </Card>

  <Card title="Choose Hosted" icon="bolt">
    You want to ship fast with minimal frontend code and are happy to redirect out and back.
  </Card>
</CardGroup>

## Next steps

<CardGroup cols={2}>
  <Card title="SDK Overview" icon="code" href="/sdk/overview">
    The library behind embedded mode.
  </Card>

  <Card title="Create Session" icon="plus" href="/api-reference/create-session">
    `integration_type`, `callback_url`, and the full request/response.
  </Card>
</CardGroup>
