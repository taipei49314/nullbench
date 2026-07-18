export default function SignalChart({ series }) {
  const points = series
    .map((value, index) => {
      const x = (index / (series.length - 1)) * 100;
      const y = 100 - value;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  return (
    <div className="signal-chart" aria-label="近 30 期證據強度">
      <svg preserveAspectRatio="none" viewBox="0 0 100 100">
        <defs>
          <linearGradient id="signalFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--lime)" stopOpacity="0.24" />
            <stop offset="100%" stopColor="var(--lime)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[20, 40, 60, 80].map((value) => (
          <line key={value} x1="0" x2="100" y1={value} y2={value} />
        ))}
        <polygon fill="url(#signalFill)" points={`0,100 ${points} 100,100`} />
        <polyline className="signal-line" points={points} />
        <line
          className="signal-cursor"
          x1="100"
          x2="100"
          y1="0"
          y2="100"
        />
        <circle
          className="signal-dot"
          cx="100"
          cy={100 - series.at(-1)}
          r="2.2"
        />
      </svg>
      <div className="signal-axis">
        <span>−30</span>
        <span>−20</span>
        <span>−10</span>
        <span>當前</span>
      </div>
    </div>
  );
}
