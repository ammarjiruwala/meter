> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Go-Live Checklist

> Everything between a working sandbox integration and live payments — and exactly which steps need Prava.

You've completed the flow in sandbox ([tutorial](/guides/add-payments-to-your-ai-app) ·
[REST walkthrough](/guides/rest-checkout-walkthrough)). Here's the full path to production.

## The checklist

<Steps>
  <Step title="Finish sandbox verification">
    Run one complete payment in sandbox: session → card entry → passkey → credentials → checkout →
    report-status → `completed`. If any step surprises you, fix it now;
    [Errors](/api-reference/errors) has every code.
  </Step>

  <Step title="Switch to production from the dashboard">
    Production is a separate environment you enable at
    [dashboard.prava.space](https://dashboard.prava.space) (the [developer dashboard](/dashboard)).
    Going live may require additional
    verification of your entity:

    <Info>
      **This step needs Prava's help — everything else is self-serve.** Email
      [support@prava.space](mailto:support@prava.space) with your account email, your entity/merchant name,
      and what you're requesting. We'll take it from there.
    </Info>
  </Step>

  <Step title="Swap keys and base URL">
    |          | Sandbox                           | Production                |
    | -------- | --------------------------------- | ------------------------- |
    | Keys     | `pk_test_*` / `sk_test_*`         | `pk_live_*` / `sk_live_*` |
    | Base URL | `https://sandbox.api.prava.space` | `https://api.prava.space` |

    Keys are environment-bound: a `sk_test_*` key against the production host fails with `AUTH_1001`.
  </Step>

  <Step title="Lock down your secret key">
    `sk_live_*` lives only in server-side env/secret storage, never in client code, version control,
    or logs. Rotate immediately if exposed.
  </Step>

  <Step title="Wire up failure handling">
    * Report **every** outcome via [Report Status](/api-reference/report-status), including `DECLINED`.
    * Handle session expiry (15 min): create sessions late, and re-create rather than reuse.
    * Log the `X-Response-ID` header from every Prava response; it's how support traces issues.
  </Step>
</Steps>

## Quick self-audit

| Check                                        | Where                                        |
| -------------------------------------------- | -------------------------------------------- |
| One full sandbox payment reached `completed` | [Testing in Sandbox](/api-reference/testing) |
| Production enabled + entity verified         | dashboard.prava.space                        |
| Live keys deployed server-side only          | your infra                                   |
| Declines and expiry handled + reported       | your code                                    |

Questions at any step: [support@prava.space](mailto:support@prava.space). Include the
`X-Response-ID` of any failing request.
