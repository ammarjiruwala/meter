import { Constellation } from "@/components/Constellation";

/**
 * The fixed background layers, bottom to top: the ambient network canvas, the 4px
 * dot texture, then a vignette. All are `position: fixed` and `pointer-events:
 * none`, so they never intercept a click meant for the content at z-index 10.
 *
 * The vignette is what makes the network usable as a background rather than a
 * distraction — it darkens toward the edges and corners, so the mesh is densest
 * where there is least content and recedes under the panels.
 */
export function Background() {
  return (
    <>
      <Constellation />
      <div className="bg-dots" aria-hidden="true" />
      <div className="bg-vignette" aria-hidden="true" />
    </>
  );
}
