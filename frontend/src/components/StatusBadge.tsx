import type { UnitStatus } from "@/lib/types";
import { Badge } from "./ui";

const STATUS_MAP: Record<UnitStatus, { tone: "paid" | "partial" | "unpaid" | "vacant"; label: string }> = {
  vacant: { tone: "vacant", label: "Vacant" },
  occupied_paid: { tone: "paid", label: "Paid" },
  occupied_partial: { tone: "partial", label: "Partial" },
  occupied_unpaid: { tone: "unpaid", label: "Unpaid" },
  arrears: { tone: "unpaid", label: "Arrears" },
};

interface Props {
  status: UnitStatus;
  size?: "sm" | "md";
}

export default function StatusBadge({ status }: Props) {
  const { tone, label } = STATUS_MAP[status] ?? STATUS_MAP.vacant;
  return (
    <Badge tone={tone} withDot>
      {label}
    </Badge>
  );
}
