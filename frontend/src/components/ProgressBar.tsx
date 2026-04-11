interface Props {
  percentage: number;
  showLabel?: boolean;
  size?: "sm" | "md";
}

export default function ProgressBar({ percentage, showLabel = true, size = "md" }: Props) {
  const clamped = Math.min(Math.max(percentage, 0), 100);
  const height = size === "sm" ? "h-2" : "h-3";

  const barColor =
    clamped === 0
      ? "bg-red-500"
      : clamped < 100
        ? "bg-amber-500"
        : "bg-green-500";

  return (
    <div className="w-full">
      <div className={`w-full overflow-hidden rounded-full bg-slate-200 ${height}`}>
        <div
          className={`${height} rounded-full transition-all duration-300 ${barColor}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {showLabel && (
        <p className="mt-1 text-xs text-slate-500 text-right">{clamped.toFixed(0)}%</p>
      )}
    </div>
  );
}
