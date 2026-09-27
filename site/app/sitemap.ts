import type { MetadataRoute } from "next";
import { getSiteUrl } from "@/lib/site-url";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: getSiteUrl(),
      lastModified: "2026-09-27",
      changeFrequency: "monthly",
      priority: 1,
    },
  ];
}
