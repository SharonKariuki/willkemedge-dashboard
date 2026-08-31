import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VoidPaymentModal } from "./VoidPaymentModal";
import type { Payment } from "@/hooks/usePayments";

const mutateAsync = vi.fn();
const preview = vi.fn();

vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/usePayments", () => ({
  useVoidPreview: () => preview(),
  useVoidPayment: () => ({ mutateAsync, isPending: false }),
}));

const payment = (over: Partial<Payment> = {}): Payment => ({
  id: 1,
  tenant: 7,
  tenant_name: "Erick Odhiambo",
  unit_label: "B12",
  building_name: "Road Block",
  amount: "5000.00",
  payment_date: "2026-08-05",
  period_month: 8,
  period_year: 2026,
  source: "mpesa",
  source_display: "M-Pesa",
  payment_type: "rent",
  reference: "MPESA1",
  notes: "",
  is_void: false,
  voided_at: null,
  void_reason: "",
  created_at: "2026-08-05T10:00:00Z",
  ...over,
});

const ok = (siblings: Payment[], total: string) => ({
  data: { payment: payment(), siblings, total },
  isLoading: false,
  isError: false,
});

describe("VoidPaymentModal", () => {
  beforeEach(() => {
    mutateAsync.mockReset();
    preview.mockReset();
  });

  it("will not void until a reason is given", async () => {
    preview.mockReturnValue(ok([], "5000.00"));
    render(<VoidPaymentModal payment={payment()} onClose={() => {}} />);

    const button = screen.getByRole("button", { name: /^Void KES/ });
    expect(button).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/Reason/), "wrong unit");
    expect(button).toBeEnabled();
  });

  it("voids the whole credit when it was split across periods", async () => {
    preview.mockReturnValue(
      ok([payment({ id: 2, period_month: 7, amount: "5000.00" })], "10000.00"),
    );
    render(<VoidPaymentModal payment={payment()} onClose={() => {}} />);

    expect(screen.getByText(/split across 2 payments/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/Reason/), "wrong unit");
    await userEvent.click(screen.getByRole("button", { name: /Void 2 payments/ }));

    expect(mutateAsync).toHaveBeenCalledWith({
      id: 1,
      reason: "wrong unit",
      scope: "reference",
    });
  });

  it("can be narrowed to the clicked row alone", async () => {
    preview.mockReturnValue(
      ok([payment({ id: 2, period_month: 7, amount: "5000.00" })], "10000.00"),
    );
    render(<VoidPaymentModal payment={payment()} onClose={() => {}} />);

    await userEvent.click(screen.getByRole("radio", { name: /this row only/i }));
    await userEvent.type(screen.getByLabelText(/Reason/), "wrong period");
    await userEvent.click(screen.getByRole("button", { name: /^Void KES/ }));

    expect(mutateAsync).toHaveBeenCalledWith({
      id: 1,
      reason: "wrong period",
      scope: "single",
    });
  });

  it("refuses to void blind when the group could not be loaded", async () => {
    preview.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    render(<VoidPaymentModal payment={payment()} onClose={() => {}} />);

    await userEvent.type(screen.getByLabelText(/Reason/), "wrong unit");
    expect(screen.getByRole("button", { name: /^Void KES/ })).toBeDisabled();
  });
});
