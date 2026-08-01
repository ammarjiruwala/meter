> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Compliance & Verification

> What verification each integration path needs, and what Prava is (and is not) as a regulated matter.

Two questions come up before production: "what do you need from me?" and "what exactly is Prava,
legally?" Both answers are short.

## Verification by integration path

### SDK / API integrators: KYB

KYB (Know Your Business) is business identity verification. If you integrate the
[SDK + API](/sdk/overview) and take live payments in your product, your business gets verified when
you [switch to production](/guides/go-live-checklist). Have these ready (indicative; we confirm the
exact list during verification):

* Legal entity name and country of incorporation
* Registration / incorporation number and date
* Registered business address
* Beneficial owners (name, ownership stake)
* Business website and a working contact

Sandbox needs none of this. Build and test first; verify when you go live. Specifics:
[support@prava.space](mailto:support@prava.space).

### MCP / CLI users: KYC via card verification

KYC (Know Your Customer) is personal identity verification. If you connect an agent through
[MCP](/mcp/overview) or the [CLI](/prava-pay/overview), there is no separate KYC form. Identity
verification is inherited from your card: when you enroll it, the card is verified with your
issuing bank (including OTP verification, a one-time code, where the issuer requires it), and
every payment is approved with a passkey (Touch ID / Face ID) on your device. Your bank has already verified you; Prava
builds on that.

## What Prava is — and is not

From our [Terms & Conditions](https://www.prava.space/terms-conditions):

> Prava is not a bank, card issuer, acquirer, payment processor, money transmitter, stored value
> provider, or deposit-taking institution.

Prava is a **technology service provider for agentic commerce**, operated by **Prava Payments Inc**
(Delaware, USA). Payment processing, authorization, clearing, settlement, money movement, refunds,
and chargebacks are handled by the card networks, banks, and licensed processors in the flow. Prava
never holds your money.

On data security:

* Prava maintains **PCI DSS Level 2 / SAQ-D** compliance (PCI DSS is the card industry's
  data-security standard) and uses **Skyflow, a PCI DSS Level 1 vault provider**, for card vaulting.
* Prava does not store raw card numbers or CVV in its application databases.
* AI agents and apps never receive the user's underlying card number or CVV.

Full texts: [Terms & Conditions](https://www.prava.space/terms-conditions) ·
[Privacy Policy](https://www.prava.space/privacypolicy) ·
[Security](https://www.prava.space/security)
