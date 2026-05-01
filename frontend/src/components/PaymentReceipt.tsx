/**
 * PaymentReceipt.tsx
 *
 * Reusable receipt component. Accepts a ReceiptData prop and renders
 * the correct layout based on the conditional flags set by the backend:
 *
 *   show_tax_line  === true  → BUSINESS layout (Base + VAT + Total)
 *   show_total_only === true → RESIDENTIAL layout (Total only)
 *
 * This component is intentionally "dumb" — it does not compute or derive
 * any financial values. All amounts come from the stored ReceiptData.
 */

import { Building2, Calendar, CreditCard, Hash, Receipt, Tag, Wallet } from "lucide-react";

import { cn } from "@/lib/cn";
import { buildReceiptDisplay } from "@/lib/receiptService";
import type { ReceiptData } from "@/lib/types";

interface PaymentReceiptProps {
  data: ReceiptData;
  className?: string;
}

function MetaRow({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <div className="flex items-center gap-2 text-ink-500">
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span className="text-xs">{label}</span>
      </div>
      <span className="text-right text-xs font-medium text-ink-900">{value}</span>
    </div>
  );
}

function Divider() {
  return <hr className="my-3 border-dashed border-ink-200" />;
}

export default function PaymentReceipt({ data, className }: PaymentReceiptProps) {
  const receipt = buildReceiptDisplay(data);

  return (
    <div
      className={cn(
        "rounded-xl border border-ink-200 bg-canvas p-5 shadow-sm font-mono text-sm",
        "dark:border-ink-700 dark:bg-surface-raised",
        className,
      )}
      role="region"
      aria-label="Payment Receipt"
    >
      {/* Header */}
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Receipt className="h-4 w-4 text-sage-600" />
            <span className="font-sans text-xs font-semibold uppercase tracking-widest text-sage-700">
              Payment Receipt
            </span>
          </div>
          <p className="mt-1 font-sans text-lg font-bold text-ink-900">
            {receipt.tenantName}
          </p>
          <p className="text-xs text-ink-500">
            {receipt.buildingName} · Unit {receipt.unitLabel}
          </p>
        </div>
        <span
          className={cn(
            "rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
            data.unit_classification === "BUSINESS"
              ? "bg-peri-100 text-peri-700 dark:bg-peri-900/30 dark:text-peri-300"
              : "bg-sage-100 text-sage-700 dark:bg-sage-900/30 dark:text-sage-300",
          )}
        >
          {receipt.classificationLabel}
        </span>
      </div>

      <Divider />

      {/* Meta information */}
      <div>
        <MetaRow icon={Calendar} label="Period" value={receipt.period} />
        {receipt.paymentDate && (
          <MetaRow icon={Calendar} label="Payment Date" value={receipt.paymentDate} />
        )}
        <MetaRow icon={Wallet} label="Payment Mode" value={receipt.paymentMode} />
        {receipt.referenceCode && (
          <MetaRow icon={Tag} label="Reference" value={receipt.referenceCode} />
        )}
        <MetaRow icon={Hash} label="Transaction ID" value={receipt.transactionId} />
      </div>

      <Divider />

      {/* Financial line items — rendered from pre-built array, no logic here */}
      <div className="space-y-1.5">
        {receipt.lineItems.map((item) => (
          <div
            key={item.label}
            className={cn(
              "flex items-center justify-between gap-4",
              item.highlight && "mt-2 rounded-md bg-sage-50 px-3 py-2 dark:bg-sage-900/20",
            )}
          >
            <span
              className={cn(
                "text-xs",
                item.highlight
                  ? "font-semibold text-ink-900"
                  : "text-ink-500",
              )}
            >
              {item.label}
            </span>
            <span
              className={cn(
                "tabular-nums",
                item.highlight
                  ? "text-sm font-bold text-sage-700 dark:text-sage-400"
                  : "text-xs font-medium text-ink-700",
              )}
            >
              {item.value}
            </span>
          </div>
        ))}
      </div>

      {/* Outstanding balance (optional) */}
      {receipt.outstandingBalance && (
        <>
          <Divider />
          <div className="flex items-center justify-between gap-4 rounded-md bg-coral-50 px-3 py-2 dark:bg-coral-900/20">
            <div className="flex items-center gap-2">
              <CreditCard className="h-3.5 w-3.5 text-coral-600" />
              <span className="text-xs font-medium text-coral-700 dark:text-coral-300">
                Outstanding Balance
              </span>
            </div>
            <span className="tabular-nums text-sm font-bold text-coral-700 dark:text-coral-300">
              {receipt.outstandingBalance}
            </span>
          </div>
        </>
      )}

      {/* Footer */}
      <Divider />
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-ink-400">
          <Building2 className="h-3 w-3" />
          <span className="text-[10px]">Dr. William Osoro — Property Management</span>
        </div>
        <span className="text-[10px] text-ink-400">
          {data.unit_classification === "BUSINESS" ? "VAT Inc." : "VAT Exempt"}
        </span>
      </div>
    </div>
  );
}
