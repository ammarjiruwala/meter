> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# REST Checkout Walkthrough

> The complete payment flow with nothing but cURL — hosted card entry, zero frontend code.

The fastest way to see a full Prava payment: **hosted mode**, where Prava serves the card-entry page
and your side is three HTTP calls. Everything below is copy-pasteable; swap in your own `sk_test_*`
key.

## 1. Create the session

```bash theme={null}
curl -X POST https://sandbox.api.prava.space/v1/sessions \
  -H "Authorization: Bearer sk_test_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "user_email": "user@example.com",
    "total_amount": "49.99",
    "currency": "USD",
    "integration_type": "full_checkout",
    "callback_url": "https://yourapp.com/payment-done",
    "purchase_context": [{
      "merchant_details": {
        "name": "Example Store",
        "url": "https://examplestore.com",
        "country_code_iso2": "US"
      },
      "product_details": [{
        "description": "Wireless Headphones",
        "unit_price": "49.99",
        "quantity": 1
      }]
    }]
  }'
```

Response:

```json theme={null}
{
  "session_id": "ses_abc123",
  "session_token": "eyJhbGciOi…",
  "iframe_url": "https://sandbox.collect.prava.space?session=…",
  "order_id": "ord_xyz789",
  "expires_at": "2026-01-01T00:15:00Z"
}
```

<Warning>
  The session expires at `expires_at`, **15 minutes** after creation. Don't create it until the
  cardholder is ready.
</Warning>

## 2. Send the cardholder to the hosted page

Redirect (or link) the cardholder to the `iframe_url`. On Prava's hosted page they enter the card and
approve with a **passkey** (Touch ID / Face ID); Prava then redirects them to your `callback_url`. No SDK, no frontend
code, no card data anywhere near you.

<Note>
  On a **new browser/device** the cardholder is first asked for an **issuer OTP** (one-time code) and
  then to **register a passkey** — in that order (this is device binding). On a **returning** browser
  they just verify their existing passkey, with no OTP. In sandbox the test OTP is `456789`. Full
  sequence: [Anatomy of a Checkout](/concepts/checkout-flow).
</Note>

<Note>
  Behind the scenes Prava runs authentication, mandate registration (recording the cardholder's
  permission to pay), and tokenization (swapping the real card for one-time credentials):
  [what Prava does for you](/concepts/payments#what-prava-does-for-you-in-the-middle).
</Note>

## 3. Poll the payment result

```bash theme={null}
curl https://sandbox.api.prava.space/v1/sessions/ses_abc123/payment-result \
  -H "Authorization: Bearer sk_test_xxx"
```

While the cardholder is still on the hosted page you'll see `"status": "pending"`. Once they finish:

```json theme={null}
{
  "session_id": "ses_abc123",
  "order_id": "ord_xyz789",
  "status": "awaiting_result",
  "transactions": [{
    "txn_id": "txn_001",
    "status": "awaiting_result",
    "line_items": [{
      "txn_ref_id": "tli_001",
      "merchant_name": "Example Store",
      "merchant_url": "https://examplestore.com",
      "total_amount": "49.99",
      "status": "awaiting_result",
      "token": "4323126882557932",
      "dynamic_cvv": "957",
      "expiry_month": "12",
      "expiry_year": "2028",
      "products": [{
        "product_ref_id": "prd_001",
        "external_product_id": null,
        "name": "Wireless Headphones",
        "unit_price": "49.99",
        "quantity": 1
      }]
    }]
  }]
}
```

`token` + `dynamic_cvv` + expiry are the **one-time card credentials**. Use them at the merchant's
checkout like a normal card; they're single-use, merchant-locked, and amount-scoped.

## 4. Report the outcome

After the checkout runs (note the `txn_ref_id` from step 3):

```bash theme={null}
curl -X POST https://sandbox.api.prava.space/v1/sessions/ses_abc123/report-status \
  -H "Authorization: Bearer sk_test_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "txn_ref_id": "tli_001",
    "txn_status": "APPROVED"
  }'
```

Report `DECLINED` if the checkout failed; either way, always report. Re-poll the payment result and
the status is now `"completed"` (or `"failed"`).

## That's the whole flow

```
create session → cardholder pays on hosted page → poll result → checkout with token → report status
```

<CardGroup cols={2}>
  <Card title="Prefer embedded card entry?" icon="window-maximize" href="/guides/add-payments-to-your-ai-app">
    The same flow with Prava's card UI inside your own page.
  </Card>

  <Card title="Test cards & test OTP" icon="credit-card" href="/api-reference/test-cards">
    What you need to run this walkthrough end to end.
  </Card>
</CardGroup>
