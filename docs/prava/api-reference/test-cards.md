> ## Documentation Index
> Fetch the complete documentation index at: https://docs.prava.space/llms.txt
> Use this file to discover all available pages before exploring further.

# Test Cards

> Sandbox test card numbers and the test OTP, organized by card network.

Use these values to exercise the full payment flow in sandbox. They work like real cards but never
move money. More networks will appear here as they're supported.

<Warning>
  **Sandbox only.** These values work only on `sandbox.api.prava.space` /
  `sandbox.collect.prava.space`. They are declined everywhere else.
</Warning>

## Visa

| Card number           | CVV   | Expiry  |
| --------------------- | ----- | ------- |
| `4622 9431 2313 7789` | `757` | `12/27` |
| `4622 9431 2313 7797` | `640` | `12/27` |
| `4622 9431 2313 7805` | `304` | `12/27` |
| `4622 9431 2313 7847` | `698` | `12/27` |
| `4622 9431 2313 7854` | `799` | `12/27` |
| `4622 9431 2313 7862` | `938` | `12/27` |
| `4622 9431 2313 7870` | `966` | `12/27` |
| `4622 9431 2313 7888` | `408` | `12/27` |
| `4622 9431 2313 7896` | `499` | `12/27` |
| `4622 9431 2313 7904` | `890` | `12/27` |
| `4622 9431 2313 7912` | `999` | `12/27` |

## Test OTP

When card verification asks for an OTP (the one-time code your bank would normally text you), enter:

```
456789
```

## Next

<CardGroup cols={2}>
  <Card title="Testing in Sandbox" icon="flask" href="/api-reference/testing">
    The full sandbox test run, step by step.
  </Card>

  <Card title="Errors" icon="triangle-exclamation" href="/api-reference/errors">
    Every code you might hit, with recovery steps.
  </Card>
</CardGroup>
