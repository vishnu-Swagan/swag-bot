import type { Metadata } from "next";

export function pageMeta(title: string, description: string, path: string, absolute = false): Metadata {
  const image = `/og?title=${encodeURIComponent(title)}`;
  return {
    title: absolute ? { absolute: title } : title,
    description,
    alternates: { canonical: path },
    openGraph: {
      title,
      description,
      url: path,
      siteName: "Swag Bot",
      type: "website",
      images: [{ url: image, width: 1200, height: 630, alt: title }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [image],
    },
  };
}
