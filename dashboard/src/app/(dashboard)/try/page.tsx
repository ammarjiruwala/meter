import type { Metadata } from "next";
import { JudgeConsole } from "@/components/judge/JudgeConsole";

export const metadata: Metadata = {
  title: "Meter — Try it yourself",
  description:
    "Run Meter on your own session: predicted cost before every call, a runaway feature throttled, and an agent that pays its own bill.",
};

/**
 * The judge console.
 *
 * A thin server shell around a client component, because everything here is interactive
 * and stateful — there is no server-rendered view of a session that does not exist yet.
 * It deliberately does NOT read the ledger the way `/dashboard` does: the console talks to
 * the proxy over `/judge/*`, where the session token, the Meter key and the judge's own
 * credentials are handled server-side and never reach this origin.
 */
export default function TryPage() {
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-5 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="t-page-title">Try it yourself</h1>
        <p className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
          Your own private session, your own card, about ten minutes. Nothing to install.
        </p>
      </header>
      <JudgeConsole />
    </main>
  );
}
