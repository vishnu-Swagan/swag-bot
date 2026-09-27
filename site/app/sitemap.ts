import type { MetadataRoute } from "next";
import { DOCS } from "@/lib/docs";
import { FEATURES } from "@/lib/site";
import { getSiteUrl } from "@/lib/site-url";

export default function sitemap(): MetadataRoute.Sitemap {
  const origin = getSiteUrl();
  const paths = [
    "/",
    "/features",
    "/docs",
    "/plugins",
    "/changelog",
    "/security",
    "/community",
    "/brand",
    "/legal/terms",
    "/legal/privacy",
    "/legal/disclaimer",
    "/legal/license",
    "/legal/acceptable-use",
    ...FEATURES.map((feature) => `/features/${feature.slug}`),
    ...DOCS.map((doc) => `/docs/${doc.slug}`),
  ];
  return paths.map((path) => ({
    url: `${origin}${path}`,
    lastModified: "2026-09-27",
    changeFrequency: path === "/" ? "weekly" : "monthly",
    priority: path === "/" ? 1 : 0.7,
  }));
}
