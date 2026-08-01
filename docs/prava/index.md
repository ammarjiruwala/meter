> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Introduction

> An overview of the Prava Payments API

<img src="https://mintcdn.com/pravapayments/O4nkkn6wh7EpbsaN/images/brand-banner.png?fit=max&auto=format&n=O4nkkn6wh7EpbsaN&q=85&s=5f9fd0ab72da457adc80b64355b7b407" alt="Prava — the payment stack for agentic checkout" width="2400" height="800" data-path="images/brand-banner.png" />

Prava turns a user's permission into a one-time, merchant-scoped card credential, so your agent can check out anywhere without ever touching raw card data. In-chat, in-voice, or any AI-native interface.

<Card title="Start building" icon="rocket" href="/quickstart" horizontal>
  Go from zero to a working session in minutes.
</Card>

## What do you want to do?

<CardGroup cols={2}>
  <Card title="Let an agent pay with my card" icon="terminal" href="/prava-pay/overview">
    The interface is an AI agent (OpenClaw, Hermes, ChatGPT). Connect Prava Pay via MCP (Model Context Protocol) or the CLI. No card data, no crypto.
  </Card>

  <Card title="Add payments to my app" icon="code" href="/choosing-your-integration">
    You own the interface. Embed the card UI in your page (SDK) or redirect to a Prava-hosted page (API). Pick your integration path.
  </Card>

  <Card title="Sell to AI shoppers" icon="cart-shopping" href="/integration/overview">
    You're a merchant or marketplace. Let agents discover, quote, and check out, with network-level enforcement. See Agentic Commerce.
  </Card>

  <Card title="Control what my agent spends" icon="wallet" href="/prava-pay/your-wallet">
    Your agent pays with your card. See exactly what it can and can't do, and the controls that keep you in charge. No code required.
  </Card>
</CardGroup>

<Card title="Try the Interactive Playground" icon="play" href="https://playground.prava.space/">
  See how Prava works in a live demo. No setup required.
</Card>

## The core ideas in 60 seconds

Think of Prava as a **programmable payment proxy**.

Instead of your AI agent handling raw credit card numbers (which creates massive compliance and security risks), it handles **permissions to spend**: approved by the user with a passkey and exchanged for a one-time, scoped credential.

<Steps>
  <Step title="The agent requests permission">
    It asks to buy a specific thing: merchant, amount, constraints.
  </Step>

  <Step title="The user grants it">
    The user approves on their device with a **Passkey** (Touch ID / Face ID).
  </Step>

  <Step title="Prava exchanges it for a credential">
    Prava trades that permission with the **card network** for a one-time, merchant-specific credential.
  </Step>

  <Step title="The agent checks out">
    The agent uses that ephemeral credential to complete the checkout at the merchant.
  </Step>
</Steps>

This decouples the *agent's ability to buy* from the *user's sensitive data*.

Four terms carry the whole system. A **session** is the workspace for one payment. A **passkey** is
the user's biometric approval (Touch ID / Face ID). A **mandate** is the resulting permission:
this merchant, up to this amount, for this long. A **payment token** is the single-use card
credential issued against it. Deeper reading: [How Prava Works](/concepts/how-it-works) ·
[Payments](/concepts/payments) · [Glossary](/concepts/glossary).

## What Prava provides

<CardGroup cols={2}>
  <Card title="Zero PCI scope" icon="shield-check">
    PCI scope is the security compliance you take on when handling card data. No sensitive card data exposure. Your agent never sees real card numbers.
  </Card>

  <Card title="Passkey-approved payments" icon="fingerprint">
    Users authorize specific purchases via Passkey authentication.
  </Card>

  <Card title="Network-level security" icon="lock">
    Merchant-specific, amount-scoped credentials enforced at the card network level.
  </Card>

  <Card title="Agentic commerce" icon="robot">
    Cards can be enrolled for AI-agent-initiated transactions with network-level enforcement.
  </Card>

  <Card title="Universal compatibility" icon="plug">
    Works with any merchant checkout: Stripe, Braintree, Adyen, or custom PSPs.
  </Card>

  <Card title="One SDK" icon="cube">
    A single SDK for complex payment orchestration.
  </Card>
</CardGroup>

## Who benefits

This documentation is for **developers building AI-powered applications** that need to make purchases on behalf of users. For the commerce capabilities behind that (discovery, quoting, and checkout), see [Agentic Commerce](/integration/overview).

* AI shopping/stylist apps (in-chat discovery → buy)
* Travel and booking agents (flight/hotel reservations)
* Personal assistant apps (scheduling, recurring purchases)
* Marketplaces and merchants who want to accept purchases triggered by LLMs or agents

## Start here

<CardGroup cols={3}>
  <Card title="Choose your integration" icon="signs-post" href="/choosing-your-integration">
    Three paths, decided in 10 seconds.
  </Card>

  <Card title="Quickstart" icon="rocket" href="/quickstart">
    Go from zero to a working session.
  </Card>

  <Card title="How Prava works" icon="diagram-project" href="/concepts/how-it-works">
    The full flow, end to end.
  </Card>
</CardGroup>
