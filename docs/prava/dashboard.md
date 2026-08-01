> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Your Developer Dashboard

> What dashboard.prava.space is for: keys, environments, and your payment activity.

The **Prava Dashboard** at [dashboard.prava.space](https://dashboard.prava.space) is the console for
**developers and merchants** integrating Prava. Everything your integration needs from Prava's side
lives here, and all of it is self-serve.

<Note>
  **Two portals, two audiences.** [dashboard.prava.space](https://dashboard.prava.space) is the
  [**developer console**](/dashboard): sign up, create API keys, switch to
  production. [pay.prava.space](https://pay.prava.space) is the
  [**Prava Pay dashboard**](/prava-pay/your-wallet) for agent *owners*: approve agent links, enroll
  cards, set spending controls. A developer integrating the API only needs the console; an agent
  owner only needs the Prava Pay dashboard.
</Note>

## What you do here

| Task                                                                                          | Where it fits                                                                                 |
| --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| **Sign up** with email (one-time code) or Google                                              | First step of the [Quickstart](/quickstart)                                                   |
| **Create API keys** — enter your entity name, get `pk_test_*` + `sk_test_*` instantly         | [Authentication](/authentication) explains each key                                           |
| **Switch environments** — sandbox and production are separate views with separate keys        | [Testing in Sandbox](/api-reference/testing) · [Go-Live Checklist](/guides/go-live-checklist) |
| **See your payment activity** — transactions and orders as they flow through your integration | Statuses match the [payment lifecycle](/concepts/payments)                                    |
| **Go live** — enable production; may require entity verification                              | [Compliance & Verification](/guides/compliance)                                               |

## Sandbox first, production when ready

New accounts start in **sandbox**: keys work immediately against
`sandbox.api.prava.space`, no waiting and no verification. Production is a separate environment you
enable from the dashboard when you're ready; going live may require verification of your entity
([what's needed](/guides/compliance)).

## Not the dashboard you're looking for?

If your agent pays with **your own card** and you want to approve agents, enroll cards, or set
spending limits, that's the **Prava Pay dashboard** at
[pay.prava.space](https://pay.prava.space) — see [Your Prava Pay Dashboard](/prava-pay/your-wallet).

## Next

<CardGroup cols={2}>
  <Card title="Quickstart" icon="bolt" href="/quickstart">
    Sign up, create keys, and make your first session.
  </Card>

  <Card title="Go-Live Checklist" icon="rocket" href="/guides/go-live-checklist">
    Everything between sandbox and production.
  </Card>
</CardGroup>
