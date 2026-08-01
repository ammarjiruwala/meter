// Placeholder until Shivam's Treasurer/wallets table exists (ARCHITECTURE.md §4
// `wallets`, not started as of Phase 1 — see CONTEXT.md §6a). Swap this for a real
// query once that table lands.
export type ProviderBalance = {
  provider: string;
  balance_usd: number;
};

export function getProviderBalancesPlaceholder(): ProviderBalance[] {
  return [
    { provider: "openai", balance_usd: 0 },
    { provider: "anthropic", balance_usd: 0 },
  ];
}
