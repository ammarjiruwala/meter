import type { BudgetScope } from "@/lib/db";
import { usdCeilingFormatter, usdColumnFormatter } from "@/lib/format";

// Utilization bands. A display convention, not a second enforcement rule — the
// proxy refuses at the ceiling and nowhere else. These exist so someone glancing at
// the page sees a feature approaching its limit before it starts returning 429s.
type Band = {
  badge: string;
  fill: string;
  pulse: string;
};

function bandFor(used: number): Band {
  if (used >= 0.9)
    return {
      badge: "badge badge-bad badge-pulse-bad",
      fill: "fill-danger",
      pulse: "bad",
    };
  if (used >= 0.7)
    return {
      badge: "badge badge-warn badge-pulse-warn",
      fill: "fill-warn",
      pulse: "warn",
    };
  return { badge: "badge badge-good", fill: "fill-safe", pulse: "none" };
}

// Colour is assigned by position, not by status — status is already carried by the
// badge and the progress fill, and tinting the whole card by health would drown
// those out and make a healthy page look like a christmas tree.
const VARIANTS = ["card-blue", "card-purple", "card-teal", "card-indigo", "card-rose"];

// Stable per-initial colours, so the same person keeps the same swatch across cards.
const AVATAR_COLORS = [
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#f59e0b",
  "#10b981",
  "#6366f1",
];

function avatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function initials(name: string): string {
  const parts = name.split(/[\s._-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).replace(/^./, (c) => c.toUpperCase());
}

type Formatters = {
  spend: (n: number | null | undefined) => string;
  ceiling: (n: number | null | undefined) => string;
};

function BudgetCard({
  scope,
  variant,
  usd,
  delay,
}: {
  scope: BudgetScope;
  variant: string;
  usd: Formatters;
  delay: string;
}) {
  const isProject = scope.feature === null;
  // A zero ceiling would divide to Infinity. meter.yaml rejects non-positive
  // ceilings at load, but the card should not be what breaks if that changes.
  const used = scope.ceiling_usd > 0 ? scope.spend_usd / scope.ceiling_usd : 0;
  const band = bandFor(used);
  const headroom = Math.max(0, scope.ceiling_usd - scope.spend_usd);
  const shown = scope.members.slice(0, 4);
  const extra = scope.members.length - shown.length;

  return (
    <div className={`budget-card animate-in ${variant} ${delay}`}>
      <div className="relative z-[1] mb-[14px] flex items-start justify-between gap-[12px]">
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold tracking-[-0.02em] text-white">
            {isProject ? scope.project_id : scope.feature}
          </div>
          {/* Alpha levels on these cards are set by contrast, not taste: over the
              five card gradients, white at 35% measures 3.1:1 and at 45% about
              4.2:1 — both under the floor. 60% clears 6.2:1 on every variant and
              still reads a clear step under the white title. */}
          <div className="truncate text-[12px] text-white/60">
            {isProject ? "Project ceiling" : scope.project_id}
          </div>
        </div>
        <span className={band.badge}>{(used * 100).toFixed(0)}%</span>
      </div>

      <div className="relative z-[1] mb-[14px]">
        <div className="progress-track mb-[8px]">
          {/* Bar length caps at the ceiling; the badge percentage does not, so an
              overspend still reads as the number it is. */}
          <div
            className={`progress-fill ${band.fill}`}
            style={{ width: `${Math.min(100, used * 100)}%` }}
          />
        </div>
        <div className="t-num flex justify-between text-[12px] text-white/60">
          <span>
            {usd.spend(scope.spend_usd)} of {usd.ceiling(scope.ceiling_usd)}
          </span>
          <span className="font-semibold text-white/75">Rolling 24h</span>
        </div>
      </div>

      <div className="relative z-[1] flex items-center justify-between gap-[12px]">
        <div className="flex items-center gap-[4px] text-[11px] text-white/55">
          <span
            className="t-num"
            style={
              band.pulse === "none"
                ? undefined
                : { color: `var(--color-status-${band.pulse === "bad" ? "bad" : "warn"})` }
            }
          >
            {band.pulse !== "none" && "⚠ "}
            {usd.spend(headroom)} headroom
          </span>
          {scope.members.length > 0 && (
            <>
              <span className="h-[4px] w-[4px] rounded-full bg-white/25" />
              <span>
                {scope.members.length} member
                {scope.members.length === 1 ? "" : "s"}
              </span>
            </>
          )}
        </div>

        {/* Real attribution: these are the actors who spent against this scope,
            ordered by how much they spent. */}
        <div className="flex items-center">
          {shown.map((m) => (
            <span
              key={m}
              className="avatar"
              style={{ background: avatarColor(m) }}
              title={m}
            >
              {initials(m)}
            </span>
          ))}
          {extra > 0 && (
            <span
              className="avatar text-white/70"
              style={{ background: "rgba(255,255,255,0.08)" }}
              title={scope.members.slice(4).join(", ")}
            >
              +{extra}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export function TeamBudgetCard({ scopes }: { scopes: BudgetScope[] | null }) {
  // Null means no ceilings anywhere — no meter.yaml, a normal deployment. Rendering
  // that as "$0.00 of $0.00" would read as catastrophically over budget when it
  // means the opposite.
  if (scopes === null || scopes.length === 0) {
    return (
      <div
        id="budget"
        className="glass animate-in delay-2 flex min-h-[175px] items-center p-[24px]"
      >
        <p className="t-body text-text-secondary">
          {scopes === null ? (
            <>
              No ceilings configured. Copy{" "}
              <span className="text-text-primary">meter.yaml.example</span> to{" "}
              <span className="text-text-primary">meter.yaml</span> at the repo
              root and restart the proxy.
            </>
          ) : (
            "Ceilings are configured, but no requests have been logged yet."
          )}
        </p>
      </div>
    );
  }

  // Two formatters. Spend and headroom share an axis of comparison; ceilings are
  // round numbers a human typed into meter.yaml, and folding them in with sub-cent
  // spend would render a $0.50 cap as "$0.500000".
  const usd: Formatters = {
    spend: usdColumnFormatter([
      ...scopes.map((s) => s.spend_usd),
      ...scopes.map((s) => s.ceiling_usd - s.spend_usd),
    ]),
    ceiling: usdCeilingFormatter(scopes.map((s) => s.ceiling_usd)),
  };

  return (
    // Scopes stay in meter.yaml order and are never re-sorted, including by how
    // close to the ceiling they are — cards must not reshuffle under someone
    // watching them during a live demo.
    <div
      id="budget"
      className="grid grid-cols-1 gap-[14px] sm:grid-cols-2"
    >
      {scopes.map((scope, i) => (
        <BudgetCard
          key={`${scope.project_id}:${scope.feature ?? "*"}`}
          scope={scope}
          variant={VARIANTS[i % VARIANTS.length]}
          usd={usd}
          delay={`delay-${Math.min(6, i + 2)}`}
        />
      ))}
    </div>
  );
}
