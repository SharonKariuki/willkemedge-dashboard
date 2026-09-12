/**
 * Registering a letting: what the deposit box now carries, and the one case
 * where zero rent is legitimate.
 *
 * The deposit is no longer a bare number on the tenant record — the backend
 * books a non-zero figure as a DEPOSIT payment — so the form has to send how,
 * when and under what reference the money arrived. And a caretaker housed as
 * part of their job is the only tenancy allowed through at zero rent.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateTenantForm } from "./TenantsPage";
import type { Unit } from "@/lib/types";

const mutateAsync = vi.fn();

vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useTenants", () => ({
  useCreateTenant: () => ({ mutateAsync, isPending: false }),
  useTenants: () => ({ data: [], isLoading: false }),
}));

const units: Partial<Unit>[] = [
  {
    id: 1, label: "WED1A", building_name: "Wilkem Edge",
    monthly_rent: "20000.00", classification: "RESIDENTIAL",
  },
  {
    id: 2, label: "MCG05", building_name: "Matasia Commercial",
    monthly_rent: "50000.00", classification: "BUSINESS",
  },
];

vi.mock("@/hooks/useUnits", () => ({
  useUnits: () => ({ data: units }),
}));

async function fillRequiredIdentity(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("First name *"), "Grace");
  await user.type(screen.getByLabelText("Last name *"), "Wanjiru");
  await user.type(screen.getByLabelText("ID number *"), "12345678");
  await user.type(screen.getByLabelText("Phone *"), "+254711111111");
}

function submitted() {
  return mutateAsync.mock.calls.at(-1)?.[0] as Record<string, unknown>;
}

describe("CreateTenantForm", () => {
  beforeEach(() => {
    mutateAsync.mockReset();
    mutateAsync.mockResolvedValue({ id: 1 });
    render(<CreateTenantForm onClose={() => {}} />);
  });

  describe("the expected deposit", () => {
    it("previews one month's rent for a residential letting", async () => {
      const user = userEvent.setup();
      await user.selectOptions(screen.getByLabelText("Unit *"), "1");
      await user.type(screen.getByLabelText("Monthly rent (KES) *"), "20000");

      expect(await screen.findByText(/Expected KES 20,000/)).toBeInTheDocument();
      expect(screen.getByText(/1 month/)).toBeInTheDocument();
    });

    it("previews three months for a commercial one", async () => {
      const user = userEvent.setup();
      await user.selectOptions(screen.getByLabelText("Unit *"), "2");
      await user.type(screen.getByLabelText("Monthly rent (KES) *"), "50000");

      expect(await screen.findByText(/Expected KES 150,000/)).toBeInTheDocument();
      expect(screen.getByText(/3 months/)).toBeInTheDocument();
    });

    it("fills the box in on request but never on its own", async () => {
      const user = userEvent.setup();
      await user.selectOptions(screen.getByLabelText("Unit *"), "1");
      await user.type(screen.getByLabelText("Monthly rent (KES) *"), "20000");

      const box = screen.getByLabelText("Deposit received (KES)");
      expect(box).toHaveValue("0");

      await user.click(await screen.findByRole("button", { name: "use this" }));
      expect(box).toHaveValue("20000");
    });
  });

  describe("what the deposit fields send", () => {
    it("carries the source, date and reference through", async () => {
      const user = userEvent.setup();
      await fillRequiredIdentity(user);
      await user.selectOptions(screen.getByLabelText("Unit *"), "1");
      await user.type(screen.getByLabelText("Monthly rent (KES) *"), "20000");

      const box = screen.getByLabelText("Deposit received (KES)");
      await user.clear(box);
      await user.type(box, "20000");
      await user.selectOptions(screen.getByLabelText("How it was received"), "mpesa");
      await user.type(screen.getByLabelText("Date received"), "2026-09-12");
      await user.type(screen.getByLabelText("Reference"), "TJ4X9QW1ZP");

      await user.click(screen.getByRole("button", { name: /Register/ }));

      await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
      expect(submitted()).toMatchObject({
        deposit_paid: "20000",
        deposit_source: "mpesa",
        deposit_date: "2026-09-12",
        deposit_reference: "TJ4X9QW1ZP",
      });
    });

    it("greys the three out while there is no deposit to describe", () => {
      expect(screen.getByLabelText("How it was received")).toBeDisabled();
      expect(screen.getByLabelText("Date received")).toBeDisabled();
      expect(screen.getByLabelText("Reference")).toBeDisabled();
    });
  });

  describe("zero rent", () => {
    it("is refused for an ordinary letting", async () => {
      const user = userEvent.setup();
      await fillRequiredIdentity(user);
      await user.selectOptions(screen.getByLabelText("Unit *"), "1");
      await user.type(screen.getByLabelText("Monthly rent (KES) *"), "0");

      await user.click(screen.getByRole("button", { name: /Register/ }));

      expect(
        await screen.findByText(/Enter an amount greater than 0/),
      ).toBeInTheDocument();
      expect(mutateAsync).not.toHaveBeenCalled();
    });

    it("is allowed once the tenancy is marked as not charged rent", async () => {
      const user = userEvent.setup();
      await fillRequiredIdentity(user);
      await user.selectOptions(screen.getByLabelText("Unit *"), "1");
      await user.type(screen.getByLabelText("Monthly rent (KES) *"), "0");
      await user.click(screen.getByRole("checkbox", { name: /Charge rent/ }));

      await user.click(screen.getByRole("button", { name: /Register/ }));

      await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
      expect(submitted()).toMatchObject({ monthly_rent: "0", is_billable: false });
    });

    it("defaults to charging rent, so the exemption is always deliberate", () => {
      expect(screen.getByRole("checkbox", { name: /Charge rent/ })).toBeChecked();
    });
  });

  describe("the rent due day", () => {
    it("registers fine when left blank, and sends nothing for it", async () => {
      // It coerced "" to 0 and failed its own min(1), so an optional field
      // blocked the whole registration — with the error pointing at Rent Due
      // Day rather than at anything that had been typed.
      const user = userEvent.setup();
      await fillRequiredIdentity(user);
      await user.selectOptions(screen.getByLabelText("Unit *"), "1");
      await user.type(screen.getByLabelText("Monthly rent (KES) *"), "20000");

      await user.click(screen.getByRole("button", { name: /Register/ }));

      await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
      expect(submitted().due_day).toBeUndefined();
    });

    it("still sends a day that was typed", async () => {
      const user = userEvent.setup();
      await fillRequiredIdentity(user);
      await user.selectOptions(screen.getByLabelText("Unit *"), "1");
      await user.type(screen.getByLabelText("Monthly rent (KES) *"), "20000");
      await user.type(screen.getByLabelText("Rent Due Day (1-31)"), "10");

      await user.click(screen.getByRole("button", { name: /Register/ }));

      await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
      expect(submitted().due_day).toBe(10);
    });

    // Out-of-range days are caught by the input's own min/max before the
    // submit handler runs, so the zod bounds are only a backstop and there is
    // nothing here worth asserting in jsdom.
  });

  it("refuses a deposit dated before the keys were handed over", async () => {
    const user = userEvent.setup();
    await fillRequiredIdentity(user);
    await user.selectOptions(screen.getByLabelText("Unit *"), "1");
    await user.type(screen.getByLabelText("Monthly rent (KES) *"), "20000");

    const box = screen.getByLabelText("Deposit received (KES)");
    await user.clear(box);
    await user.type(box, "20000");
    await user.type(screen.getByLabelText("Date received"), "2020-01-01");

    await user.click(screen.getByRole("button", { name: /Register/ }));

    expect(
      await screen.findByText(/Cannot be before the move-in date/),
    ).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
  });
});
