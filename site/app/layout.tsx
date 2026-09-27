import { CommandPalette } from "@/components/shell/command-palette";
import { Footer } from "@/components/shell/footer";
import { Nav } from "@/components/shell/nav";
import { ScrollProgress } from "@/components/shell/scroll-progress";
import { DESCRIPTION, GITHUB_URL, GITHUB_USER_URL, PRODUCT } from "@/lib/site";
import { getSiteUrl } from "@/lib/site-url";
import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

const sans = Geist({
  subsets: ["latin"],
  display: "optional",
  variable: "--font-geist",
});

const mono = Geist_Mono({
  subsets: ["latin"],
  display: "optional",
  preload: false,
  variable: "--font-geist-mono",
});

const siteUrl = getSiteUrl();

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "Swag Bot — done only when the evidence agrees",
    template: "%s · Swag Bot",
  },
  description: DESCRIPTION,
  applicationName: "Swag Bot",
  authors: [{ name: PRODUCT.author, url: GITHUB_USER_URL }],
  keywords: ["Swag Bot", "swag", "AI agent", "Ollama", "MCP", "open source", "MIT"],
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    url: "/",
    title: "Swag Bot — done only when the evidence agrees",
    description: DESCRIPTION,
    siteName: "Swag Bot",
    images: [{ url: "/og?title=Done%20only%20when%20the%20evidence%20agrees", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Swag Bot — done only when the evidence agrees",
    description: DESCRIPTION,
    images: ["/og?title=Done%20only%20when%20the%20evidence%20agrees"],
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: "#09090b",
  width: "device-width",
  initialScale: 1,
};

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "Swag Bot",
  applicationCategory: "DeveloperApplication",
  operatingSystem: "macOS, Windows, Linux",
  softwareVersion: PRODUCT.versionLabel,
  offers: { "@type": "Offer", "price": "0", "priceCurrency": "USD" },
  isAccessibleForFree: true,
  license: "https://opensource.org/licenses/MIT",
  codeRepository: GITHUB_URL,
  url: siteUrl,
  description: DESCRIPTION,
  author: { "@type": "Person", name: PRODUCT.author, url: GITHUB_USER_URL },
};

const themeBoot = `
try {
  var stored = localStorage.getItem("theme");
  var theme = stored === "light" || stored === "dark" ? stored : "dark";
  var root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "light" ? "#f5f5f2" : "#09090b");
} catch (e) {}
`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeBoot }} />
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <ScrollProgress />
        <Nav />
        <CommandPalette />
        <main id="main">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
