> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Developer FAQ

> Common SDK and REST API integration questions, answered.

*Questions about agentic commerce, merchants, or refunds? See the
[Agentic Commerce FAQs](/integration/faqs). CLI issues? See
[Prava Pay Troubleshooting](/prava-pay/troubleshooting).*

## Keys & environments

**Which key goes where?** `pk_*` (publishable) initializes the SDK in the browser; `sk_*` (secret)
stays server-side for sessions, results, and card management. Full table:
[Authentication](/authentication).

**My key returns `AUTH_1001` but it's correct.** Check environment pairing: `sk_test_*` only works
against `sandbox.api.prava.space`, `sk_live_*` only against `api.prava.space`.

**Where do I get keys?** Self-serve at [dashboard.prava.space](https://dashboard.prava.space);
see the [Quickstart](/quickstart). No invite or waiting.

## Sessions

**How long does a session last?** 15 minutes (`expires_at` in the create response). Create sessions
when the user is ready to pay; once expired, create a new one rather than reusing it.

**The checkout page says "Authentication Failed" out of nowhere.** Check `expires_at` first — a
session that expires mid-flow can surface as a generic authentication error instead of a
"Session Expired" screen. If the session is past its 15 minutes, it isn't an auth problem:
create a fresh session and retry before debugging keys or passkeys.

**Can I create multiple sessions per user?** Technically yes, but create one per checkout flow and
complete or [revoke](/api-reference/revoke-session) it before starting another.

**Does the session `currency` have to match the card's country?** No. `currency` is your pricing
currency and is independent of where the card was issued — a US-issued card can pay an INR-denominated
session, and the network settles the conversion. `country_code_iso2` on the session is the
**merchant's** location, not the cardholder's. Price in your own currency; no re-denomination needed.

**`payment-result` stays `pending` forever.** The cardholder hasn't completed card entry + passkey
approval (Touch ID / Face ID) on the Prava surface. Confirm they opened the `iframe_url` (hosted) or that
[`collectPAN`](/sdk/cards/collect-pan) mounted without errors (embedded).

## The iframe / collectPAN

**The iframe won't load (`IFRAME_LOAD_ERROR`).** Verify you passed the `iframe_url` from the session
response verbatim.

**`Session preview failed: 404`.** The `?session=` value in the iframe URL isn't a valid `session_id`.
Two causes: (a) you rebuilt the URL and passed the `session_token` (JWT) instead of using `iframe_url`
verbatim — the identifier in `?session=` must be the `session_id` (`sess_…`); (b) environment mismatch,
e.g. a **sandbox** session opened on the **prod** collect host (or vice-versa).

**Can I style the card form?** The card fields live inside Prava's PCI-scoped iframe and aren't
arbitrarily styleable from your page. Position and size the container; the iframe handles the rest.

**Do I ever touch the card number?** No. You receive `{ enrollmentId, last4, brand, expMonth,
expYear }`, never the PAN (the full card number). That's what keeps you out of PCI scope, the
security compliance that applies once you handle card data.

## Tokens & checkout

**Can I reuse a token?** No — payment tokens are single-use, merchant-locked, amount-scoped, and
short-lived. If a checkout fails, report `DECLINED` and start a new session.

**What's a `dynamic_cvv`?** The single-use CVV paired with the token (the CLI calls it a
`Cryptogram`). Terminology map: [Glossary](/concepts/glossary).

**Do I have to call report-status?** Yes, always — `APPROVED` or `DECLINED`. It closes the loop with
transaction records and the card network. Unreported checkouts leave the transaction in
`awaiting_result`.

## Going further

**Webhooks?** Coming soon: configuration exists today, delivery is rolling out. Poll
[Get Payment Result](/api-reference/get-payment-result) meanwhile. See
[Authentication → Webhooks](/authentication#webhooks).

**Test cards?** Published on [Test Cards](/api-reference/test-cards), together with the test OTP,
organized by card network. Sandbox only.

**Pricing?** Contact [support@prava.space](mailto:support@prava.space) for current pricing.

**Something not covered here?** [support@prava.space](mailto:support@prava.space); include the
`X-Response-ID` header of any failing request.
