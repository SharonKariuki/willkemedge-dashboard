import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AddCreditPage from "./AddCreditPage";
import RefundCreditPage from "./RefundCreditPage";
import type { CreditPosition } from "@/hooks/useCredits";

const addCredit = vi.fn();
const createRefund = vi.fn();
const navigate = vi.fn();

vi.mock("react-hot-toast", () => ({ default: { success: vi.fn(), error: vi.fn() } }));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigate };
});

const position: CreditPosition = {
  balance: "3000.00",
  credit_on_account: "0.00",
  overpayment_credit: "0.00",
  credits_available: "0.00",
  credits_held: "0.00",
  refunds_to_send: "0.00",
  refundable: "2000.00",
  reasons: [
    { value: "billing_correction", label: "We charged too much", document: "credit_note", needs_charge: true, rent_only: false, needs_category: false },
    { value: "tenant_paid_cost", label: "Tenant paid for a repair or cost that was ours", document: "account_credit", needs_charge: false, rent_only: false, needs_category: true },
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
  useTenantCredits: () => ({ data: [] }),
}));

vi.mock("@/hooks/useTenants", () => ({
  useTenant: () => ({
    data: { id: 7, full_name: "Sidai Healthcare", unit_label: "MCF12", building_name: "Matasia" },
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { can_forgive_money: true } }),
}));

function renderPage(path: string, element: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/tenants/:id/credits/:action" element={element} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AddCreditPage", () => {
  beforeEach(() => {
    addCredit.mockReset();
    addCredit.mockResolvedValue({
      number: "CN-00001", amount: "2320.00", amount_applied: "0.00", remaining: "2320.00",
    });
    createRefund.mockReset();
    navigate.mockReset();
  });

  it("adds the charge's VAT, shows the balance after, and posts the form", async () => {
    renderPage("/tenants/7/credits/new", <AddCreditPage />);
    expect(screen.getByRole("heading", { name: "Add Credit" })).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText(/Why is the tenant/), "billing_correction");
    await userEvent.selectOptions(screen.getByLabelText(/^Charge/), "11");
    await userEvent.type(screen.getByLabelText(/Amount before VAT/), "2000");
    await userEvent.type(screen.getByLabelText(/Explanation for the tenant/), "Rent overbilled");

    // The summary beside the form carries the VAT-inclusive total all along.
    expect(screen.getByText("KES 2,320")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Review credit" }));
    // 3,000 owed less a 2,320 credit.
    expect(screen.getByText("KES 680")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Issue Credit" }));
    expect(addCredit).toHaveBeenCalledTimes(1);
    const body = addCredit.mock.calls[0][0] as FormData;
    expect(body.get("arrears")).toBe("11");
    expect(body.get("amount")).toBe("2000.00");
    expect(body.get("hold")).toBe("false");
    expect(navigate).toHaveBeenCalledWith("/tenants/7#credit-history");
  });

  it("reviews a tenant-paid cost without a receipt — the document is optional", async () => {
    renderPage("/tenants/7/credits/new", <AddCreditPage />);
    await userEvent.selectOptions(screen.getByLabelText(/Why is the tenant/), "tenant_paid_cost");
    await userEvent.selectOptions(screen.getByLabelText(/What kind of cost/), "4");
    await userEvent.type(screen.getByLabelText(/^Amount/), "5000");
    await userEvent.type(screen.getByLabelText(/Explanation for the tenant/), "Plumber");
    await userEvent.click(screen.getByRole("button", { name: "Review credit" }));

    expect(screen.getByRole("button", { name: "Issue Credit" })).toBeInTheDocument();
  });
});

describe("RefundCreditPage", () => {
  beforeEach(() => {
    createRefund.mockReset();
    createRefund.mockResolvedValue({ number: "RF-00001", amount: "2000.00", status: "sent" });
    navigate.mockReset();
  });

  it("caps the refund at what is refundable and asks for the M-Pesa reference", async () => {
    renderPage("/tenants/7/credits/refund", <RefundCreditPage />);
    expect(screen.getByLabelText(/^Amount/)).toHaveValue("2000");

    await userEvent.click(screen.getByRole("button", { name: /Record Refund/ }));
    expect(screen.getByText(/transaction reference/)).toBeInTheDocument();
    expect(createRefund).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText(/Transaction reference/), "QX7");
    await userEvent.click(screen.getByRole("button", { name: /Record Refund/ }));
    expect(createRefund).toHaveBeenCalledWith(expect.objectContaining({
      amount: "2000.00", method: "mpesa", reference: "QX7", already_sent: true, credit: null,
    }));
    expect(navigate).toHaveBeenCalledWith("/tenants/7#credit-history");
  });

  it("warns when the money is going to someone other than the tenant", async () => {
    renderPage("/tenants/7/credits/refund", <RefundCreditPage />);
    const paidTo = screen.getByLabelText(/Paid to/);
    await userEvent.clear(paidTo);
    await userEvent.type(paidTo, "+254700000000");
    expect(screen.getByText(/isn.t the tenant.s registered number/)).toBeInTheDocument();
  });
});
