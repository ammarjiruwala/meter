// Shown automatically by the App Router as the Suspense fallback while the
// dashboard's ~5s worth of ledger queries run on navigation from home. Next
// swaps it for the page the moment the server component resolves — no client
// state, no wiring on the Link. Just an indeterminate bar so the click isn't
// a dead 5 seconds. ponytail: native loading.tsx; nothing else needed.
export default function Loading() {
  return (
    <div className="route-loading" role="status" aria-live="polite">
      <div className="route-loading__bar" />
      <span className="route-loading__label">Loading dashboard…</span>
    </div>
  );
}
