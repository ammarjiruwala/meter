"use client";

import { useEffect, useRef, useState } from "react";

/**
 * The opening sequence, timed exactly as the design's script: three coins arrive, the
 * meter counts up, then it zooms through into the hero.
 *
 * The counter is a real rAF tween between the design's figures ($1.23 → $4.56 → $9.87)
 * rather than three snapped values — a display that jumps reads as a slideshow, and the
 * whole point of the device is that it is metering.
 */
type Beat = { at: number; run: () => void };

export function Intro() {
  const [hidden, setHidden] = useState(false);
  const [fading, setFading] = useState(false);
  const [zooming, setZooming] = useState(false);
  const [active, setActive] = useState(false);
  const [lit, setLit] = useState(false);
  const [gold, setGold] = useState(false);
  const [flicker, setFlicker] = useState(0);
  const [slot, setSlot] = useState(0);
  const [burst, setBurst] = useState(false);
  const [fill, setFill] = useState(0);
  const [value, setValue] = useState("$0.00");

  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const raf = useRef<number | null>(null);

  useEffect(() => {
    const tween = (from: number, to: number, ms: number) => {
      const t0 = performance.now();
      const step = (now: number) => {
        const p = Math.min((now - t0) / ms, 1);
        setValue(`$${(from + (to - from) * p).toFixed(2)}`);
        if (p < 1) raf.current = requestAnimationFrame(step);
      };
      raf.current = requestAnimationFrame(step);
    };

    const finish = () => {
      document.body.classList.remove("no-scroll");
      // The hero listens for this rather than running a duplicate timer, so retuning
      // one side cannot leave the other behind.
      window.dispatchEvent(new Event("meter:intro-done"));
    };

    // Anyone who asked their OS to stop motion gets no sequence. The CSS hides the
    // overlay for them — but the page is also locked behind `no-scroll` until this
    // finishes, so without releasing it here they would be left on a frozen page.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      finish();
      return;
    }

    const beats: Beat[] = [
      { at: 600, run: () => { setActive(true); setLit(true); } },
      { at: 700, run: () => setSlot((n) => n + 1) },
      { at: 850, run: () => { tween(0, 1.23, 800); setFill(15); } },
      { at: 1500, run: () => setSlot((n) => n + 1) },
      { at: 1650, run: () => setFlicker((n) => n + 1) },
      { at: 1800, run: () => { setGold(true); tween(1.23, 4.56, 800); setFill(45); } },
      { at: 2300, run: () => setSlot((n) => n + 1) },
      { at: 2450, run: () => setFlicker((n) => n + 1) },
      { at: 2600, run: () => { tween(4.56, 9.87, 800); setFill(85); } },
      { at: 3400, run: () => { setFill(100); setBurst(true); } },
      { at: 3600, run: () => setZooming(true) },
      { at: 4100, run: () => { setFading(true); finish(); } },
      { at: 4500, run: () => setHidden(true) },
    ];

    beats.forEach((b) => timers.current.push(setTimeout(b.run, b.at)));

    const t = timers.current;
    return () => {
      t.forEach(clearTimeout);
      if (raf.current) cancelAnimationFrame(raf.current);
      document.body.classList.remove("no-scroll");
    };
  }, []);

  // Nobody should be held in a four-second animation. Any key or click skips it.
  useEffect(() => {
    if (hidden) return;
    const skip = () => {
      timers.current.forEach(clearTimeout);
      if (raf.current) cancelAnimationFrame(raf.current);
      setZooming(true);
      setFading(true);
      document.body.classList.remove("no-scroll");
      window.dispatchEvent(new Event("meter:intro-done"));
      setTimeout(() => setHidden(true), 400);
    };
    window.addEventListener("keydown", skip);
    window.addEventListener("pointerdown", skip);
    return () => {
      window.removeEventListener("keydown", skip);
      window.removeEventListener("pointerdown", skip);
    };
  }, [hidden]);

  if (hidden) return null;

  return (
    <div
      className={`intro-overlay${fading ? " fade-out" : ""}`}
      role="presentation"
      aria-hidden="true"
    >
      <div className="intro-bg" />
      <div className="intro-scene">
        <div
          className={`meter-device${active ? " active" : ""}${zooming ? " zoom-out" : ""}`}
        >
          {/* Keyed so each flash restarts the animation — otherwise the first one
              wins and the later two silently do nothing. */}
          <div key={`s${slot}`} className={`meter-slot${slot ? " flash" : ""}`} />
          <div
            key={`d${flicker}`}
            className={`meter-display${gold ? " gold-glow" : ""}${flicker ? " flicker" : ""}`}
          >
            <span>{value}</span>
          </div>
          <div className="meter-bar">
            <div className="meter-fill" style={{ width: `${fill}%` }} />
          </div>
          <div className={`meter-dots${lit ? " lit" : ""}`}>
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className="meter-label">METER</div>
        </div>

        <div className="coin coin-1">$</div>
        <div className="coin coin-2">$</div>
        <div className="coin coin-3">$</div>

        <div className={`burst-ring${burst ? " active" : ""}`} />
        <div className={`burst-ring r2${burst ? " active" : ""}`} />
      </div>
    </div>
  );
}
