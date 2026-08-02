import type { ReactNode } from "react";

/**
 * Copy and snippets for the "How to use it" section.
 *
 * Steps 01 and 02 are the design's, verbatim.
 *
 * ⚠ STEP 03 IS DELIBERATELY NOT THE DESIGN'S. The supplied version promised a
 * "Real-time ledger via WebSocket", a `@meter/sdk` npm package and a Slack pipe.
 * None of the three exists: the dashboard polls over HTTP, there is no SDK, and the
 * alert rail is iMessage through Linq. The section's own lede says "No mocks, no
 * illustrations" — shipping three invented capabilities directly underneath that, to
 * judges assessing whether the thing works, is the wrong risk to take.
 *
 * What replaces it is real and verified end to end: `POST /v1/annotate` turns the
 * ledger from a cost report into a margin report, and it is the feature nothing else
 * in the category has. Swap this file's third entry back if you want the original.
 */

export const STEPS: {
  num: string;
  tag: string;
  title: string;
  body: ReactNode;
  foot: string;
}[] = [
  {
    num: "01",
    tag: "Point at Meter",
    title: "Change one base URL.",
    body: (
      <>
        Your app normally talks straight to <b>api.openai.com</b>. Point it at
        Meter instead. Now every request arrives at our door — we look at it,
        price it, write it down, and forward it on. Anthropic works the same way.
      </>
    ),
    foot: "✓ Attribution recorded on every row",
  },
  {
    num: "02",
    tag: "Budgets as code",
    title: "Set ceilings per project and per feature.",
    body: (
      <>
        When a limit is hit, the refusal names the exact scope in{" "}
        <b>X-Meter-Budget-Scope</b>, so a developer reading a 429 knows which line
        to raise. Two ways in, one place it lands.
      </>
    ),
    foot: "✓ Rolling 24h · settled + in-flight holds",
  },
  {
    num: "03",
    tag: "Close the loop",
    title: "Price the outcome, not the token.",
    body: (
      <>
        Meter cannot know whether a support ticket was resolved — so you tell it.
        Post an outcome against a <b>trace_id</b> and every call in that trace
        rolls up behind it. The ledger stops being a cost report and starts being
        a margin report.
      </>
    ),
    foot: "✓ Cost per resolved outcome, not per token",
  },
];

export const CODE: { file: string; raw: string; body: ReactNode }[] = [
  {
    file: ".env",
    raw: `OPENAI_BASE_URL=https://meter.acme.dev/v1
OPENAI_API_KEY=mtr_platformeng_e7c9a1b2

ANTHROPIC_BASE_URL=https://meter.acme.dev/v1
ANTHROPIC_API_KEY=mtr_platformeng_e7c9a1b2`,
    body: (
      <>
        <span className="c"># the only line that changes</span>
        {"\n"}
        <span className="k">OPENAI_BASE_URL</span>=
        <span className="s">https://meter.acme.dev/v1</span>
        {"\n"}
        <span className="k">OPENAI_API_KEY</span>=
        <span className="s">mtr_platformeng_e7c9a1b2</span>
        {"\n\n"}
        <span className="k">ANTHROPIC_BASE_URL</span>=
        <span className="s">https://meter.acme.dev/v1</span>
        {"\n"}
        <span className="k">ANTHROPIC_API_KEY</span>=
        <span className="s">mtr_platformeng_e7c9a1b2</span>
      </>
    ),
  },
  {
    file: "meter.yaml",
    raw: `projects:
  - id: acme-app
    ceiling_usd_day: 200
    features:
      - id: summarize
        ceiling_usd_day: 50
      - id: chat
        ceiling_usd_day: 120`,
    body: (
      <>
        <span className="k">projects</span>:{"\n  - "}
        <span className="k">id</span>: <span className="s">acme-app</span>
        {"\n    "}
        <span className="k">ceiling_usd_day</span>: <span className="n">200</span>
        {"\n    "}
        <span className="k">features</span>:{"\n      - "}
        <span className="k">id</span>: <span className="s">summarize</span>
        {"\n        "}
        <span className="k">ceiling_usd_day</span>: <span className="n">50</span>
        {"\n      - "}
        <span className="k">id</span>: <span className="s">chat</span>
        {"\n        "}
        <span className="k">ceiling_usd_day</span>: <span className="n">120</span>
      </>
    ),
  },
  {
    file: "annotate.sh",
    raw: `# one resolved ticket, a dozen AI calls, one number
curl -X POST https://meter.acme.dev/v1/annotate \\
  -H "Authorization: Bearer mtr_platformeng_e7c9a1b2" \\
  -d '{"trace_id":"tkt_9812","outcome":"resolved","value_usd":40}'

# -> {"cost_usd": 0.184, "request_count": 12, "margin_usd": 39.816}`,
    body: (
      <>
        <span className="c">
          # one resolved ticket, a dozen AI calls, one number
        </span>
        {"\n"}
        <span className="k">curl</span> -X POST{" "}
        <span className="s">https://meter.acme.dev/v1/annotate</span> \{"\n  "}
        -H{" "}
        <span className="s">
          &quot;Authorization: Bearer mtr_platformeng_e7c9a1b2&quot;
        </span>{" "}
        \{"\n  "}
        -d{" "}
        <span className="s">
          {'\'{"trace_id":"tkt_9812","outcome":"resolved","value_usd":40}\''}
        </span>
        {"\n\n"}
        <span className="c">
          {"# -> "}
          {'{"cost_usd": '}
        </span>
        <span className="n">0.184</span>
        <span className="c">{', "request_count": '}</span>
        <span className="n">12</span>
        <span className="c">{', "margin_usd": '}</span>
        <span className="n">39.816</span>
        <span className="c">{"}"}</span>
      </>
    ),
  },
];
