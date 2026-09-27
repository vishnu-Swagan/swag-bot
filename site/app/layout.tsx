import type { Metadata, Viewport } from "next";
import { Fraunces, IBM_Plex_Mono, Outfit } from "next/font/google";
import { GITHUB_URL, VERSION } from "@/lib/content";
import { getSiteUrl } from "@/lib/site-url";
import "./globals.css";

const display = Fraunces({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  display: "swap",
  variable: "--font-fraunces",
});

const sans = Outfit({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
  variable: "--font-outfit",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
  variable: "--font-plex",
});

const description =
  "Free MIT-licensed Python agent. It plans a goal, does the steps, and checks the result. Local models with Ollama, or bring your own key.";

export const metadata: Metadata = {
  metadataBase: new URL(getSiteUrl()),
  title: {
    default: "Swag Bot — plans the work, does it, and checks it",
    template: "%s · Swag Bot",
  },
  description,
  applicationName: "Swag Bot",
  authors: [{ name: "Vishnu M", url: GITHUB_URL }],
  keywords: [
    "Swag Bot",
    "swag",
    "AI agent",
    "Ollama",
    "MCP",
    "Python",
    "open source",
  ],
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    url: "/",
    title: "Swag Bot — plans the work, does it, and checks it",
    description,
    siteName: "Swag Bot",
  },
  twitter: {
    card: "summary_large_image",
    title: "Swag Bot — plans the work, does it, and checks it",
    description,
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: "#110f0c",
  width: "device-width",
  initialScale: 1,
};

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareSourceCode",
  name: "Swag Bot",
  description,
  version: VERSION,
  license: "https://opensource.org/licenses/MIT",
  codeRepository: GITHUB_URL,
  programmingLanguage: "Python",
  runtimePlatform: "Python 3.11+",
  isAccessibleForFree: true,
  author: { "@type": "Person", name: "Vishnu M" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${sans.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <body>
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{if(!matchMedia('(prefers-reduced-motion: reduce)').matches){document.documentElement.classList.add('js-motion')}}catch(e){}",
          }}
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
        {children}
      </body>
    </html>
  );
}
