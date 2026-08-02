import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Background } from "@/components/Background";
import "../globals.css";

// Inter across the dashboard. Weights are explicit because the design gets its
// hierarchy from weight (600 headings against 400 body) rather than from size and
// tracking — Next only subsets what is asked for, and a missing 600 silently
// synthesises a faux-bold that ruins the type.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Meter — Dashboard",
  description:
    "The autonomous inference treasurer — budget, analyze, and transact.",
};

/**
 * Root layout for the dashboard half of the product.
 *
 * A *root* layout (it renders <html>/<body>), not a nested one — the marketing side
 * has its own. Two root layouts is what keeps the halves from sharing a font stack
 * or a token set: the homepage is deliberately expressive, the dashboard
 * deliberately plain, and they never have to agree on anything.
 *
 * The documented cost is that moving between them is a full page load rather than a
 * client transition. That is acceptable, and arguably right: going from a marketing
 * page into live financial data is a hard context switch, and the reload guarantees
 * no stylesheet from one side leaks into the other.
 */
export default function DashboardRootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} antialiased`}>
      <body className="min-h-screen bg-canvas">
        {/* The drifting mesh background belongs to the dashboard alone — mounted
            here rather than app-wide, so the marketing side never inherits it. */}
        <Background />
        {children}
      </body>
    </html>
  );
}
