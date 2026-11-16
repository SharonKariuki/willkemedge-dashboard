import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ManagedUser } from "@/hooks/useUsers";

import { BuildingCaretakers } from "./BuildingCaretakers";

const mutate = vi.fn();
const toastError = vi.fn();
vi.mock("react-hot-toast", () => ({ default: { success: vi.fn(), error: (...a: unknown[]) => toastError(...a) } }));

const person = (over: Partial<ManagedUser>): ManagedUser => ({
  id: 1, email: "x@example.com", first_name: "", last_name: "", full_name: "", role: "caretaker",
  role_display: "Caretaker", status: "active", is_superuser: false, last_login: null,
  date_joined: "2026-11-01T00:00:00Z", invited_at: null, invited_by_email: null, invite_expires_at: null,
  deactivated_at: null, is_self: false, buildings: [], access_expires_on: null,
  extra_capabilities: [], removed_capabilities: [], capabilities: [], ...over,
});

const USERS = [
  person({ id: 1, full_name: "Jane Only", buildings: [{ id: 10, name: "Block A" }] }),
  person({ id: 2, full_name: "Ben Both", buildings: [{ id: 10, name: "Block A" }, { id: 11, name: "Block B" }] }),
  person({ id: 3, full_name: "Cate Elsewhere", buildings: [{ id: 11, name: "Block B" }] }),
  person({ id: 4, full_name: "Ann Accountant", role: "accountant" }),
];

vi.mock("@/hooks/useUsers", () => ({
  useUsers: () => ({ data: { users: USERS }, isLoading: false }),
  useUpdateUser: () => ({ mutateAsync: mutate, isPending: false }),
}));

const renderCard = () =>
  render(<MemoryRouter><BuildingCaretakers buildingId={10} buildingName="Block A" /></MemoryRouter>);

describe("Caretakers on a property", () => {
  beforeEach(() => {
    mutate.mockReset();
    mutate.mockResolvedValue({});
    toastError.mockReset();
  });

  it("lists who looks after it, and offers only the other caretakers", () => {
    renderCard();
    expect(screen.getByText("Jane Only")).toBeInTheDocument();
    expect(screen.getByText("Ben Both")).toBeInTheDocument();
    const options = [...(screen.getByLabelText(/Add a caretaker/) as HTMLSelectElement).options].map((o) => o.text);
    expect(options).toEqual(["Add an existing caretaker…", "Cate Elsewhere"]);
  });

  it("adds a caretaker, keeping the properties they already have", async () => {
    renderCard();
    await userEvent.selectOptions(screen.getByLabelText(/Add a caretaker/), "3");
    await userEvent.click(screen.getByRole("button", { name: /Add/ }));
    expect(mutate).toHaveBeenCalledWith({ id: 3, buildings: [11, 10] });
  });

  it("takes one off, but never leaves a caretaker with no property", async () => {
    renderCard();
    await userEvent.click(screen.getByRole("button", { name: "Take Ben Both off Block A" }));
    expect(mutate).toHaveBeenCalledWith({ id: 2, buildings: [11] });

    await userEvent.click(screen.getByRole("button", { name: "Take Jane Only off Block A" }));
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(toastError).toHaveBeenCalledWith(expect.stringMatching(/only looks after Block A/));
  });
});
