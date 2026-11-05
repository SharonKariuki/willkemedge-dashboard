import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SettleDepositPage from "./SettleDepositPage";
import type { SettlementPreview } from "@/hooks/useDepositSettlements";

const settle = vi.fn();
const navigate = vi.fn();

vi.mock("react-hot-toast", () => ({ default: { success: vi.fn(), error: vi.fn() } }));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigate };
});

let preview: SettlementPreview;

vi.mock("@/hooks/useDepositSettlements", () => ({
  useSettlementPreview: () => ({ data: preview, isLoading: false }),
  useSettleDeposit: () => ({ mutateAsync: settle, isPending: false }),
}));

vi.mock("@/hooks/useTenants", () => ({
  useTenant: () => ({
    data: { id: 7, full_name: "Jane Tenant", unit_label: "TC1A", building_name: "Test Court" },
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { can_forgive_money: true } }),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/tenants/7/deposit/settle"]}>
      <Routes>
        <Route path="/tenants/:id/deposit/settle" element={<SettleDepositPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function summary(label: string) {
  return screen.getByText(label, { selector: "dt" }).nextElementSibling?.textContent ?? "";
}

describe("SettleDepositPage", () => {
  beforeEach(() => {
    preview = {
      deposit_held: "20000.00",
      balance_owed: "10000.00",
      can_settle: true,
      tenant_status: "moved_out",
      tenant_phone: "+254700000001",
      settlement: null,
      default_categories: { damages: 3, cleaning: 4 },
      expense_categories: [{ id: 3, name: "Repairs & Maintenance" }, { id: 4, name: "Cleaning & Garbage Collection" }],
    };
    settle.mockReset();
    settle.mockResolvedValue({ number: "DS-00001", refund_amount: "8500.00" });
    navigate.mockReset();
  });

  it("starts from the unpaid balance and refunds what is left", async () => {
    renderPage();
    expect(screen.getByLabelText("Deduction amount")).toHaveValue("10000");
    expect(summary("Refund")).toContain("10,000");

    await userEvent.click(screen.getByRole("button", { name: /Cleaning/ }));
    const amounts = screen.getAllByLabelText("Deduction amount");
    await userEvent.type(amounts[1], "1500");
    expect(summary("Refund")).toContain("8,500");
    expect(summary("Not accounted for")).toContain("0");

    await userEvent.click(screen.getByRole("button", { name: /Settle Deposit/ }));
    expect(settle).toHaveBeenCalledWith(expect.objectContaining({
      tenant: 7,
      refund_basis: "remainder",
      deductions: [
        { kind: "unpaid_balance", description: "", amount: "10000.00", expense_category: null },
        { kind: "cleaning", description: "", amount: "1500.00", expense_category: 4 },
      ],
      already_sent: false,
    }));
    expect(navigate).toHaveBeenCalledWith("/tenants/7#deposit");
  });

  it("will not settle a percentage refund until the gap is itemised", async () => {
    renderPage();
    await userEvent.click(screen.getByLabelText("A percentage of the deposit"));
    await userEvent.type(screen.getByPlaceholderText("e.g. 75"), "25");

    expect(summary("Refund")).toContain("5,000");
    expect(summary("Not accounted for")).toContain("5,000");
    await userEvent.click(screen.getByRole("button", { name: /Settle Deposit/ }));
    expect(settle).not.toHaveBeenCalled();
    expect(screen.getByText(/of the deposit is not accounted for/)).toBeInTheDocument();
  });

  it("says why when the tenant has not given notice", () => {
    preview = { ...preview, can_settle: false };
    renderPage();
    expect(screen.getByText(/move-out notice or move-out first/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Settle Deposit/ })).not.toBeInTheDocument();
  });
});
