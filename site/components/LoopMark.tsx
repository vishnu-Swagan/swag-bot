export function LoopMark() {
  return (
    <svg viewBox="0 0 320 300" className="h-full w-full" aria-hidden="true">
      <path
        d="M160 48 L68 214 L252 214 Z"
        fill="none"
        stroke="rgba(246,241,232,0.28)"
        strokeWidth="1.5"
      />
      <path
        className="loop-path"
        d="M160 48 L68 214 L252 214 Z"
        fill="none"
        stroke="#e2ff57"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <circle cx="160" cy="150" r="34" fill="none" stroke="rgba(226,255,87,0.35)" strokeWidth="1.5" />
      <circle cx="160" cy="150" r="16" fill="#e2ff57" />
      <circle cx="160" cy="48" r="18" fill="#d7c6ff" />
      <circle cx="68" cy="214" r="18" fill="#ff8a5c" />
      <circle cx="252" cy="214" r="18" fill="#8ef0d2" />
      <circle cx="160" cy="48" r="5" fill="#110f0c" />
      <circle cx="68" cy="214" r="5" fill="#110f0c" />
      <circle cx="252" cy="214" r="5" fill="#110f0c" />
    </svg>
  );
}
