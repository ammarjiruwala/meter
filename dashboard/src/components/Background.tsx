/**
 * The three fixed background layers, bottom to top: the 4px dot texture, a pair of
 * soft corner blooms, then a vignette. All of them are `position: fixed` and
 * `pointer-events: none`, so they never intercept a click meant for the content
 * sitting at z-index 10.
 *
 * This replaced four drifting, blurred orbs. Two reasons: the orbs were violet and
 * cyan, which belonged to the old accent and would now fight the mint/gold/signal
 * ramp the data uses — and they were in constant motion. A dashboard whose
 * background moves while the numbers do not is telling the viewer the wrong thing
 * about what is live. This layer is completely still; only the data animates.
 */
export function Background() {
  return (
    <>
      <div className="bg-dots" aria-hidden="true" />
      <div className="bg-bloom" aria-hidden="true" />
      <div className="bg-vignette" aria-hidden="true" />
    </>
  );
}
