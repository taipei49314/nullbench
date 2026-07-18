export default function ArenaRadar({ pulse }) {
  return (
    <div className={`arena-radar ${pulse ? "is-live" : ""}`} aria-hidden="true">
      <svg viewBox="0 0 500 500">
        <circle cx="250" cy="250" r="196" />
        <circle cx="250" cy="250" r="148" />
        <circle cx="250" cy="250" r="100" />
        <circle cx="250" cy="250" r="52" />
        <line x1="250" y1="36" x2="250" y2="464" />
        <line x1="36" y1="250" x2="464" y2="250" />
        <line x1="99" y1="99" x2="401" y2="401" />
        <line x1="401" y1="99" x2="99" y2="401" />
        <path className="radar-sweep" d="M250 250 L250 54 A196 196 0 0 1 414 142 Z" />
        <circle className="radar-point point-a" cx="335" cy="112" r="4" />
        <circle className="radar-point point-b" cx="131" cy="294" r="3" />
        <circle className="radar-point point-c" cx="303" cy="366" r="4" />
      </svg>
    </div>
  );
}
