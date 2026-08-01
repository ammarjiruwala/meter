/**
 * The four fixed background layers, bottom to top: drifting mesh orbs, a masked
 * line grid, noise grain, then a vignette. All of them are `position: fixed` and
 * `pointer-events: none`, so they never intercept a click meant for the content
 * sitting at z-index 10.
 *
 * Rendered once in the root layout rather than per page — they must not remount
 * on navigation, or the orbs would jump back to the start of their drift.
 */
export function Background() {
  return (
    <>
      <div className="bg-mesh" aria-hidden="true">
        <div className="orb orb-1" />
        <div className="orb orb-2" />
        <div className="orb orb-3" />
        <div className="orb orb-4" />
      </div>
      <div className="bg-grid" aria-hidden="true" />
      <div className="bg-noise" aria-hidden="true" />
      <div className="bg-vignette" aria-hidden="true" />
    </>
  );
}
