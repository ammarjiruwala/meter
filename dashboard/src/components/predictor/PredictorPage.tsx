"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import Lenis from "lenis";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

/**
 * The predictive-engine explainer, built as one interactive scene.
 *
 * The whole page hangs on a single metaphor: a prediction is a physical thing
 * moving through a machine. Every 3D plate, particle, and animated number serves
 * that, nothing is decoration for its own sake. All figures come from
 * predictor/DESIGN.md so the page cannot drift from the engine it describes.
 *
 * 3D is CSS `preserve-3d` rather than WebGL on purpose: real depth and
 * cursor-reactive parallax, none of the WebGL failure surface, and it degrades to
 * a flat static page under prefers-reduced-motion.
 */

// Seven stages (DESIGN.md §2). `readout` is the predicted-token figure visible when
// that stage is the active one in the engine; null means the deterministic waterfall
// has nothing to show yet.
const STAGES: {
  n: string;
  tag: string;
  title: string;
  body: string;
  formula: string;
  readout: number | null;
  note: string;
}[] = [
  {
    n: "0",
    tag: "Cache",
    title: "Have we seen this exact call?",
    body: "Same model, same messages, same max_tokens. If the ledger already holds this fingerprint, use what actually happened. A real outcome beats any heuristic.",
    formula: "key = sha256(model + messages + max_tokens)",
    readout: null,
    note: "cache miss",
  },
  {
    n: "1",
    tag: "Structural override",
    title: "Is the shape of the answer fixed?",
    body: "A JSON-schema response is bounded by its own structure. The input term stays in, because pulling entities from a 10k-token document is not the same size job as describing one user.",
    formula: "scope = 100 + input_tokens x 0.1",
    readout: null,
    note: "not schema-bound",
  },
  {
    n: "2",
    tag: "Explicit length",
    title: "Did the prompt state the length?",
    body: "If the user said how long, we do arithmetic instead of guessing. Where this fires it is the single most accurate rule in the system.",
    formula: '"in 3 sentences" gives 3 x 25 = 75',
    readout: null,
    note: "no length stated",
  },
  {
    n: "3",
    tag: "Task stacking",
    title: "No hard signal. Read the scope of work.",
    body: "A prompt is rarely one task. Summarize AND write the code is both, so scopes add rather than compete. Then verb intensity, chain-of-thought, and message shape multiply in.",
    formula: "scope = (150 + 250 + 500) x 1.5 x 1.0 x 1.5",
    readout: 2025,
    note: "scope built",
  },
  {
    n: "4",
    tag: "Safety buffer",
    title: "Aim high, on purpose.",
    body: "Under-predicting leaks a budget ceiling. Over-predicting holds a few cents for a few seconds. Those costs are not symmetric, so we aim over, per bucket, fitted in log space.",
    formula: "prediction = 2025 x buffer[code] (1.30)",
    readout: 2632,
    note: "buffer applied",
  },
  {
    n: "5",
    tag: "History",
    title: "Learn how this team prompts.",
    body: "Teams are consistent, because their prompts come from one template written by one person. A shrunk median correction nudges the estimate toward what this project actually does.",
    formula: "x factor,  factor = median(actual / predicted)",
    readout: 2632,
    note: "this team runs ~1.0",
  },
  {
    n: "6",
    tag: "Clamp + bound",
    title: "Two numbers leave the engine.",
    body: "max_tokens clamps the forecast, it never replaces it. The forecast says what this will probably cost. The bound says what it could cost at worst, and the ceiling reserves against that.",
    formula: "prediction = min(pred, bound)",
    readout: 2632,
    note: "bound 4096",
  },
];

const CONSTANTS: [string, string, "measured" | "property" | "guess"][] = [
  ["tokens per sentence", "25", "measured"],
  ["tokens per word", "1.33", "property"],
  ["base conversational scope", "150", "guess"],
  ["summary / code / extract / search", "+250 / +500 / +100 / +400", "guess"],
  ["verb intensity (build / fix)", "x1.5 / x0.6", "guess"],
  ["chain-of-thought", "x3.0", "guess"],
  ["safety buffer (default)", "1.30", "guess"],
  ["shrinkage k", "20", "guess"],
];

const PROV_LABEL = {
  measured: "measured",
  property: "property of English",
  guess: "guess, and fittable",
} as const;

// The trace lines for the self-typing terminal. `v` marks the animated count-up value.
const TRACE: { t: string; cls?: string; v?: number }[] = [
  { t: 'prompt  "Summarize this ticket and create the parser to fix it."' },
  { t: "" },
  { t: "3A · task scopes add up", cls: "c" },
  { t: "  base + summary + code   150 + 250 + 500", v: 900 },
  { t: "3B · verb intensity  create maps to build", cls: "c" },
  { t: "  x 1.5", v: 1350 },
  { t: "3C · chain-of-thought  none", cls: "c" },
  { t: "  x 1.0", v: 1350 },
  { t: "3D · instruction-to-context  short message", cls: "c" },
  { t: "  x 1.5", v: 2025 },
  { t: "4 · safety buffer  code bucket 1.30", cls: "c" },
  { t: "  x 1.30", v: 2632 },
  { t: "5 · history factor  this team ~1.0", cls: "c" },
  { t: "  x 1.00", v: 2632 },
  { t: "6 · clamp  no max_tokens, model ceiling", cls: "c" },
  { t: "  predicted_output_tokens", v: 2632 },
  { t: "  bound_output_tokens", v: 4096 },
  { t: "" },
  { t: "  predicted_cost_usd   $0.0184", cls: "s" },
];

const REDUCED = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function PredictorPage() {
  const [activeStage, setActiveStage] = useState(0);
  const readoutRef = useRef<HTMLSpanElement>(null);
  const engineRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  // Smooth momentum scroll + GSAP wiring. One RAF loop drives Lenis and feeds
  // ScrollTrigger, so the two never fight over scroll position.
  useEffect(() => {
    if (REDUCED()) return;
    gsap.registerPlugin(ScrollTrigger);

    const lenis = new Lenis({ duration: 1.1, smoothWheel: true });
    lenis.on("scroll", ScrollTrigger.update);
    const raf = (time: number) => lenis.raf(time * 1000);
    gsap.ticker.add(raf);
    gsap.ticker.lagSmoothing(0);

    const ctx = gsap.context(() => {
      // Reveal on scroll, staggered per section.
      gsap.utils.toArray<HTMLElement>(".reveal").forEach((el) => {
        gsap.from(el, {
          scrollTrigger: { trigger: el, start: "top 85%" },
          y: 40,
          opacity: 0,
          duration: 1,
          ease: "expo.out",
        });
      });

      // The pipeline engine: each stage row drives the active index and the big
      // readout as it passes the centre band.
      gsap.utils.toArray<HTMLElement>(".pipe-step").forEach((el, i) => {
        ScrollTrigger.create({
          trigger: el,
          start: "top 60%",
          end: "bottom 60%",
          onToggle: (self) => self.isActive && setActiveStage(i),
        });
      });
    }, rootRef);

    return () => {
      ctx.revert();
      gsap.ticker.remove(raf);
      lenis.destroy();
    };
  }, []);

  // Tween the big engine readout whenever the active stage changes.
  useEffect(() => {
    const el = readoutRef.current;
    if (!el) return;
    const target = STAGES[activeStage].readout;
    if (target == null) {
      el.textContent = "----";
      return;
    }
    if (REDUCED()) {
      el.textContent = target.toLocaleString();
      return;
    }
    const from = Number(el.textContent?.replace(/[^0-9]/g, "")) || 0;
    const obj = { v: from };
    const tween = gsap.to(obj, {
      v: target,
      duration: 0.9,
      ease: "expo.out",
      onUpdate: () => (el.textContent = Math.round(obj.v).toLocaleString()),
    });
    return () => {
      tween.kill();
    };
  }, [activeStage]);

  // Cursor-reactive depth on the hero engine.
  const onHeroMove = useCallback((e: React.MouseEvent) => {
    if (REDUCED()) return;
    const el = engineRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    el.style.setProperty("--rx", `${(-py * 16).toFixed(2)}deg`);
    el.style.setProperty("--ry", `${(px * 20).toFixed(2)}deg`);
  }, []);
  const onHeroLeave = useCallback(() => {
    const el = engineRef.current;
    if (el) {
      el.style.setProperty("--rx", "0deg");
      el.style.setProperty("--ry", "0deg");
    }
  }, []);

  return (
    <div className="px" ref={rootRef}>
      <Topbar />

      {/* ── HERO ─────────────────────────────────────────────── */}
      <section
        className="px-hero"
        onMouseMove={onHeroMove}
        onMouseLeave={onHeroLeave}
      >
        <div className="px-hero-grid wrap">
          <div className="px-hero-copy">
            <p className="section-label">The predictive engine</p>
            <h1 className="px-h1">
              We price the call <em>before</em> we make it.
            </h1>
            <p className="px-lede">
              Every other cost tool reads the bill after the money is gone. Meter
              reads the prompt and forecasts the bill first, in about three
              hundredths of a millisecond, with no network and no database.
            </p>
            <div className="px-hero-cta-row">
              <a href="#engine" className="hero-cta">
                See it compute <span className="arr">↓</span>
              </a>
              <span className="px-hero-stat">0.031ms · no I/O</span>
            </div>
          </div>

          {/* The engine object: seven translucent plates in real 3D, a token
              falling through them. Tilts toward the cursor. */}
          <div className="px-engine-stage">
            <div className="px-engine" ref={engineRef}>
              {STAGES.map((s, i) => (
                <div
                  className="px-plate"
                  key={s.n}
                  style={{ "--i": i } as React.CSSProperties}
                >
                  <span className="px-plate-n">{s.n}</span>
                  <span className="px-plate-tag">{s.tag}</span>
                </div>
              ))}
              <div className="px-token" aria-hidden="true" />
            </div>
          </div>
        </div>
        <div className="px-scrollhint" aria-hidden="true">
          <span>Scroll</span>
          <span className="px-drop" />
        </div>
      </section>

      {/* ── PROBLEM: interactive scatter ─────────────────────── */}
      <section className="px-sec wrap">
        <p className="section-label reveal">Why this is genuinely hard</p>
        <h2 className="px-h2 reveal">
          The obvious model is <span className="px-grad">wrong</span>, and we
          measured how wrong.
        </h2>
        <p className="px-body reveal">
          The tempting formula is <code>output ≈ ratio × input_tokens</code>.
          Longer prompt, longer answer. Toggle it on and watch the fit fall apart
          against real calls.
        </p>
        <Scatter />
        <div className="px-statrow reveal">
          {[
            ["+0.096", "correlation between input and output length"],
            ["0.9%", "of output variance that input length explains"],
            ["2", "task buckets that were negatively correlated"],
          ].map(([n, l]) => (
            <div className="px-stat" key={n}>
              <span className="px-stat-n">{n}</span>
              <span className="px-stat-l">{l}</span>
            </div>
          ))}
        </div>
        <blockquote className="px-quote reveal">
          Output length is set by the <b>scope of the work requested</b>, not by
          the length of the request.
        </blockquote>
      </section>

      {/* ── TWO NUMBERS: 3D flip cards ───────────────────────── */}
      <section className="px-sec wrap">
        <p className="section-label reveal">The structural trick</p>
        <h2 className="px-h2 reveal">
          Every call returns two numbers. <span className="px-grad">Hover to turn them over.</span>
        </h2>
        <div className="px-flips reveal">
          <FlipCard
            tag="predicted_output_tokens"
            front="What will this probably cost?"
            back="Dashboard figures, Treasurer runway, cost per outcome. Accurate is the job."
          />
          <FlipCard
            bound
            tag="bound_output_tokens"
            front="What could it cost at worst?"
            back="The hard ceiling reserves against this. With max_tokens set, output cannot exceed it, so the guarantee is structural, not statistical."
          />
        </div>
      </section>

      {/* ── PIPELINE: scroll-driven engine readout ───────────── */}
      <section className="px-sec wrap" id="engine">
        <p className="section-label reveal">The pipeline, end to end</p>
        <h2 className="px-h2 reveal">
          Seven stages. Hard data exits early, soft signals stack.
        </h2>
        <div className="px-pipe-layout">
          {/* Sticky readout: the number the engine is holding right now. */}
          <aside className="px-readout">
            <div className="px-readout-card">
              <span className="px-readout-label">predicted tokens</span>
              <span className="px-readout-n" ref={readoutRef}>
                ----
              </span>
              <span className="px-readout-note">
                {STAGES[activeStage].note}
              </span>
              <div className="px-readout-track">
                {STAGES.map((s, i) => (
                  <span
                    key={s.n}
                    className={`px-readout-pip${i === activeStage ? " on" : ""}${
                      i < activeStage ? " done" : ""
                    }`}
                  />
                ))}
              </div>
            </div>
          </aside>

          <ol className="px-pipe">
            {STAGES.map((s, i) => (
              <li
                className={`pipe-step px-pipe-step${
                  i === activeStage ? " active" : ""
                }`}
                key={s.n}
              >
                <div className="px-pipe-num">{s.n}</div>
                <div className="px-pipe-body">
                  <span className="px-pipe-tag">{s.tag}</span>
                  <h3 className="px-pipe-title">{s.title}</h3>
                  <p className="px-pipe-text">{s.body}</p>
                  <code className="px-formula">{s.formula}</code>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── WORKED EXAMPLE: self-typing terminal ─────────────── */}
      <section className="px-sec wrap">
        <p className="section-label reveal">Watch it compute</p>
        <h2 className="px-h2 reveal">
          One prompt, <span className="px-grad">every step shown.</span>
        </h2>
        <Terminal />
        <div className="px-fastpath reveal">
          <span className="px-fastpath-tag">fast path</span>
          <p>
            Had the prompt said <b>&quot;in 3 sentences&quot;</b>, stage 2 fires
            first and short-circuits all of it: <code>3 × 25 = 75</code>, then
            straight to the buffer. Stated length is the most accurate rule we
            have, so we never guess past it.
          </p>
        </div>
      </section>

      {/* ── HONESTY: provenance ──────────────────────────────── */}
      <section className="px-sec wrap">
        <p className="section-label reveal">What is measured, what is a guess</p>
        <h2 className="px-h2 reveal">
          We label every constant, <span className="px-grad">including the soft ones.</span>
        </h2>
        <p className="px-body reveal">
          A number you cannot trace is a number you cannot trust. Each guess below
          is a fittable parameter. As the ledger fills, stages 4 and 5 replace
          them with measured values, which is the whole reason the learner has
          anything to learn.
        </p>
        <div className="px-table reveal">
          {CONSTANTS.map(([name, val, kind]) => (
            <div className="px-table-row" key={name}>
              <span className="px-table-name">{name}</span>
              <span className="px-table-val">{val}</span>
              <span className={`px-badge ${kind}`}>{PROV_LABEL[kind]}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ── THE FEAT: 3D loop ────────────────────────────────── */}
      <section className="px-sec wrap">
        <p className="section-label reveal">Why this is a first</p>
        <h2 className="px-h2 reveal">
          The loop the prior art left <span className="px-grad">dead.</span>
        </h2>
        <p className="px-body reveal">
          The estimators we evaluated stopped at the guess. They never fed real
          usage back, so their learning tier was permanently inert. Meter closes
          the loop: at capture, the actual token count lands in the ledger next to
          the prediction that reserved for it.
        </p>
        <LoopRing />
        <p className="px-body px-muted reveal">
          Once a bucket clears thirty real rows its correction goes live and its
          label flips from <code>prior</code> to <code>learned</code>. That flip
          is the visible moment the engine stopped guessing and started knowing.
        </p>
      </section>

      {/* ── CTA ──────────────────────────────────────────────── */}
      <section className="px-cta wrap">
        <h2 className="reveal">
          Every row in the ledger was <em>reserved before it happened.</em>
        </h2>
        <p className="reveal">
          See the predictions land against their actuals, live, on the dashboard.
        </p>
        <Link href="/dashboard" className="hero-cta reveal">
          Open dashboard <span className="arr">→</span>
        </Link>
      </section>

      <footer className="px-footer wrap">
        <span>Meter — the autonomous inference treasurer</span>
        <span>predictor/DESIGN.md is the source for every number here</span>
      </footer>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────── */

function Topbar() {
  return (
    <div className="topbar scrolled">
      <div className="wrap">
        <Link href="/" className="mark">
          <span className="dot" />
          METER
        </Link>
        <nav>
          <Link href="/" className="glass-pill">
            Home
          </Link>
          <Link href="/dashboard" className="glass-cta">
            Open dashboard <span className="arr">→</span>
          </Link>
        </nav>
      </div>
    </div>
  );
}

function FlipCard({
  tag,
  front,
  back,
  bound,
}: {
  tag: string;
  front: string;
  back: string;
  bound?: boolean;
}) {
  return (
    <div className={`px-flip${bound ? " bound" : ""}`}>
      <div className="px-flip-inner">
        <div className="px-flip-face">
          <span className="px-flip-tag">{tag}</span>
          <p className="px-flip-q">{front}</p>
          <span className="px-flip-hint">hover →</span>
        </div>
        <div className="px-flip-face px-flip-back">
          <p className="px-flip-a">{back}</p>
        </div>
      </div>
    </div>
  );
}

// Interactive proof: toggle between "predict by input length" (a flat, useless
// line) and "predict by scope" (points line up). Positions are illustrative, the
// correlation figure they dramatise is the real +0.096 from DESIGN.md.
const POINTS = [
  [12, 62], [18, 20], [40, 86], [55, 14], [30, 70], [8, 45],
  [70, 30], [22, 92], [48, 55], [90, 18], [35, 40], [60, 78],
  [15, 88], [80, 25], [25, 12],
];
function Scatter() {
  const [byScope, setByScope] = useState(false);
  const W = 100, H = 100;
  return (
    <div className="px-scatter reveal">
      <div className="px-scatter-head">
        <div className="px-toggle">
          <button
            className={!byScope ? "on" : ""}
            onClick={() => setByScope(false)}
          >
            predict by input length
          </button>
          <button
            className={byScope ? "on" : ""}
            onClick={() => setByScope(true)}
          >
            predict by scope
          </button>
        </div>
        <span className="px-scatter-verdict">
          {byScope ? (
            <b className="ok">points align — R² is real</b>
          ) : (
            <b className="bad">no line fits — R² = 0.9%</b>
          )}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="px-scatter-svg" preserveAspectRatio="none">
        {/* The fit line: flat and wrong for input length, diagonal and tight for scope. */}
        <line
          className={`px-fit${byScope ? " ok" : " bad"}`}
          x1="0"
          y1={byScope ? 95 : 55}
          x2="100"
          y2={byScope ? 8 : 48}
        />
        {POINTS.map(([x, y], i) => {
          // In scope mode, snap points toward the diagonal so the eye sees the fit.
          const sy = byScope ? 100 - x * 0.9 - 5 : y;
          return (
            <circle
              key={i}
              cx={x}
              cy={sy}
              r="2.2"
              className={`px-dot${byScope ? " ok" : ""}`}
              style={{ transition: "cy 600ms cubic-bezier(0.16,1,0.3,1)" }}
            />
          );
        })}
      </svg>
      <div className="px-scatter-ax">
        <span>input tokens →</span>
        <span>↑ output tokens</span>
      </div>
    </div>
  );
}

function Terminal() {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(0); // lines revealed
  const [counts, setCounts] = useState<Record<number, number>>({});

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (REDUCED()) {
      // ponytail: rAF only to keep the state write out of the effect body
      // (react-hooks/set-state-in-effect); REDUCED() needs matchMedia, so it
      // can't be a useState initializer under SSR.
      const id = requestAnimationFrame(() => {
        setShown(TRACE.length);
        const final: Record<number, number> = {};
        TRACE.forEach((l, i) => l.v != null && (final[i] = l.v));
        setCounts(final);
      });
      return () => cancelAnimationFrame(id);
    }
    let started = false;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !started) {
          started = true;
          io.disconnect();
          let i = 0;
          const tick = () => {
            i += 1;
            setShown(i);
            const line = TRACE[i - 1];
            if (line?.v != null) {
              const target = line.v;
              const step = Math.max(1, Math.round(target / 22));
              let cur = 0;
              const idx = i - 1;
              const count = () => {
                cur = Math.min(target, cur + step);
                setCounts((c) => ({ ...c, [idx]: cur }));
                if (cur < target) requestAnimationFrame(count);
              };
              count();
            }
            if (i < TRACE.length) setTimeout(tick, 120);
          };
          tick();
        }
      },
      { threshold: 0.3 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div className="px-term reveal" ref={ref}>
      <div className="px-term-head">
        <div className="px-term-dots">
          <span />
          <span />
          <span />
        </div>
        <span className="px-term-name">predict.trace</span>
      </div>
      <pre className="px-term-body">
        {TRACE.slice(0, shown).map((l, i) => (
          <div key={i} className={l.cls ? `px-t-${l.cls}` : undefined}>
            {l.t}
            {l.v != null && (
              <span className="px-t-num">
                {" "}
                {(counts[i] ?? 0).toLocaleString()}
              </span>
            )}
          </div>
        ))}
        {shown < TRACE.length && <span className="px-term-caret" />}
      </pre>
    </div>
  );
}

const LOOP = ["predict", "reserve", "call", "capture", "refit"];
function LoopRing() {
  return (
    <div className="px-loop reveal">
      <div className="px-loop-ring">
        {LOOP.map((label, i) => (
          <div
            className={`px-loop-node${label === "capture" ? " accent" : ""}${
              label === "refit" ? " gold" : ""
            }`}
            key={label}
            style={
              { "--a": `${(360 / LOOP.length) * i}deg` } as React.CSSProperties
            }
          >
            {label}
          </div>
        ))}
        <div className="px-loop-orbit" aria-hidden="true">
          <span className="px-loop-particle" />
        </div>
        <div className="px-loop-core">
          actual
          <br />
          feeds
          <br />
          forecast
        </div>
      </div>
    </div>
  );
}
