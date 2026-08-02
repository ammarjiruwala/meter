import type { Metadata } from "next";
import {
  IBM_Plex_Sans,
  IBM_Plex_Mono,
  IBM_Plex_Sans_Condensed,
} from "next/font/google";
import "./marketing.css";

// Self-hosted through next/font rather than the design's <link> to Google Fonts:
// the link version blocks first paint on a third-party round trip, and this page
// opens with a timed animation where a late font swap is very visible.
const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const plexCond = IBM_Plex_Sans_Condensed({
  variable: "--font-plex-cond",
  subsets: ["latin"],
  weight: ["600", "700"],
});

export const metadata: Metadata = {
  title: "Meter — AI infrastructure that pays its own bills",
  description:
    "Meter sits in the request path, meters every AI call your company makes, "
    + "enforces budgets, and tops up provider credit before production fails.",
};

/**
 * Root layout for the marketing surface — its own <html>/<body>, its own fonts,
 * its own stylesheet. The dashboard has a separate root layout and shares nothing
 * with this one, which is what lets the homepage be expressive without any of it
 * reaching an operations screen someone watches while production is live.
 */
export default function MarketingRootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable} ${plexCond.variable}`}
    >
      {/* `no-scroll` is removed by the intro once it finishes; without it the page
          can be scrolled behind the overlay before the sequence has played. */}
      <body className="no-scroll">{children}</body>
    </html>
  );
}
