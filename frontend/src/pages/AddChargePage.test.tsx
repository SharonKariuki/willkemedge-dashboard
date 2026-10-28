import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AddChargePage from "./AddChargePage";
import type { ChargeOptions } from "@/hooks/useCharges";

const addCharge = vi.fn();
const navigate = vi.fn();
let canForgive = true;

vi.mock("react-hot-toast", () => ({ default: { success: vi.fn(), error: vi.fn() } }));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigate };
});

const options: ChargeOptions = {
  charge_types: [
    { value: "garbage", label: "Garbage collection", account: "4150 Service Charge / Utilities Reimbursed by Tenants" },
    { value: "utility", label: "Water or other utility", account: "4150 Service Charge / Utilities Reimbursed by Tenants" },
    { value: "late_fee", label: "Late payment penalty", account: "4200 Late Payment Fees / Penalties" },
    { value: "parking", label: "Parking", account: "4250 Parking Fees" },
    { value: "damage", label: "Damage or repair recharge", account: "" },
  ],
  expense_categories: [{ id: 4, name: "Repairs & Maintenance", account: "5200 Repairs & Maintenance" }],
};

vi.mock("@/hooks/useCharges", () => ({
  useChargeOptions: () => ({ data: options, isLoading: false }),
  useAddCharge: () => ({ mutateAsync: addCharge, isPending: false }),
}));

vi.mock("@/hooks/useCredits", () => ({
  useCreditPosition: () => ({ data: { balance: "3000.00" }, isLoading: false }),
}));

vi.mock("@/hooks/useTenants", () => ({
  useTenant: () => ({
    data: { id: 7, full_name: "Mercy Murunga", unit_label: "DON1A", building_name: "Donholm" },
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { can_forgive_money: canForgive } }),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/tenants/7/charges/new"]}>
      <Routes>
        <Route path="/tenants/:id/charges/new" element={<AddChargePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AddChargePage", () => {
  beforeEach(() => {
    canForgive = true;
    addCharge.mockReset();
    addCharge.mockResolvedValue({ id: 1 });
    navigate.mockReset();
  });

  it("fills the penalty wording, names the account and posts the charge", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Add Charge" })).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText(/Type of charge/), "late_fee");
    expect(screen.getByLabelText(/Reason for the charge/)).toHaveValue("Late payment penalty");
    await userEvent.type(screen.getByLabelText(/^Amount/), "1500");
    expect(screen.getByText(/Booked to 4200 Late Payment Fees/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Review charge" }));
    // 3,000 owed plus a 1,500 charge.
    expect(screen.getByText("KES 4,500")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Add Charge" }));
    expect(addCharge).toHaveBeenCalledTimes(1);
    expect(addCharge.mock.calls[0][0]).toMatchObject({
      tenant: 7, charge_type: "late_fee", amount: "1500.00",
      label: "Late payment penalty", expense_category: null,
    });
    expect(navigate).toHaveBeenCalledWith("/tenants/7");
  });

  it("lists the named service charges under the one account they book to", async () => {
    renderPage();
    const group = screen.getByRole("group", { name: /^4150/ });
    expect(group).toContainElement(screen.getByRole("option", { name: "Garbage collection" }));
    expect(group).toContainElement(screen.getByRole("option", { name: "Water or other utility" }));

    await userEvent.selectOptions(screen.getByLabelText(/Type of charge/), "garbage");
    expect(screen.getByLabelText(/Reason for the charge/)).toHaveValue("Garbage collection");
    expect(screen.getByText(/Booked to 4150/)).toBeInTheDocument();
  });

  it("asks which expense a damage recharge recovers", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText(/Type of charge/), "damage");
    await userEvent.type(screen.getByLabelText(/Reason for the charge/), "Broken window");
    await userEvent.type(screen.getByLabelText(/^Amount/), "3500");
    await userEvent.click(screen.getByRole("button", { name: "Review charge" }));
    expect(screen.getByText(/Choose which expense/)).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText(/Which expense/), "4");
    await userEvent.click(screen.getByRole("button", { name: "Review charge" }));
    await userEvent.click(screen.getByRole("button", { name: "Add Charge" }));
    expect(addCharge.mock.calls[0][0]).toMatchObject({ charge_type: "damage", expense_category: 4 });
  });

  it("is the owner's alone", () => {
    canForgive = false;
    renderPage();
    expect(screen.getByText("Only the owner can add a charge.")).toBeInTheDocument();
  });
});
