import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddCreditModal, RefundCreditModal } from "./CreditModals";
import type { CreditPosition } from "@/hooks/useCredits";

const addCredit = vi.fn();
const createRefund = vi.fn();

vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

const position: CreditPosition = {
  balance: "3000.00",
  credit_on_account: "0.00",
  overpayment_credit: "0.00",
  credits_available: "0.00",
  credits_held: "0.00",
  refunds_to_send: "0.00",
  refundable: "2000.00",
  reasons: [
    { value: "billing_correction", label: "We charged too much", document: "credit_note", needs_charge: true, rent_only: false, needs_category: false, evidence_required: false },
    { value: "tenant_paid_cost", label: "Tenant paid for a repair or cost that was ours", document: "account_credit", needs_charge: false, rent_only: false, needs_category: true, evidence_required: true },
  ],
  rent_charges: [
    { id: 11, label: "Rent September 2026", charged: "10000.00", vat: "1600.00", creditable: "10000.00", vat_rate: "0.1600" },
  ],
  water_charges: [],
  expense_categories: [{ id: 4, name: "Plumbing & Electrical" }],
  tenant_phone: "+254711111111",
};

vi.mock("@/hooks/useCredits", () => ({
  useCreditPosition: () => ({ data: position, isLoading: false }),
  useAddCredit: () => ({ mutateAsync: addCredit, isPending: false }),
  useCreateRefund: () => ({ mutateAsync: createRefund, isPending: false }),
  useMarkRefundSent: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useVoidCredit: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useVoidCreditPreview: () => ({ data: undefined, isLoading: false, isError: false }),
  useCloseRefund: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

function renderAdd() {
  return render(
    <MemoryRouter>
      <AddCreditModal tenantId={7} tenantName="Sidai Healthcare" onClose={() => {}} />
    </MemoryRouter>,
  );
}

describe("AddCreditModal", () => {
  beforeEach(() => {
    addCredit.mockReset();
    createRefund.mockReset();
  });

  it("adds the charge's VAT to a billing correction and shows the balance after", async () => {
    renderAdd();
    await userEvent.selectOptions(screen.getByLabelText(/Why is the tenant/), "billing_correction");
    await userEvent.selectOptions(screen.getByLabelText(/^Charge/), "11");
    await userEvent.type(screen.getByLabelText(/Amount before VAT/), "2000");
    expect(screen.getByText(/KES 2,320 credit/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/Explanation for the tenant/), "Rent overbilled");
    await userEvent.click(screen.getByRole("button", { name: "Review credit" }));

    // 3,000 owed less a 2,320 credit.
    expect(screen.getByText("KES 680")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Issue Credit" }));
    expect(addCredit).toHaveBeenCalledTimes(1);
    const form = addCredit.mock.calls[0][0] as FormData;
    expect(form.get("arrears")).toBe("11");
    expect(form.get("amount")).toBe("2000.00");
    expect(form.get("hold")).toBe("false");
  });

  it("will not review a tenant-paid cost without its receipt", async () => {
    renderAdd();
    await userEvent.selectOptions(screen.getByLabelText(/Why is the tenant/), "tenant_paid_cost");
    await userEvent.selectOptions(screen.getByLabelText(/What kind of cost/), "4");
    await userEvent.type(screen.getByLabelText(/^Amount/), "5000");
    await userEvent.type(screen.getByLabelText(/Explanation for the tenant/), "Plumber");
    await userEvent.click(screen.getByRole("button", { name: "Review credit" }));

    expect(screen.getByText(/Attach the supporting document/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Issue Credit" })).not.toBeInTheDocument();
  });
});

describe("RefundCreditModal", () => {
  it("caps the refund at what is refundable and asks for the M-Pesa reference", async () => {
    render(<RefundCreditModal tenantId={7} tenantName="Sidai Healthcare" onClose={() => {}} />);
    expect(screen.getByLabelText(/^Amount/)).toHaveValue("2000");

    await userEvent.click(screen.getByRole("button", { name: /Record Refund/ }));
    expect(screen.getByText(/transaction reference/)).toBeInTheDocument();
    expect(createRefund).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText(/Transaction reference/), "QX7");
    await userEvent.click(screen.getByRole("button", { name: /Record Refund/ }));
    expect(createRefund).toHaveBeenCalledWith(expect.objectContaining({
      amount: "2000.00", method: "mpesa", reference: "QX7", already_sent: true,
    }));
  });

  it("warns when the money is going to someone other than the tenant", async () => {
    render(<RefundCreditModal tenantId={7} tenantName="Sidai Healthcare" onClose={() => {}} />);
    const paidTo = screen.getByLabelText(/Paid to/);
    await userEvent.clear(paidTo);
    await userEvent.type(paidTo, "+254700000000");
    expect(screen.getByText(/isn.t the tenant.s registered number/)).toBeInTheDocument();
  });
});
