> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Accounts & Agents

> How an owner's Prava account holds cards and authorizes AI agents to pay — and the controls that keep it safe.

Prava doesn't have a standalone "wallet" object. What it has is an **account** owned by a person or
business (the **agent owner**), managed from the [Prava Pay dashboard](https://pay.prava.space).
The account holds the enrolled cards and saved addresses, and the owner authorizes one or more **AI
agents** to pay on their behalf.

<Note>
  **Two portals, two audiences.** [dashboard.prava.space](https://dashboard.prava.space) is the
  [**developer console**](/dashboard): sign up, create API keys, switch to
  production. [pay.prava.space](https://pay.prava.space) is the
  [**Prava Pay dashboard**](/prava-pay/your-wallet) for agent *owners*: approve agent links, enroll
  cards, set spending controls. A developer integrating the API only needs the console; an agent
  owner only needs the Prava Pay dashboard.
</Note>

<Note>
  With Prava, the agent never holds funds or a raw card. It acts against the **owner's account** under
  the owner's controls, and only ever receives one-time, scoped credentials at the moment of purchase.
</Note>

## The model

* **Agent owner**: a dashboard user who owns the account and manages everything at
  [pay.prava.space](https://pay.prava.space).
* **Cards & addresses**: enrolled once and held on the owner's account.
* **Agents**: the owner links and approves each agent; every agent gets its own secure identity.
* **Shared access**: all of an owner's agents draw on the **same** cards. There are no per-agent card
  permissions.

## Authorizing agents

An agent is connected through the [linking flow](/prava-pay/linking): it requests access, and the owner
approves it in the browser. From then on an agent is either **active** or **revoked**. It's
all-or-nothing, not a permissions matrix. Revoking an agent cuts off its access immediately.

## Spending controls

These are the controls that actually exist and are enforced:

| Control                        | What it does                                                                                                                                                                                                                     | Where it's enforced       |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| **Checkout quota**             | A set number of checkouts allowed per owner (a lifetime count), consumed as agents buy.                                                                                                                                          | Prava (application level) |
| **Concurrency limit**          | Caps how many checkouts can be open at once (a small number).                                                                                                                                                                    | Prava (application level) |
| **Per-purchase approval**      | Every spend requires explicit approval before it happens. The [Skills](/prava-pay/skills) enforce a hard stop for agents; SDK/hosted flows use passkey confirmation (a biometric or security-key approval on the user's device). | Owner / device            |
| **Per-merchant amount limits** | When a card is enrolled for agentic commerce, each authorization is locked to the merchant and amount.                                                                                                                           | Card network (Visa)       |

<Note>
  Quota and concurrency are **Prava application-level** limits. Merchant/amount locking is enforced by
  the **card network**. See [Guardrails](/concepts/guardrails) for the network-level detail.
</Note>

## Cards on the account

Cards are enrolled through Prava's secure collection ([`collectPAN`](/sdk/cards/collect-pan) or a hosted
page) and tokenized: the number is replaced with a secure stand-in, and the raw card never touches the
app or the agent. Each card carries:

* a **status** (`active` / `deleted`),
* an **agentic-commerce** flag (`isAgenticCommerceEnrolled`) indicating it's enabled for AI-initiated
  purchases,

and is visible from the dashboard and the [List Cards](/api-reference/list-cards) API.

## Related

<CardGroup cols={2}>
  <Card title="Link an agent" icon="link" href="/prava-pay/linking">
    How an owner approves an agent against their account.
  </Card>

  <Card title="Guardrails" icon="shield" href="/concepts/guardrails">
    The network-level constraints on what an authorized purchase can do.
  </Card>
</CardGroup>
