"use client";

/**
 * The two controls that move a judge between the team's dashboard and their own.
 *
 * They live beside the page title rather than in the nav, because a pill among six other
 * pills is the definition of hidden — and the entry point is the one thing a judge
 * arriving with no context has to find.
 */

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { judge, rememberToken } from "@/lib/judge";

/** On `/dashboard`: the way in. Deliberately the loudest thing on the header row. */
export function TryItYourself() {
  return (
    <Link href="/try" className="judge-cta">
      <span className="judge-cta-dot" aria-hidden />
      Try it yourself
    </Link>
  );
}

/**
 * On `/try`: the way out.
 *
 * Ends the session properly rather than just navigating away — the credentials a judge
 * pasted are dropped from the proxy's memory immediately instead of waiting out their
 * TTL, which is what the setup screen promised. The session row survives as the record of
 * what was run; only the secrets go.
 */
export function EndSession({ token }: { token: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function end() {
    setBusy(true);
    try {
      await judge.endSession(token);
    } catch {
      // Clearing the cookie is the part that must happen. If the proxy is unreachable the
      // credentials expire on their own, and stranding someone on a session they asked to
      // leave would be the worse failure.
    }
    rememberToken(null);
    router.push("/dashboard");
    router.refresh();
  }

  return (
    <div className="flex flex-col items-center gap-[10px] py-[8px] text-center">
      <button className="judge-btn-quiet" disabled={busy} onClick={() => void end()}>
        {busy ? "Ending your session…" : "End session and return to the team dashboard"}
      </button>
      <p className="text-[12px]" style={{ color: "var(--color-text-tertiary)" }}>
        Your keys are dropped from memory straight away. The calls you made stay in the
        ledger and in the public feed.
      </p>
    </div>
  );
}
