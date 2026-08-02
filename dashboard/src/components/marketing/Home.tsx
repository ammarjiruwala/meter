"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Intro } from "./Intro";

const RING_1 = [
  { t: "Explain" },
  { t: "quantum", cls: "hot", cost: "$0.003" },
  { t: "computing" },
  { t: "summarize", cls: "gold" },
  { t: "this" },
  { t: "document", cls: "hot", cost: "$0.005" },
  { t: "write" },
  { t: "code", cls: "mint" },
  { t: "parse" },
  { t: "returns", cls: "hot", cost: "$0.009" },
];

const RING_2 = [
  { t: "Debug" },
  { t: "trace", cls: "hot", cost: "$0.004" },
  { t: "SQL", cls: "gold" },
  { t: "query" },
  { t: "refactor", cls: "hot", cost: "$0.002" },
  { t: "hooks", cls: "mint" },
  { t: "translate" },
  { t: "please", cls: "hot", cost: "$0.005" },
];

const SLIDES = [
  {
    accent: "coral",
    num: "01",
    h: "Meter every call.",
    p: "Change one base URL. Every AI call now passes through Meter — priced, attributed, and written to the ledger with a p50 overhead of 1.49ms.",
    foot: "✓ Attribution recorded on every row",
  },
  {
    accent: "gold",
    num: "02",
    h: "Pay while you sleep.",
    p: "When the provider balance runs low, the Treasurer agent charges a pre-approved Prava mandate and tops up the wallet before anything fails. You get the iMessage in the morning.",
    foot: "✓ Auto top-up via Prava mandate",
  },
  {
    accent: "mint",
    num: "03",
    h: "Cut spend anomalies.",
    p: "Named after the fuse box in a house. When one feature runs 50× normal, the Circuit Breaker cuts it off. Everything else keeps flowing. Leaked keys die immediately.",
    foot: "✓ Per-feature circuit breaker",
  },
];

const SLIDE_MS = 6000;
const SECTIONS = ["hero-section", "overview", "usage"];

export function Home() {
  const scroller = useRef<HTMLDivElement>(null);
  const [landed, setLanded] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [progress, setProgress] = useState(0);
  const [activeSection, setActiveSection] = useState(0);
  const [slide, setSlide] = useState(0);
  const [slideProgress, setSlideProgress] = useState(0);
  const [copied, setCopied] = useState<string | null>(null);

  // The hero waits for the intro rather than a duplicated timer, so retuning one
  // cannot leave the other behind.
  useEffect(() => {
    const land = () => setLanded(true);
    window.addEventListener("meter:intro-done", land);
    return () => window.removeEventListener("meter:intro-done", land);
  }, []);

  // `.snap-container` is the scrolling element, not the window — it has its own
  // `overflow-y: auto`. Listening on window here would silently never fire, which
  // is the kind of bug that looks like "the progress bar just doesn't work".
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;

    const onScroll = () => {
      const max = el.scrollHeight - el.clientHeight;
      setProgress(max > 0 ? (el.scrollTop / max) * 100 : 0);
      setScrolled(el.scrollTop > 40);

      let current = 0;
      SECTIONS.forEach((id, i) => {
        const s = document.getElementById(id);
        if (s && s.getBoundingClientRect().top <= el.clientHeight * 0.5) {
          current = i;
        }
      });
      setActiveSection(current);
    };

    onScroll();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Reveal-on-scroll. The root is the snap container for the same reason as above.
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const targets = el.querySelectorAll(".reveal, .step");
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) e.target.classList.add("in-view");
        });
      },
      { root: el, threshold: 0.15 },
    );
    targets.forEach((t) => io.observe(t));
    return () => io.disconnect();
  }, []);

  // Carousel autoplay, driven by one 80ms ticker so the progress bar and the slide
  // change cannot drift out of step with each other.
  useEffect(() => {
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still) return;
    const step = 80;
    const id = setInterval(() => {
      setSlideProgress((p) => {
        const next = p + (step / SLIDE_MS) * 100;
        if (next >= 100) {
          setSlide((s) => (s + 1) % SLIDES.length);
          return 0;
        }
        return next;
      });
    }, step);
    return () => clearInterval(id);
  }, []);

  const goto = useCallback((i: number) => {
    setSlide((i + SLIDES.length) % SLIDES.length);
    setSlideProgress(0);
  }, []);

  const copy = useCallback(async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id);
      setTimeout(() => setCopied(null), 1600);
    } catch {
      // Clipboard is permission-gated and blocked outright in some embeds. Failing
      // silently is right here — the snippet is on screen and can be selected.
    }
  }, []);

  const jump = (id: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <>
      <Intro />

      <div className="progress" style={{ width: `${progress}%` }} />

      <div className={`topbar${scrolled ? " scrolled" : ""}`}>
        <div className="wrap">
          <span className="mark">
            <span className="dot" />
            METER
          </span>
          <nav>
            <a href="#overview" className="glass-pill" onClick={jump("overview")}>
              Overview
            </a>
            <a href="#usage" className="glass-pill" onClick={jump("usage")}>
              How to use
            </a>
            {/* A real navigation, not an in-page jump: the dashboard is a separate
                root layout, so this is deliberately a full page load. */}
            <Link href="/dashboard" className="glass-cta">
              Open dashboard <span className="arr">→</span>
            </Link>
          </nav>
        </div>
      </div>

      <div className="section-dots">
        {SECTIONS.map((id, i) => (
          <a
            key={id}
            href={`#${id}`}
            onClick={jump(id)}
            className={activeSection === i ? "active" : undefined}
            aria-label={id.replace("-section", "")}
          />
        ))}
      </div>

      <div className="snap-container" ref={scroller}>
        {/* ── HERO ───────────────────────────────────────────────── */}
        <section
          className={`snap-section hero${landed ? " landed" : ""}`}
          id="hero-section"
        >
          <div className="orbit-container">
            <div className="orbit-ring ring-1">
              {RING_1.map((tok, i) => (
                <div
                  key={tok.t}
                  className="t3d"
                  style={
                    {
                      "--a": `${(360 / RING_1.length) * i}deg`,
                      "--r": "300px",
                    } as React.CSSProperties
                  }
                >
                  <span className={`tk${tok.cls ? ` ${tok.cls}` : ""}`}>
                    {tok.t}
                    {tok.cost && <span className="cost">{tok.cost}</span>}
                  </span>
                </div>
              ))}
            </div>
            <div className="orbit-ring ring-2">
              {RING_2.map((tok, i) => (
                <div
                  key={tok.t}
                  className="t3d"
                  style={
                    {
                      "--a": `${(360 / RING_2.length) * i}deg`,
                      "--r": "240px",
                    } as React.CSSProperties
                  }
                >
                  <span className={`tk${tok.cls ? ` ${tok.cls}` : ""}`}>
                    {tok.t}
                    {tok.cost && <span className="cost">{tok.cost}</span>}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {(
            [
              ["22%", "14%", "1.8s", "7s", "8px", "-12px"],
              ["68%", "78%", "2.4s", "8s", "-10px", "8px"],
              ["35%", "82%", "3s", "6s", "6px", "-10px"],
              ["72%", "20%", "2.1s", "9s", "-8px", "6px"],
            ] as const
          ).map(([top, left, delay, dur, x2, y2], i) => (
            <div
              key={i}
              className="cost-float"
              style={
                {
                  top,
                  left,
                  "--delay": delay,
                  "--dur": dur,
                  "--x1": "0px",
                  "--y1": "0px",
                  "--x2": x2,
                  "--y2": y2,
                } as React.CSSProperties
              }
            >
              {["$0.0012", "$0.0034", "$0.0091", "$0.0044"][i]}
            </div>
          ))}

          <div className="hero-center">
            <div className={`hero-glow${landed ? " animate" : ""}`} />
            <h1 className={`hero-name${landed ? " animate" : ""}`}>
              {["M", "E", "T", "E", "R"].map((ch, i) => (
                <span
                  key={i}
                  className={`letter${i === 2 ? " accent" : ""}`}
                  style={{ "--i": i } as React.CSSProperties}
                >
                  {ch}
                </span>
              ))}
            </h1>
            <p className={`hero-tagline${landed ? " animate" : ""}`}>
              AI infrastructure that pays its own bills
            </p>
          </div>

          <div className={`scroll-hint${landed ? " animate" : ""}`} aria-hidden="true">
            <span>Scroll</span>
            <span className="line-drop" />
          </div>
        </section>

        {/* ── OVERVIEW ───────────────────────────────────────────── */}
        <section className="snap-section overview" id="overview">
          <div className="wrap">
            <div className="overview-layout">
              <div className="overview-text">
                <p className="section-label reveal">What Meter is</p>
                <h2 className="reveal d1">
                  A treasury agent that <em>happens to make charts.</em>
                </h2>
                <p className="lede reveal d2">
                  Every observability tool shows you the graph. Meter pays the
                  bill. It sits in the request path, sees every AI call your
                  company makes, and quietly does the work no dashboard has ever
                  done.
                </p>
                <div className="live-badge reveal d3">
                  <span className="live-dot" />
                  Live · <b>$847.31</b> metered today
                </div>
              </div>

              <div className="carousel reveal d2">
                <div className="carousel-viewport">
                  <div
                    className="carousel-track"
                    style={{ transform: `translateX(-${slide * 100}%)` }}
                  >
                    {SLIDES.map((s) => (
                      <div
                        key={s.num}
                        className="carousel-slide"
                        data-accent={s.accent}
                      >
                        <div className="slide-bg-num">{s.num}</div>
                        <div className="slide-accent-line" />
                        <h3>{s.h}</h3>
                        <p>{s.p}</p>
                        <div className="slide-foot">{s.foot}</div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="carousel-controls">
                  <div className="carousel-counter">
                    <span className="current">
                      {String(slide + 1).padStart(2, "0")}
                    </span>
                    <span>/</span>
                    <span>{String(SLIDES.length).padStart(2, "0")}</span>
                  </div>
                  <div className="carousel-dots">
                    {SLIDES.map((s, i) => (
                      <button
                        key={s.num}
                        className={`carousel-dot${slide === i ? " active" : ""}`}
                        data-index={i}
                        onClick={() => goto(i)}
                        aria-label={`Slide ${i + 1}`}
                      />
                    ))}
                  </div>
                  <div className="carousel-arrows">
                    <button
                      className="carousel-btn"
                      onClick={() => goto(slide - 1)}
                      aria-label="Previous"
                    >
                      ←
                    </button>
                    <button
                      className="carousel-btn"
                      onClick={() => goto(slide + 1)}
                      aria-label="Next"
                    >
                      →
                    </button>
                  </div>
                </div>

                <div className="carousel-progress">
                  <div
                    className={`carousel-progress-fill accent-${SLIDES[slide].accent}`}
                    style={{ width: `${slideProgress}%` }}
                  />
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── USAGE ──────────────────────────────────────────────── */}
        <section className="snap-section usage" id="usage">
          <div className="wrap">
            <p className="section-label reveal">How to use it</p>
            <h2 className="reveal d1">Three steps. All of it real.</h2>
            <p className="lede reveal d2">
              Every snippet below runs against a live Meter instance. No mocks, no
              illustrations. Install takes about a minute.
            </p>

            <Step
              num="01"
              tag="Point at Meter"
              title="Change one base URL."
              foot="✓ Attribution recorded on every row"
              body={
                <>
                  Your app normally talks straight to <b>api.openai.com</b>. Point
                  it at Meter instead. Now every request arrives at our door — we
                  look at it, price it, write it down, and forward it on. Anthropic
                  works the same way.
                </>
              }
              file=".env"
              copyId="env"
              copied={copied === "env"}
              onCopy={copy}
              raw={`OPENAI_BASE_URL=https://meter.acme.dev/v1
OPENAI_API_KEY=mtr_platformeng_e7c9a1b2

ANTHROPIC_BASE_URL=https://meter.acme.dev/v1
ANTHROPIC_API_KEY=mtr_platformeng_e7c9a1b2`}
              code={
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
              }
            />

            <Step
              num="02"
              tag="Budgets as code"
              title="Set ceilings per project and per feature."
              foot="✓ Rolling 24h · settled + in-flight holds"
              body={
                <>
                  When a limit is hit, the refusal names the exact scope in{" "}
                  <b>X-Meter-Budget-Scope</b>, so a developer reading a 429 knows
                  which line to raise. Two ways in, one place it lands.
                </>
              }
              file="meter.yaml"
              copyId="yaml"
              copied={copied === "yaml"}
              onCopy={copy}
              raw={`projects:
  - id: acme-app
    ceiling_usd_day: 200
    features:
      - id: summarize
        ceiling_usd_day: 50
      - id: chat
        ceiling_usd_day: 120`}
              code={
                <>
                  <span className="k">projects</span>:{"\n"}
                  {"  - "}
                  <span className="k">id</span>: <span className="s">acme-app</span>
                  {"\n    "}
                  <span className="k">ceiling_usd_day</span>:{" "}
                  <span className="n">200</span>
                  {"\n    "}
                  <span className="k">features</span>:{"\n"}
                  {"      - "}
                  <span className="k">id</span>:{" "}
                  <span className="s">summarize</span>
                  {"\n        "}
                  <span className="k">ceiling_usd_day</span>:{" "}
                  <span className="n">50</span>
                  {"\n"}
                  {"      - "}
                  <span className="k">id</span>: <span className="s">chat</span>
                  {"\n        "}
                  <span className="k">ceiling_usd_day</span>:{" "}
                  <span className="n">120</span>
                </>
              }
            />

            {/* ⚠ RECONSTRUCTED — the pasted design was truncated at the 50k limit
                partway through step 02, so step 03 and the final CTA below are
                written from the real product surface rather than from the design.
                Replace when the tail arrives. */}
            <Step
              num="03"
              tag="Close the loop"
              title="Tell Meter what a call was worth."
              foot="✓ Cost per resolved outcome, not cost per token"
              body={
                <>
                  Meter cannot know whether a support ticket was resolved — so you
                  tell it. Post an outcome against a <b>trace_id</b> and the ledger
                  turns from a cost report into a margin report.
                </>
              }
              file="annotate.sh"
              copyId="annotate"
              copied={copied === "annotate"}
              onCopy={copy}
              raw={`curl -X POST https://meter.acme.dev/v1/annotate \\
  -H "Authorization: Bearer mtr_platformeng_e7c9a1b2" \\
  -d '{"trace_id":"tkt_9812","outcome":"resolved","value_usd":40}'`}
              code={
                <>
                  <span className="k">curl</span> -X POST{" "}
                  <span className="s">
                    https://meter.acme.dev/v1/annotate
                  </span>{" "}
                  \{"\n  "}
                  -H{" "}
                  <span className="s">
                    &quot;Authorization: Bearer mtr_platformeng_e7c9a1b2&quot;
                  </span>{" "}
                  \{"\n  "}
                  -d{" "}
                  <span className="s">
                    {
                      '\'{"trace_id":"tkt_9812","outcome":"resolved","value_usd":40}\''
                    }
                  </span>
                </>
              }
            />
          </div>

          <div className="wrap">
            <div className="final-cta">
              <h2>
                Stop watching the graph. <em>Start paying the bill.</em>
              </h2>
              <p>
                Meter is metering, budgeting, alerting and transacting today. The
                dashboard is live — go look at what it already knows.
              </p>
              <Link href="/dashboard" className="hero-cta">
                Open the dashboard <span className="arr">→</span>
              </Link>
            </div>
          </div>

          <footer>
            <div className="wrap">
              <span>Meter — the autonomous inference treasurer</span>
              <span>Built for the Prava Agentic Commerce Hackathon</span>
            </div>
          </footer>
        </section>
      </div>
    </>
  );
}

function Step({
  num,
  tag,
  title,
  body,
  foot,
  file,
  code,
  raw,
  copyId,
  copied,
  onCopy,
}: {
  num: string;
  tag: string;
  title: string;
  body: React.ReactNode;
  foot: string;
  file: string;
  code: React.ReactNode;
  raw: string;
  copyId: string;
  copied: boolean;
  onCopy: (id: string, text: string) => void;
}) {
  return (
    <div className="step">
      <div>
        <div className="step-marker">
          <span className="num">{num}</span>
          <span className="tag">{tag}</span>
        </div>
        <h3>{title}</h3>
        <p>{body}</p>
        <div className="foot">{foot}</div>
      </div>
      <div className="code">
        <div className="head">
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div className="dots">
              <span />
              <span />
              <span />
            </div>
            <span className="fname">{file}</span>
          </div>
          <button
            className={`copy${copied ? " copied" : ""}`}
            onClick={() => onCopy(copyId, raw)}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <pre>{code}</pre>
      </div>
    </div>
  );
}
