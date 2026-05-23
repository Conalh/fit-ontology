import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

/**
 * Inter + JetBrains Mono match the design's --font-sans / --font-mono
 * tokens declared in globals.css. We load via next/font (no external
 * <link>) and bind the CSS variables so var(--font-sans) resolves to
 * Inter throughout every component.
 */
const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans-inter",
});
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono-jetbrains",
});

export const metadata: Metadata = {
  title: "FitOntology",
  description:
    "Client intelligence for personal trainers — wearables, intake, and ACSM guidelines unified.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      data-theme="dark"
      className={`${inter.variable} ${jetbrainsMono.variable} h-full antialiased`}
      style={
        {
          "--font-sans": `var(--font-sans-inter), -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`,
          "--font-mono": `var(--font-mono-jetbrains), ui-monospace, SFMono-Regular, Menlo, monospace`,
        } as React.CSSProperties
      }
    >
      <body className="min-h-full" style={{ background: "var(--surface)", color: "var(--text)" }}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
