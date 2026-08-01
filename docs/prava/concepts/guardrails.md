> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Guardrails

> Rule-based controls that constrain what AI agents can spend and where.

## Guardrails

**Guardrails** are rule-based controls enforced at multiple levels to ensure AI agents cannot exceed their authorized scope. They operate across four enforcement layers:

### 0. Owner-Set Account Controls

Before any payment mechanics apply, the account owner's own controls do. These are set from the
[Prava Pay dashboard](https://pay.prava.space) and enforced by Prava on every purchase:

* **Checkout quota**: a set number of checkouts allowed per owner, consumed as agents buy.
* **Concurrency limit**: caps how many checkouts can be open at once.
* **Per-purchase approval**: every spend needs explicit approval before it happens.
* **Agent revocation**: revoking an agent cuts off its access immediately.

See [Accounts & Agents](/concepts/accounts) for the full model.

### 1. Mandate-Level Constraints

Every payment intent creates a **mandate**, a spending permission registered at the card network level. The mandate itself is a guardrail. It specifies:

| Constraint             | What it controls                                                                             |
| ---------------------- | -------------------------------------------------------------------------------------------- |
| **Merchant**           | The merchant the mandate is scoped to                                                        |
| **Amount threshold**   | Maximum amount for the transaction                                                           |
| **Frequency**          | `one_time`, or recurring `weekly`/`monthly`/`yearly` (one charge per cycle, single-merchant) |
| **Effective duration** | When the mandate expires (`expiresAt`)                                                       |
| **Product scope**      | The products in the purchase (via mandate line items)                                        |

The mandate's **amount** is enforced at the card-network level through the tokenized credential (the substitute card number issued for the purchase): a transaction outside the mandate amount is declined. The remaining constraints are applied by Prava.

### 2. Session-Level Controls

Each session is scoped to:

* A specific **merchant** and **order**
* A **time limit**: sessions expire and cannot be reused
* **Idempotency**: duplicate transactions within a session are detected and rejected

### 3. Authentication Controls

* **Passkey (WebAuthn)**: a biometric or security-key approval on the user's device, required for every intent mutation (register, update, delete). Prevents unauthorized agents from creating mandates.
* **Device binding**: passkeys are registered per browser, so a passkey on one device cannot be used on another.
* **WebAuthn required**: if the user's device does not support WebAuthn (passkeys), transactions cannot be performed. There is no fallback mechanism; this ensures the highest level of authentication security.

## Defense in Depth

```
Owner controls (quota, approval) → User approval (Passkey) → Mandate (amount-scoped) → Session (time-scoped) → one-time credential
```

Every layer must pass for a payment to succeed. An AI agent with a valid mandate but an expired session is blocked; a transaction outside the mandate amount is declined. This layered approach ensures no single point of failure.
