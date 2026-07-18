export default function NumberBall({
  number,
  active = false,
  special = false,
  compact = false,
}) {
  const classNames = [
    "number-ball",
    active ? "is-active" : "",
    special ? "is-special" : "",
    compact ? "is-compact" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <span className={classNames}>
      {String(number).padStart(2, "0")}
    </span>
  );
}
