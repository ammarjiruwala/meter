import type { Metadata } from "next";
import { Inter, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// Substitutes for the brief's custom faces: Inter for Diatype REKKI (geometric
// sans, holds up under aggressive negative tracking at display sizes), IBM Plex
// Mono for OCD-GARRI (the instrument-label register).
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400"],
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
    <html
      lang="en"
      className={`${inter.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-obsidian">{children}</body>
    </html>
  );
}
