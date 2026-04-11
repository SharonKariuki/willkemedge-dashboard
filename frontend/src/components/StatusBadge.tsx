import type { UnitStatus } from "@/lib/types";

const STATUS_STYLES: Record<UnitStatus, { bg: string; text: string; label: string }> = {
  vacant: { bg: "bg-slate-100", text: "text-slate-700", label: "Vacant" },
  occupied_paid: { bg: "bg-green-100", text: "text-green-800", label: "Paid" },
  occupied_partial: { bg: "bg-amber-100", text: "text-amber-800", label: "Partial" },
  occupied_unpaid: { bg: "bg-red-100", text: "text-red-800", label: "Unpaid" },
  arrears: { bg: "bg-red-200", text: "text-red-900", label: "Arrears" },
};

interface Props {
  status: UnitStatus;
  size?: "sm" | "md";
}

export default function StatusBadge({ status, size = "sm" }: Props) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.vacant;
  const sizeClasses = size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm";

  return (
    <span
      className={`inline-flex items-center rounded-full font-medium ${style.bg} ${style.text} ${sizeClasses}`}
    >
      <span
        className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${
          status === "vacant"
            ? "bg-slate-400"
            : status === "occupied_paid"
              ? "bg-green-500"
              : status === "occupied_partial"
                ? "bg-amber-500"
                : "bg-red-500"
        }`}
      />
      {style.label}
    </span>
  );
}
