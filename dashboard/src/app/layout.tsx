import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Background } from "@/components/Background";
import "./globals.css";

// Inter across the whole product. Weights are explicit because the design gets its
// hierarchy from weight (600 headings against 400 body) rather than from size and
// tracking — Next only subsets what is asked for, and a missing 600 silently
// synthesises a faux-bold that ruins the type.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Meter",
  description:
    "The autonomous inference treasurer — budget, analyze, and transact.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} antialiased`}>
      <body className="min-h-screen bg-canvas">
        {/* Fixed layers live outside the content flow, mounted once so the orbs
            keep their drift position across navigation. */}
        <Background />
        {children}
      </body>
    </html>
  );
}
