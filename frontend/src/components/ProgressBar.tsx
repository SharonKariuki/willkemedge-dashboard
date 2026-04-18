import { cn } from "@/lib/cn";

interface Props {
  percentage: number;
  showLabel?: boolean;
  size?: "sm" | "md";
  tone?: "auto" | "sage" | "coral" | "ochre" | "peri";
}

export default function ProgressBar({ percentage, showLabel = true, size = "md", tone = "auto" }: Props) {
  const clamped = Math.min(Math.max(percentage, 0), 100);
  const height = size === "sm" ? "h-1.5" : "h-2.5";

  const autoFill =
    clamped === 0
      ? "bg-status-unpaid"
      : clamped < 60
        ? "bg-status-partial"
        : clamped < 100
          ? "bg-sage-500"
          : "bg-status-paid";

  const toneFill = {
    auto: autoFill,
    sage: "bg-gradient-to-r from-sage-400 to-sage-600",
    coral: "bg-gradient-to-r from-coral-400 to-coral-600",
    ochre: "bg-gradient-to-r from-ochre-400 to-ochre-600",
    peri: "bg-gradient-to-r from-peri-400 to-peri-600",
  }[tone];

  return (
    <div className="w-full">
      <div className={cn("w-full overflow-hidden rounded-full bg-ink-100/60", height)}>
        <div
          className={cn(height, "rounded-full transition-all duration-700 ease-out", toneFill)}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {showLabel && (
        <p className="mt-1 text-right text-[11px] font-medium text-ink-500">{clamped.toFixed(0)}%</p>
      )}
    </div>
  );
}
