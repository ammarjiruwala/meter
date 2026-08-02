import { cookies } from "next/headers";
import { query } from "@/lib/db";

/**
 * Resolving a judge's session on the *server*, so the Control Room can render their data.
 *
 * The judge view is not a second dashboard. It is the same page, the same components and
 * the same queries, with every read scoped to one project — so the token has to be
 * readable where those queries run, which is a server component. That rules out
 * `localStorage` and makes a cookie the only option.
 *
 * **Deliberately not `httpOnly`.** The console also calls the proxy directly from the
 * browser (`/judge/*` on another origin, where cookies are not sent), so the client needs
 * to read the same value. The token is a capability for a throwaway sandbox session with
 * a call cap and a four-hour life — the cost of it being script-readable is small, and
 * the alternative is storing it twice and keeping the copies in sync.
 */
export const SESSION_COOKIE = "meter_judge_session";

/** How long the cookie lives. Matches `judge.sessions.SESSION_TTL_S`. */
export const SESSION_MAX_AGE_S = 4 * 3600;

export type JudgeContext = {
  token: string;
  projectId: string;
  displayName: string | null;
  callsUsed: number;
  callCap: number;
  expiresAt: string;
};

/**
 * The live judge session for this request, or `null`.
 *
 * Read straight from `judge_sessions` rather than through the proxy's API: this file
 * already has a pooled connection to the same database, and going over HTTP would add a
 * round trip to a different host in front of every page render.
 *
 * Returns `null` for an expired session as well as an absent one. The distinction matters
 * to the *console*, which tells a judge their session timed out — but the page underneath
 * has nothing to render either way, and showing a stale project's numbers would be worse
 * than showing the team's.
 */
export async function judgeContext(): Promise<JudgeContext | null> {
  const store = await cookies();
  const token = store.get(SESSION_COOKIE)?.value;
  if (!token) return null;

  try {
    const rows = await query<{
      token: string;
      project_id: string;
      display_name: string | null;
      calls_used: number;
      call_cap: number;
      expires_at: string;
    }>(
      `SELECT token, project_id, display_name, calls_used, call_cap, expires_at
         FROM judge_sessions
        WHERE token = $1 AND expires_at > $2
        LIMIT 1`,
      [token, new Date().toISOString()],
    );
    const row = rows[0];
    if (!row) return null;
    return {
      token: row.token,
      projectId: row.project_id,
      displayName: row.display_name,
      callsUsed: Number(row.calls_used ?? 0),
      callCap: Number(row.call_cap ?? 0),
      expiresAt: row.expires_at,
    };
  } catch {
    // The table will not exist on a database whose proxy predates the judge work. A
    // missing table is "no session", not a broken dashboard.
    return null;
  }
}
