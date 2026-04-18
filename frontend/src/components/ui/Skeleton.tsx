import { cn } from "@/lib/cn";

interface Props {
  className?: string;
  rounded?: "sm" | "md" | "lg" | "full";
}

export function Skeleton({ className, rounded = "md" }: Props) {
  const r = { sm: "rounded-sm", md: "rounded-md", lg: "rounded-lg", full: "rounded-full" }[rounded];
  return (
    <div
      className={cn(
        "relative overflow-hidden bg-ink-100/70",
        r,
        className
      )}
    >
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/50 to-transparent dark:via-white/5" />
    </div>
  );
}
