> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Glossary

> Every Prava term in one place — and how the same thing is named across the API, CLI, and dashboard.

## Same thing, different names

Prava's surfaces sometimes use different names for the same value. This table is the map:

| Concept                      | REST API                        | Prava Pay CLI            | Prose / Concepts            |
| ---------------------------- | ------------------------------- | ------------------------ | --------------------------- |
| One-time virtual card number | `token`                         | `Token`                  | Payment token (virtual PAN) |
| One-time security code       | `dynamic_cvv`                   | `Cryptogram`             | Single-use CVV              |
| Card expiry for the token    | `expiry_month` + `expiry_year`  | `Expiry` (`MM/YYYY`)     | Token expiry                |
| Payment container            | session (`session_id`, `ses_…`) | session (`--session-id`) | Session                     |
| Spending permission          | mandate (`/v1/mandates`)        | `prava mandate`          | Mandate                     |

## The portals

<Note>
  **Two portals, two audiences.** [dashboard.prava.space](https://dashboard.prava.space) is the
  [**developer console**](/dashboard): sign up, create API keys, switch to
  production. [pay.prava.space](https://pay.prava.space) is the
  [**Prava Pay dashboard**](/prava-pay/your-wallet) for agent *owners*: approve agent links, enroll
  cards, set spending controls. A developer integrating the API only needs the console; an agent
  owner only needs the Prava Pay dashboard.
</Note>

## Core terms

| Term                            | Definition                                                                                                                                                                                                                                |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Session**                     | The container for one payment: customer + merchant + order, created by `POST /v1/sessions` (or `prava sessions create`). Expires after 15 minutes.                                                                                        |
| **Transaction**                 | A single payment attempt within a session (`addCard` or `savedCard` flow).                                                                                                                                                                |
| **Passkey**                     | WebAuthn biometric/device approval (Touch ID, Face ID, security key). Required for every payment; no fallback.                                                                                                                            |
| **Mandate**                     | A standing card-network spending permission: merchant, amount cap, frequency (`one_time` or recurring `weekly`/`monthly`/`yearly`), duration. Approved once with a passkey, then charged within caps. See [Mandates](/concepts/mandates). |
| **Payment token**               | The single-use virtual card credentials (number + CVV + expiry) issued against an active mandate: merchant-locked, amount-scoped, short-lived.                                                                                            |
| **Enrollment**                  | Securely collecting and tokenizing a card (via [`collectPAN`](/sdk/cards/collect-pan) or a hosted page). Yields an `enrollmentId`.                                                                                                        |
| **Agentic commerce enrollment** | A card flag (`isAgenticCommerceEnrolled`) enabling AI-initiated purchases with network-level (Visa) merchant/amount locking.                                                                                                              |
| **Agent owner**                 | The person/business whose account holds the cards and who approves agents; manages everything at [pay.prava.space](https://pay.prava.space).                                                                                              |
| **Agent linking**               | Connecting an agent to an owner's account: `prava setup` → owner approves in the browser → agent is `active` (or later `revoked`).                                                                                                        |
| **Quote / checkout (shopping)** | In agentic shopping, a quote locks a price (\~15 min) for a discovered product; checkout completes the purchase. See [Agentic Shopping](/prava-pay/shopping).                                                                             |
| **UCP**                         | Shopify's Universal Commerce Protocol: product search, catalogs, and quotes across participating merchants. See [UCP](/integration/ucp).                                                                                                  |
| **Browser Harness**             | Prava's checkout automation: confirms the true final total on the live merchant checkout and pays with the one-time token. See [Browser Harness](/integration/browser-harness).                                                           |

## Key types

| Key             | Prefix                    | Lives        | Used for                                         |
| --------------- | ------------------------- | ------------ | ------------------------------------------------ |
| Publishable key | `pk_test_*` / `pk_live_*` | Frontend     | Initializing the SDK                             |
| Secret key      | `sk_test_*` / `sk_live_*` | Backend only | Sessions, results, card management               |
| Session token   | —                         | Per-session  | Authenticates in-session operations (SDK/iframe) |

## Session vs mandate vs credential

Easy to conflate; they nest:

1. A **session** (15 min) is the workspace for one payment.
2. Inside it, passkey approval creates a **mandate**, the permission (merchant + max amount + duration).
3. Against the mandate, Prava issues the **payment token**, the actual single-use card credentials
   you check out with.

Expiry of one doesn't imply the others: a token can expire while its mandate is active (getting a new
token requires a new invocation), and a mandate can outlive the card-entry window.
