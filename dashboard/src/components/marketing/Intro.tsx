"use client";

import { useEffect, useRef, useState } from "react";

/** Where the counter lands after each coin. The last figure is deliberately the
 *  same one the overview's live badge shows, so the intro is counting up to the
 *  number the page then claims. */
const STEPS = ["$12.40", "$310.06", "$847.31"];

/**
 * Timing, derived from the coin animations rather than guessed: each coin starts at
 * 0.7s / 1.5s / 2.3s and runs 1.15s, so it reaches the slot at ~1.85s / 2.65s /
 * 3.45s. The meter reacts on arrival, not on launch.
 */
const ARRIVALS = [1850, 2650, 3450];
const FINISH = 4250;

export function Intro() {
  const [gone, setGone] = useState(false);
  const [fading, setFading] = useState(false);
  const [zooming, setZooming] = useState(false);
  const [value, setValue] = useState("$0.00");
  const [fill, setFill] = useState(0);
  const [lit, setLit] = useState(false);
  const [active, setActive] = useState(false);
  const [flash, setFlash] = useState(0);
  const [burst, setBurst] = useState(0);

  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    const at = (ms: number, fn: () => void) => {
      timers.current.push(setTimeout(fn, ms));
    };

    // Anyone who asked their OS to stop motion gets no sequence at all. The CSS
    // hides the overlay for them, but the page is also locked behind `no-scroll`
    // until this finishes — so without this branch they would be left staring at a
    // frozen page. Release immediately instead.
    const still =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (still) {
      // Only side effects here, no state: the media query in marketing.css already
      // sets `display: none` on the overlay, so it is invisible and untouchable
      // whether or not this component unmounts. All that is actually required is
      // releasing the scroll lock and telling the hero to appear.
      document.body.classList.remove("no-scroll");
      window.dispatchEvent(new Event("meter:intro-done"));
      return;
    }

    ARRIVALS.forEach((ms, i) => {
      at(ms, () => {
        setValue(STEPS[i]);
        setFill(((i + 1) / ARRIVALS.length) * 100);
        setFlash((n) => n + 1);
        setBurst((n) => n + 1);
        if (i === ARRIVALS.length - 1) {
          setLit(true);
          setActive(true);
        }
      });
    });

    at(FINISH, () => {
      setZooming(true);
      setFading(true);
      document.body.classList.remove("no-scroll");
      // The hero listens for this to run its letter-by-letter entrance, so the two
      // halves of the handoff cannot drift apart if either duration is retuned.
      window.dispatchEvent(new Event("meter:intro-done"));
    });

    // The overlay keeps its own fade (0.9s) after the zoom starts; only then is it
    // safe to unmount, or the fade would be cut off mid-transition.
    at(FINISH + 950, () => setGone(true));

    const t = timers.current;
    return () => {
      t.forEach(clearTimeout);
      document.body.classList.remove("no-scroll");
    };
  }, []);

  // Nobody should be trapped in a 4-second animation. Click or any key skips it.
  useEffect(() => {
    if (gone) return;
    const skip = () => {
      timers.current.forEach(clearTimeout);
      setZooming(true);
      setFading(true);
      document.body.classList.remove("no-scroll");
      window.dispatchEvent(new Event("meter:intro-done"));
      setTimeout(() => setGone(true), 500);
    };
    window.addEventListener("keydown", skip);
    window.addEventListener("pointerdown", skip);
    return () => {
      window.removeEventListener("keydown", skip);
      window.removeEventListener("pointerdown", skip);
    };
  }, [gone]);

  if (gone) return null;

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
          <div key={`slot-${flash}`} className={flash ? "meter-slot flash" : "meter-slot"} />
          <div
            key={`disp-${flash}`}
            className={`meter-display${active ? " gold-glow" : ""}${flash ? " flicker" : ""}`}
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

        {/* Keyed so each arrival restarts the expand animation rather than the
            first one winning and the rest silently doing nothing. */}
        <div key={`b1-${burst}`} className={burst ? "burst-ring active" : "burst-ring"} />
        <div key={`b2-${burst}`} className={burst ? "burst-ring r2 active" : "burst-ring r2"} />
      </div>
    </div>
  );
}
