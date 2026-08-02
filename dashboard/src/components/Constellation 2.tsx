"use client";

import { useEffect, useRef } from "react";

/**
 * The ambient network background: drifting nodes, links between near neighbours,
 * and pulses travelling along those links.
 *
 * It is a metaphor for what the product does — calls moving between services, each
 * one metered — which is why the pulses use the same mint/gold/signal the data
 * uses rather than an arbitrary palette.
 *
 * Three deliberate departures from the reference implementation, all of them
 * because this sits under live financial data rather than under a landing page:
 *
 * 1. **Dimmer.** The reference draws links at 0.15 alpha with 8px glow on every
 *    node. Behind a dense table that is not a background, it is a competitor —
 *    text on glass panels has to stay the brightest thing on screen.
 * 2. **Capped node count.** The reference scales nodes with viewport area and
 *    links every pair within range, which is O(n²) every frame. On a 4K display
 *    that is ~400 nodes and 80k distance checks per frame, forever, on a page
 *    that is already polling twice a second.
 * 3. **Device-pixel-ratio aware.** Sizing the canvas in CSS pixels leaves 1px
 *    lines visibly soft on any retina display.
 */

type Node = { x: number; y: number; vx: number; vy: number; color: string };
type Pulse = { from: number; to: number; progress: number; color: string };

// White, mint, gold — the node palette. Signal red is reserved for pulses, so a
// red dot on this canvas always means something moved.
const NODE_COLORS = ["255, 255, 255", "110, 220, 196", "232, 181, 123"];
const PULSE_COLORS = ["240, 104, 92", "110, 220, 196", "232, 181, 123"];

const LINK_DISTANCE = 190;
const MAX_NODES = 120;

export function Constellation() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let w = 0;
    let h = 0;
    let nodes: Node[] = [];
    const pulses: Pulse[] = [];

    function resize() {
      if (!canvas || !ctx) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      // Draw in CSS pixels; the transform handles the density.
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const count = Math.min(MAX_NODES, Math.floor((w * h) / 18000));
      nodes = Array.from({ length: count }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        // Slow. These should be noticeable only if you look for them.
        vx: (Math.random() - 0.5) * 0.16,
        vy: (Math.random() - 0.5) * 0.16,
        color: NODE_COLORS[Math.floor(Math.random() * NODE_COLORS.length)],
      }));
    }

    function drawFrame(animate: boolean) {
      if (!ctx) return;
      ctx.clearRect(0, 0, w, h);

      if (animate) {
        for (const n of nodes) {
          n.x += n.vx;
          n.y += n.vy;
          // Bounce rather than wrap: a node teleporting across the viewport drags
          // its links with it and reads as a glitch.
          if (n.x < 0 || n.x > w) n.vx *= -1;
          if (n.y < 0 || n.y > h) n.vy *= -1;
        }
      }

      // Links, faded by distance so the mesh dissolves at its edges.
      ctx.lineWidth = 1;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.hypot(dx, dy);
          if (dist >= LINK_DISTANCE) continue;
          ctx.strokeStyle = `rgba(255,255,255,${0.1 * (1 - dist / LINK_DISTANCE)})`;
          ctx.beginPath();
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.stroke();
        }
      }

      // A small glow on each node. This is the one place the reference's heavier
      // treatment is worth keeping — without it the nodes read as dust rather than
      // as points on a network. `shadowBlur` is reset immediately after, or every
      // subsequent fill on the context inherits it.
      for (const n of nodes) {
        ctx.shadowColor = `rgba(${n.color}, 0.5)`;
        ctx.shadowBlur = 6;
        ctx.fillStyle = `rgba(${n.color}, 0.7)`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, 1.7, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      if (!animate) return;

      // A new pulse every so often, only along a link that actually exists.
      if (Math.random() < 0.09 && nodes.length > 1) {
        const i = Math.floor(Math.random() * nodes.length);
        let j = Math.floor(Math.random() * nodes.length);
        while (i === j) j = Math.floor(Math.random() * nodes.length);
        if (Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y) < LINK_DISTANCE) {
          pulses.push({
            from: i,
            to: j,
            progress: 0,
            color: PULSE_COLORS[Math.floor(Math.random() * PULSE_COLORS.length)],
          });
        }
      }

      for (let i = pulses.length - 1; i >= 0; i--) {
        const p = pulses[i];
        p.progress += 0.016;
        if (p.progress >= 1) {
          pulses.splice(i, 1);
          continue;
        }
        const a = nodes[p.from];
        const b = nodes[p.to];
        // A resize rebuilds the node array, which can orphan an in-flight pulse.
        if (!a || !b) {
          pulses.splice(i, 1);
          continue;
        }

        const x = a.x + (b.x - a.x) * p.progress;
        const y = a.y + (b.y - a.y) * p.progress;
        const tail = Math.max(0, p.progress - 0.28);
        const tx = a.x + (b.x - a.x) * tail;
        const ty = a.y + (b.y - a.y) * tail;

        const grad = ctx.createLinearGradient(tx, ty, x, y);
        grad.addColorStop(0, `rgba(${p.color}, 0)`);
        grad.addColorStop(1, `rgba(${p.color}, 0.8)`);
        ctx.strokeStyle = grad;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(tx, ty);
        ctx.lineTo(x, y);
        ctx.stroke();

        ctx.shadowColor = `rgba(${p.color}, 0.9)`;
        ctx.shadowBlur = 10;
        ctx.fillStyle = `rgba(${p.color}, 0.95)`;
        ctx.beginPath();
        ctx.arc(x, y, 2.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
      }
    }

    resize();

    // Reduced motion gets the mesh, drawn once and left alone. The look survives;
    // only the movement goes.
    if (reduced) {
      drawFrame(false);
      const onResizeStatic = () => {
        resize();
        drawFrame(false);
      };
      window.addEventListener("resize", onResizeStatic);
      return () => window.removeEventListener("resize", onResizeStatic);
    }

    let raf = 0;
    const loop = () => {
      drawFrame(true);
      raf = requestAnimationFrame(loop);
    };
    loop();

    // Debounced: a drag-resize fires continuously, and each one reallocates every
    // node. Rebuilding the field 60 times a second while dragging is what makes a
    // canvas background feel like it is fighting the browser.
    let resizeTimer: ReturnType<typeof setTimeout>;
    const onResize = () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(resize, 150);
    };
    window.addEventListener("resize", onResize);

    // A background animation must not run while nobody is looking at it — a
    // backgrounded tab would otherwise keep a core warm indefinitely.
    const onVisibility = () => {
      if (document.hidden) {
        cancelAnimationFrame(raf);
      } else {
        cancelAnimationFrame(raf);
        loop();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(resizeTimer);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return <canvas ref={ref} className="bg-network" aria-hidden="true" />;
}
