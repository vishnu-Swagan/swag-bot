import type { Block } from "@/lib/docs";
import Link from "next/link";

export function DocBody({ blocks }: { blocks: readonly Block[] }) {
  return (
    <div className="mx-auto grid w-full max-w-3xl gap-4 px-4 pb-20 md:px-6">
      {blocks.map((block, index) => {
        if (block.type === "h") {
          return (
            <h2 key={index} className="mt-6 text-2xl font-semibold tracking-tight">
              {block.text}
            </h2>
          );
        }
        if (block.type === "p") return <p key={index}>{block.text}</p>;
        if (block.type === "ul") {
          return (
            <ul key={index} className="grid list-disc gap-2 pl-5 text-muted">
              {block.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          );
        }
        if (block.type === "code") {
          return (
            <pre key={index} className="overflow-x-auto rounded-2xl border border-line bg-elev p-4 font-mono text-sm leading-6">
              <code>{block.text}</code>
            </pre>
          );
        }
        if (block.type === "note") {
          return (
            <p key={index} className="rounded-2xl border border-line bg-elev px-4 py-3 text-sm text-muted">
              {block.text}
            </p>
          );
        }
        const className = "link font-medium";
        return block.href.startsWith("/") ? (
          <Link key={index} href={block.href} className={className}>
            {block.label}
          </Link>
        ) : (
          <a key={index} href={block.href} className={className}>
            {block.label}
          </a>
        );
      })}
    </div>
  );
}
