import { Home } from "@/components/marketing/Home";

/**
 * The marketing homepage at `/`.
 *
 * Unlike the dashboard this reads no database and is fully static.
 *
 * That was originally a workaround — the dashboard read `meter.db` off local disk, so it
 * could not deploy to Vercel and the homepage was kept free of the dependency. The ledger
 * is Postgres now and both halves deploy fine, so the constraint is gone. Staying static
 * is still worth keeping: the public page then has no reason to fail when the database is
 * paused, unreachable, or empty.
 */
export default function Page() {
  return <Home />;
}
