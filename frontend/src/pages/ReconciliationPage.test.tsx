/**
 * Assigning a bank credit with a deposit / rent split. MR203's 53,000 went in
 * whole as rent; the director now sees "deposit X, rent Y" before confirming
 * and can change the deposit part.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReconciliationPage from "./ReconciliationPage";

const mutate = vi.fn();

vi.mock("react-hot-toast", () => ({ default: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/hooks/useTenants", () => ({ useTenants: () => ({ data: [] }) }));
vi.mock("@/features/payments/tenantChoices", () => ({ toChoices: () => [] }));

// A plain select stands in for the searchable picker.
vi.mock("@/features/payments/TenantPicker", () => ({
  TenantPicker: ({ onChange, ariaLabel }: { onChange: (id: number | null) => void; ariaLabel: string }) => (
    <select aria-label={ariaLabel} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">—</option>
      <option value="195">Samuel Mogoko — MR203</option>
    </select>
  ),
}));

vi.mock("@/hooks/useUnmatchedCredits", () => ({
  useUnmatchedCredits: () => ({
    data: [{
      id: 7, transaction_id: "CB0385042", payment_ref: "", account_number: "", amount: "27000.00",
      channel: "mpesa", narration: "", detail: "", status: "unmatched",
      received_at: "2026-10-23T09:02:26Z", payer_hint: { phone: "", name: "" }, void_requeue_count: 1,
    }],
    isLoading: false, isError: false, refetch: vi.fn(),
  }),
  useCreditSplit: (_id: number, tenant: number | null) => ({
    data: tenant === null ? undefined : {
      amount: "27000.00", deposit_amount: "3000.00", rent_amount: "24000.00",
      deposit_still_to_receive: "3000.00",
    },
    isLoading: false,
  }),
  useAssignCredit: () => ({ mutate, isPending: false }),
}));

describe("ReconciliationPage split", () => {
  beforeEach(() => {
    mutate.mockReset();
    render(<ReconciliationPage />);
  });

  it("prefills the default split and sends it", async () => {
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText(/Assign credit CB0385042/), "195");

    expect(screen.getByLabelText(/Deposit part/)).toHaveValue("3000");
    expect(screen.getByText("KES 24,000")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(mutate).toHaveBeenCalled());
    expect(mutate.mock.calls[0][0]).toEqual({ id: 7, tenant: 195, deposit_amount: "3000" });
  });

  it("lets the director book it all as rent", async () => {
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText(/Assign credit CB0385042/), "195");
    const box = screen.getByLabelText(/Deposit part/);
    await user.clear(box);
    await user.type(box, "0");

    await user.click(screen.getByRole("button", { name: "Assign" }));
    expect(mutate.mock.calls[0][0]).toEqual({ id: 7, tenant: 195, deposit_amount: "0" });
  });

  it("will not assign a deposit larger than the credit", async () => {
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText(/Assign credit CB0385042/), "195");
    const box = screen.getByLabelText(/Deposit part/);
    await user.clear(box);
    await user.type(box, "28000");

    expect(screen.getByText(/Between 0 and KES 27,000/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assign" })).toBeDisabled();
  });
});
