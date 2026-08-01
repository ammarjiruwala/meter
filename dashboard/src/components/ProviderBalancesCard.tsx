import type { WalletRow } from "@/lib/db";
import { usdColumnFormatter, providerLabel, relativeTime } from "@/lib/format";
import { SectionLabel, StatusBadge } from "@/components/ui/primitives";
import { Cell, DataTable, IdentityCell, Row } from "@/components/ui/DataTable";

/**
 * PLAN.md Phase 3 states the Treasurer's trigger as "if provider_balance < $10".
 * There is no config key for it yet because the loop itself is not built (Shivam),
 * so this is the documented figure rather than a live setting — when the loop lands
 * with a real threshold, this should read that instead of restating it.
 */
const LOW_BALANCE_USD = 10;

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

  const usd = usdColumnFormatter(wallets?.map((w) => w.balance_usd) ?? []);

  return (
    <section id="balances" className="scroll-mt-[100px]">
      <SectionLabel>Provider balances</SectionLabel>

      <DataTable
        columns={[
          { label: "Provider" },
          { label: "Balance", align: "right" },
          { label: "Status", align: "right" },
        ]}
        empty={
          wallets === null ? (
            <p className="t-cell text-ash">
              Treasury not initialised — start the proxy to create the wallets
              table.
            </p>
          ) : (
            <p className="t-cell text-ash">
              No wallets yet. Seed one with{" "}
              {/* No /treasury prefix — the router is mounted bare (see
                  proxy/README.md); the prefixed path 404s. */}
              <span className="text-paper">POST /wallets/seed</span>.
            </p>
          )
        }
        rows={(wallets ?? []).map((w) => {
          const low = w.balance_usd < LOW_BALANCE_USD;
          return (
            <Row key={w.id}>
              {/* Staleness rides under the provider name. A balance is only
                  meaningful with its age: "$4.00" is reassuring and "$4.00, three
                  hours ago" is alarming, and reacting to the second is the
                  Treasurer's entire job. */}
              <IdentityCell
                primary={providerLabel(w.provider)}
                secondary={
                  showProject
                    ? `${w.project_id} · updated ${relativeTime(w.updated_at)}`
                    : `Updated ${relativeTime(w.updated_at)}`
                }
              />
              <Cell align="right" numeric>
                {usd(w.balance_usd)}
              </Cell>
              <Cell align="right">
                <StatusBadge tone={low ? "throttled" : "good"}>
                  {low ? "Low" : "Funded"}
                </StatusBadge>
              </Cell>
            </Row>
          );
        })}
      />
    </section>
  );
}
