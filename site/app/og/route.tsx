import { renderOg } from "@/lib/og";

export function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const title = (searchParams.get("title") || "Swag Bot").replace(/\s+/g, " ").trim().slice(0, 90);
  const eyebrow = (searchParams.get("eyebrow") || "Swag Bot").replace(/\s+/g, " ").trim().slice(0, 40);
  return renderOg(title || "Swag Bot", eyebrow || "Swag Bot");
}
