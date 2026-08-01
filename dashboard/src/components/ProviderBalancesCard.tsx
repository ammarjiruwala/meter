import type { WalletRow } from "@/lib/db";
import { formatUsd, providerLabel, relativeTime } from "@/lib/format";
import { Card, SectionLabel } from "@/components/ui/primitives";

export function ProviderBalancesCard({
  wallets,
}: {
  // null means the treasury tables do not exist yet — a different situation from
  // "they exist and are empty", and the card says so rather than implying $0.
  wallets: WalletRow[] | null;
}) {
  // Balances are per (project, provider). With a single project the project name
  // is noise, so it only appears once there is more than one to tell apart.
  const showProject =
    wallets !== null && new Set(wallets.map((w) => w.project_id)).size > 1;

  return (
    <section id="balances" className="scroll-mt-[100px]">
      <SectionLabel>Provider balances</SectionLabel>

      {wallets === null ? (
        <Card className="p-[24px]">
          <p className="t-body text-ash">
            Treasury not initialised — start the proxy to create the wallets
            table.
          </p>
        </Card>
      ) : wallets.length === 0 ? (
        <Card className="p-[24px]">
          <p className="t-body text-ash">
            No wallets yet. Seed one with{" "}
            {/* No /treasury prefix — the router is mounted bare (see proxy/README.md);
                the prefixed path 404s. */}
            <span className="t-readout text-paper">POST /wallets/seed</span>.
          </p>
        </Card>
      ) : (
        <div className="grid gap-[20px] sm:grid-cols-2">
          {wallets.map((w) => (
            <Card key={w.id} className="p-[24px]">
              <div className="flex items-baseline justify-between gap-[16px]">
                <span className="t-heading-sm text-paper">
                  {providerLabel(w.provider)}
                </span>
                <span className="t-readout-sm text-ash">
                  {relativeTime(w.updated_at)}
                </span>
              </div>
              <p className="t-heading-lg mt-[20px] tabular-nums text-paper">
                {formatUsd(w.balance_usd)}
              </p>
              {showProject && (
                <p className="t-readout-sm mt-[12px] text-ash">{w.project_id}</p>
              )}
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}
