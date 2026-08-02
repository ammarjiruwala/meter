import { Home } from "@/components/marketing/Home";

/**
 * The marketing homepage at `/`.
 *
 * Unlike the dashboard this reads no database and is fully static — which is the
 * point: `DEPLOY.md` records that the dashboard cannot deploy to Vercel while it
 * reads `meter.db` off local disk, and keeping the homepage free of that dependency
 * means the public-facing page is not held hostage by the ledger migration.
 */
export default function Page() {
  return <Home />;
}
