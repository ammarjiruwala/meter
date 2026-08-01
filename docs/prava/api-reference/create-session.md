> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Create Session

> Create a payment session for a customer and order — standard checkout or mandate setup.

Create a short-lived, single-use session tied to one merchant, customer, and order. The response gives you a `session_token` + `iframe_url` for the frontend — embed the iframe via the [SDK](/sdk/overview) or open the [hosted checkout](/sdk/integration-modes) directly.

`POST /v1/sessions` · Authenticated with your secret key.

## Which flow?

<Tabs>
  <Tab title="Standard checkout">
    Omit `mandate_setup` (or send `intent: "checkout"`). The session collects a card and charges immediately.
  </Tab>

  <Tab title="Mandate setup">
    Include a `mandate_setup` block with `intent: "mandate_setup"`. The session is **authorize-only**: it returns an `iframe_url` (passkey approval) and `authorizeOnly: true`, and issues **no** credentials. Charge later with [Charge a Mandate](/api-reference/mandate-charge). There is no separate `POST /v1/mandates` create endpoint — a [mandate](/concepts/mandates) is always set up through this endpoint.
  </Tab>
</Tabs>

## Mandate setup

**Mandate creation is part of the Session APIs — this endpoint is how mandates are created.** Send a `mandate_setup` block (see [Body](#body)) with `intent: "mandate_setup"` and the session becomes authorize-only: the response carries an `iframe_url` where the owner approves **once** with their passkey, `authorizeOnly: true`, and no credentials. Once the mandate is `active`, charge it any time with [Charge a Mandate](/api-reference/mandate-charge) — no further passkey needed.

The `mandate_setup` field reference below covers `recurring_frequency`, `merchant_scope`, `max_charges`, and `valid_until`; see [Mandates](/concepts/mandates) for the concept and guardrails.

<Note>
  **Choosing a card source.** Omit `card` to let the cardholder select or enter a card in the collection surface. Send `card.card_id` to pre-select an already-enrolled card, or `card.vault_ref_id` (a Skyflow UUID) for the vault-ref flow. Send **exactly one** — if both are present, `card_id` wins.
</Note>

## Body

<ParamField body="user_id" type="string" required>
  Unique identifier for the customer in your system (1–255 chars). Required for merchant (secret-key) sessions — omitting it returns `400 VAL_2001`.
</ParamField>

<ParamField body="user_email" type="string" required>
  Customer email. Required for merchant sessions. Must be a valid email address.
</ParamField>

<ParamField body="total_amount" type="string" required>
  Total order amount as a decimal string with up to 2 decimals, e.g. `"49.99"`. Need not equal the sum of line items (it may include tax, shipping, and fees). This value becomes the authorized amount cap.
</ParamField>

<ParamField body="currency" type="string" required>
  ISO 4217 code — 3 uppercase letters — and must be a **supported currency**. Supported: USD, EUR, GBP, INR, CAD, AUD, JPY, SGD, AED, HKD, MXN, BRL, CHF, CNY, NZD, SEK, NOK, DKK, ZAR, THB, KRW, PLN, TWD, PHP, IDR, MYR, CZK, ILS, CLP, ARS, COP, PEN, SAR, QAR, KWD, BHD, OMR, EGP, NGN, KES, GHS, TZS, UGX, PKR, BDT, LKR, VND, MMK, NPR. Other codes are rejected.

  This is your **pricing currency** and is independent of the card's issuing country: there is no requirement that it match `country_code_iso2` (the merchant's location) or the cardholder's country. A US-issued card can pay an INR-denominated session; the card network settles the cross-currency conversion. Price in whatever currency your product uses — you don't need to re-denominate.
</ParamField>

<ParamField body="purchase_context" type="object[]" required>
  Exactly one entry — multi-merchant sessions are not yet supported.

  <Expandable title="purchase_context[] properties">
    <ParamField body="merchant_details" type="object" required>
      The **destination merchant** — the business the cardholder is buying from, **not your
      application**. The `name` renders as the header on the checkout page and is forwarded to
      Visa as the merchant of record for the token.

      <Expandable title="merchant_details properties">
        <ParamField body="name" type="string" required>
          Merchant display name. Sanitized to a Visa-safe character set (e.g. `H&M` → `HM`); must contain at least one usable character.
        </ParamField>

        <ParamField body="url" type="string" required>
          Merchant website URL. **Must use `https`** — the URL is forwarded to Visa.
        </ParamField>

        <ParamField body="country_code_iso2" type="string" required>
          Merchant country — 2 uppercase ISO 3166-1 letters, e.g. `"US"`.
        </ParamField>

        <ParamField body="category_code" type="string">
          Merchant category code (MCC). Free-form string, max 10 characters.
        </ParamField>

        <ParamField body="category" type="string">
          Merchant category description, max 100 characters.
        </ParamField>
      </Expandable>
    </ParamField>

    <ParamField body="product_details" type="object[]" required>
      At least one product.

      <Expandable title="product_details[] properties">
        <ParamField body="description" type="string" required>
          Product description.
        </ParamField>

        <ParamField body="unit_price" type="string" required>
          Unit price as a string, e.g. `"24.99"`.
        </ParamField>

        <ParamField body="product_id" type="string">
          Your external product identifier, max 50 characters.
        </ParamField>

        <ParamField body="quantity" type="integer" default={1}>
          Quantity of this product. Positive integer.
        </ParamField>
      </Expandable>
    </ParamField>

    <ParamField body="effective_until_minutes" type="integer" default={15}>
      How long the resulting mandate stays effective, in minutes. Positive integer.
    </ParamField>
  </Expandable>
</ParamField>

<ParamField body="integration_type" type="string" default="full_checkout">
  `full_checkout` (hosted redirect) or `embedding` (mount the iframe via the SDK). Read by the frontend to choose the surface.
</ParamField>

<ParamField body="callback_url" type="string">
  For hosted checkout: the URL Prava redirects the cardholder to after they finish. **Must use `https`**, max 2048 chars. Optional for all integration types.
</ParamField>

<ParamField body="card" type="object">
  Pre-select a card. Send one of the two fields below (see the note above).

  <Expandable title="card properties">
    <ParamField body="card_id" type="string">
      An enrolled card id (the `enrollmentId` from the SDK's [`collectPAN()`](/sdk/cards/collect-pan), or a `card_id` from [List Cards](/api-reference/list-cards)). Scoped to this customer + merchant.
    </ParamField>

    <ParamField body="vault_ref_id" type="string">
      A Skyflow vault reference UUID. Triggers provisioning at session-create.
    </ParamField>
  </Expandable>
</ParamField>

<ParamField body="mandate_setup" type="object">
  Turns the session into mandate setup (authorize-only). See the Mandate setup tab above.

  <Expandable title="mandate_setup properties">
    <ParamField body="intent" type="string">
      `mandate_setup` (authorize-only, no charge) or `checkout`. Defaults to `mandate_setup` when this block is present.
    </ParamField>

    <ParamField body="recurring_frequency" type="string">
      `one_time`, `weekly`, `monthly`, or `yearly`.
    </ParamField>

    <ParamField body="merchant_scope" type="string">
      `listed` (locked to this merchant) or `any` (any merchant). Recurring frequencies force `listed` — sending `any` with a recurring frequency returns `400 MANDATE_RECURRING_MUST_BE_SCOPED`.
    </ParamField>

    <ParamField body="valid_until" type="string">
      ISO 8601 datetime. **Ignored for `one_time`**, which is always clamped to 7 days. Recurring horizons: yearly 5y, monthly 2y, weekly 1y.
    </ParamField>

    <ParamField body="max_charges" type="integer" default={1}>
      Maximum number of charges allowed against this mandate. Positive integer. (The per-charge *amount* cap is enforced separately, at the card network.)
    </ParamField>
  </Expandable>
</ParamField>

<ParamField body="user_phone" type="string">
  Customer phone number.
</ParamField>

<ParamField body="user_country_code_iso2" type="string">
  Customer country — 2 uppercase ISO 3166-1 letters.
</ParamField>

<ParamField body="external_order_ref" type="string">
  Your external order reference id, max 255 chars.
</ParamField>

<ParamField body="description" type="string">
  Human-readable description of the order.
</ParamField>

## Response

<ResponseField name="session_id" type="string">Unique session identifier.</ResponseField>
<ResponseField name="session_token" type="string">JWT authenticating client-side SDK calls within this session.</ResponseField>
<ResponseField name="iframe_url" type="string">Secure card-collection (or, for mandate setup, passkey-approval) surface.</ResponseField>
<ResponseField name="order_id" type="string">Internal order identifier.</ResponseField>
<ResponseField name="expires_at" type="string">ISO 8601 timestamp when the session expires.</ResponseField>
<ResponseField name="authorizeOnly" type="boolean">Present and `true` for mandate-setup sessions (no credentials issued).</ResponseField>

## Notes

* Sessions are **short-lived** and **single-use**, tied to a specific merchant, customer, and order.
* `session_token` and `iframe_url` are used on the frontend: embedded via the [SDK](/sdk/overview), or opened directly for [hosted checkout](/sdk/integration-modes).
* Sessions can be revoked before use via [`POST /v1/sessions/:id/revoke`](/api-reference/revoke-session).

## Error responses

| Status | Code                               | Cause                                                                                                                        |
| ------ | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| 400    | `VAL_2001`                         | Validation error (missing/invalid fields; `user_id`/`user_email` missing on a merchant session). `details` names the fields. |
| 400    | `CARD_NOT_FOUND`                   | Pre-selected `card_id` does not exist for this customer + merchant                                                           |
| 400    | `CARD_INACTIVE`                    | Pre-selected card is not active                                                                                              |
| 400    | `MANDATE_RECURRING_MUST_BE_SCOPED` | Recurring frequency sent with `merchant_scope: "any"`                                                                        |
| 401    | `AUTH_1001`                        | Invalid API key                                                                                                              |
| 401    | `AUTH_1002`                        | Missing or invalid Authorization header                                                                                      |
| 429    | `TRIES_EXHAUSTED`                  | Sandbox test-transaction limit reached for this merchant                                                                     |
| 500    | `MERCHANT_LOOKUP_ERROR`            | Failed to load the merchant account for the key                                                                              |
| 500    | `CONFIG_ERROR`                     | Server-side configuration issue (Visa or Skyflow not configured)                                                             |

<RequestExample>
  ```bash cURL theme={null}
  curl -X POST https://sandbox.api.prava.space/v1/sessions \
    -H "Authorization: Bearer sk_test_..." \
    -H "Content-Type: application/json" \
    -d '{
      "user_id": "user_123",
      "user_email": "jane@example.com",
      "total_amount": "49.99",
      "currency": "USD",
      "purchase_context": [{
        "merchant_details": { "name": "Acme Store", "url": "https://acme.example.com", "country_code_iso2": "US" },
        "product_details": [{ "description": "Widget", "unit_price": "24.99", "quantity": 2 }]
      }],
      "integration_type": "full_checkout",
      "callback_url": "https://acme.example.com/return"
    }'
  ```

  ```python Python theme={null}
  import requests

  resp = requests.post(
      "https://sandbox.api.prava.space/v1/sessions",
      headers={"Authorization": "Bearer sk_test_..."},
      json={
          "user_id": "user_123",
          "user_email": "jane@example.com",
          "total_amount": "49.99",
          "currency": "USD",
          "purchase_context": [{
              "merchant_details": {"name": "Acme Store", "url": "https://acme.example.com", "country_code_iso2": "US"},
              "product_details": [{"description": "Widget", "unit_price": "24.99", "quantity": 2}],
          }],
          "integration_type": "full_checkout",
          "callback_url": "https://acme.example.com/return",
      },
  )
  ```

  ```javascript JavaScript theme={null}
  const resp = await fetch("https://sandbox.api.prava.space/v1/sessions", {
    method: "POST",
    headers: {
      Authorization: "Bearer sk_test_...",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      user_id: "user_123",
      user_email: "jane@example.com",
      total_amount: "49.99",
      currency: "USD",
      purchase_context: [{
        merchant_details: { name: "Acme Store", url: "https://acme.example.com", country_code_iso2: "US" },
        product_details: [{ description: "Widget", unit_price: "24.99", quantity: 2 }],
      }],
      integration_type: "full_checkout",
      callback_url: "https://acme.example.com/return",
    }),
  });
  ```

  ```bash cURL · Mandate setup theme={null}
  curl -X POST https://sandbox.api.prava.space/v1/sessions \
    -H "Authorization: Bearer sk_test_..." \
    -H "Content-Type: application/json" \
    -d '{
      "user_id": "user_123",
      "user_email": "jane@example.com",
      "total_amount": "40.00",
      "currency": "USD",
      "purchase_context": [{
        "merchant_details": { "name": "Acme Store", "url": "https://acme.example.com", "country_code_iso2": "US" },
        "product_details": [{ "description": "Monthly plan", "unit_price": "40.00" }]
      }],
      "mandate_setup": {
        "intent": "mandate_setup",
        "recurring_frequency": "monthly",
        "merchant_scope": "listed",
        "max_charges": 12
      }
    }'
  ```
</RequestExample>

<ResponseExample>
  ```json 201 Standard theme={null}
  {
    "session_id": "sess_9f2c...",
    "session_token": "eyJhbGciOi...",
    "iframe_url": "https://checkout.prava.space/s/sess_9f2c...",
    "order_id": "ord_4a1b...",
    "expires_at": "2026-07-26T12:15:00Z"
  }
  ```

  ```json 201 Mandate setup theme={null}
  {
    "session_id": "sess_7d1a...",
    "session_token": "eyJhbGciOi...",
    "iframe_url": "https://checkout.prava.space/s/sess_7d1a...",
    "order_id": "ord_88c2...",
    "expires_at": "2026-07-26T12:15:00Z",
    "authorizeOnly": true
  }
  ```

  ```json 400 Validation theme={null}
  {
    "error": {
      "code": "VAL_2001",
      "message": "Validation failed",
      "details": { "currency": "Unsupported currency code" }
    }
  }
  ```

  ```json 401 Unauthorized theme={null}
  {
    "error": { "code": "AUTH_1001", "message": "Invalid API key" }
  }
  ```
</ResponseExample>
