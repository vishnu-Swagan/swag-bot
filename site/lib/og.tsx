import { ImageResponse } from "next/og";

export const ogSize = { width: 1200, height: 630 };
export const ogContentType = "image/png";

export function renderOg(title: string, eyebrow = "Swag Bot") {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#09090b",
          color: "#fafafa",
          padding: "72px",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 12,
              background: "#d6ff4a",
              color: "#14160a",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 26,
              fontWeight: 700,
            }}
          >
            S
          </div>
          <div style={{ display: "flex", fontSize: 28, letterSpacing: -0.4 }}>{eyebrow}</div>
        </div>
        <div
          style={{
            display: "flex",
            fontSize: title.length > 42 ? 64 : 76,
            fontWeight: 600,
            letterSpacing: -2,
            lineHeight: 1.05,
            maxWidth: 980,
          }}
        >
          {title}
        </div>
        <div style={{ display: "flex", fontSize: 24, color: "#a1a1aa" }}>
          Free MIT agent. A step is done only when the evidence agrees.
        </div>
      </div>
    ),
    { ...ogSize },
  );
}
