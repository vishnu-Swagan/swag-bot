import fs from "node:fs";
import path from "node:path";

const videoPath = path.join(process.cwd(), "public", "demo", "demo.mp4");
const hasVideo = fs.existsSync(videoPath);

export function DemoSlot() {
  return (
    <section id="demo" className="border-t border-line">
      <div className="mx-auto w-full max-w-6xl px-4 py-20 md:px-6">
        <p className="kicker">Demo</p>
        <h2 className="h-display mt-3 text-4xl sm:text-5xl">Watch a run.</h2>
        <p className="mt-4 max-w-2xl text-muted">
          Drop the recording at <span className="font-mono">site/public/demo/demo.mp4</span>. The poster stays in place until that file is part of the build.
        </p>
        <div className="panel mt-8 overflow-hidden">
          {hasVideo ? (
            <video className="aspect-video w-full bg-black" controls preload="metadata" poster="/demo/poster.svg">
              <source src="/demo/demo.mp4" type="video/mp4" />
            </video>
          ) : (
            <div className="relative">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/demo/poster.svg"
                alt="Poster for the Swag Bot demo. The video file is not published yet."
                className="aspect-video w-full object-cover"
              />
              <p className="absolute inset-x-0 bottom-0 bg-black/75 px-4 py-3 text-sm text-white">
                Recording not published yet.
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
