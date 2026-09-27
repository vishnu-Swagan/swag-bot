import { ImageResponse } from "next/og";

export const alt = "Swag Bot — plans the work, does it, and checks it";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#110f0c",
          color: "#f6f1e8",
          padding: "72px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 28 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{ width: 18, height: 18, borderRadius: 99, background: "#d7c6ff" }} />
            <div style={{ width: 18, height: 18, borderRadius: 99, background: "#ff8a5c" }} />
            <div style={{ width: 18, height: 18, borderRadius: 99, background: "#8ef0d2" }} />
          </div>
          <div>Swag Bot · v0.1.0 · MIT</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", fontSize: 84, lineHeight: 1, letterSpacing: -2 }}>
          <div style={{ color: "#d7c6ff" }}>Plans the work.</div>
          <div style={{ color: "#ff8a5c" }}>Does it.</div>
          <div style={{ color: "#8ef0d2" }}>Checks it.</div>
        </div>
        <div style={{ display: "flex", fontSize: 28, color: "#d5cbbf" }}>
          A free, open-source Python agent. The command is swag.
        </div>
      </div>
    ),
    { ...size },
  );
}
