import type { ReactNode } from "react";

type OutboundProps = {
  href: string;
  className?: string;
  children: ReactNode;
};

export function Outbound({ href, className, children }: OutboundProps) {
  return (
    <a className={className} href={href} target="_blank" rel="noopener noreferrer">
      {children}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}
