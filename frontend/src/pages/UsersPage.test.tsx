import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ManagedUser } from "@/hooks/useUsers";

import UsersPage from "./UsersPage";

const mutate = vi.fn();
let me: { is_superuser: boolean } = { is_superuser: false };

vi.mock("react-hot-toast", () => ({ default: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ user: me }) }));

const person = (over: Partial<ManagedUser>): ManagedUser => ({
  id: 1, email: "x@example.com", first_name: "", last_name: "", full_name: "", role: "viewer",
  role_display: "Viewer (read-only)", status: "active", is_superuser: false, last_login: null,
  date_joined: "2026-11-01T00:00:00Z", invited_at: null, invited_by_email: null,
  invite_expires_at: null, deactivated_at: null, is_self: false, ...over,
});

const USERS = [
  person({ id: 1, email: "sharon@example.com", full_name: "Sharon K", role: "owner", role_display: "Owner / Director", is_superuser: true }),
  person({ id: 2, email: "osoro@example.com", full_name: "Wilson Osoro", role: "owner", role_display: "Owner / Director", is_self: true }),
  person({ id: 3, email: "jane@example.com", full_name: "Jane Caretaker", role: "caretaker", role_display: "Caretaker",
           status: "invited", invited_at: "2026-11-14T10:00:00Z", invite_expires_at: "2026-11-17T10:00:00Z" }),
  person({ id: 4, email: "acc@example.com", full_name: "Peter Accounts", role: "accountant", role_display: "Accountant" }),
  person({ id: 5, email: "gone@example.com", full_name: "Old Clerk", status: "deactivated", deactivated_at: "2026-10-01T00:00:00Z" }),
];

const OWNER_ROLES = [
  { value: "accountant", label: "Accountant" },
  { value: "caretaker", label: "Caretaker" },
  { value: "viewer", label: "Viewer (read-only)" },
];

vi.mock("@/hooks/useUsers", () => ({
  useUsers: () => ({ data: { users: USERS, assignable_roles: OWNER_ROLES }, isLoading: false, isError: false }),
  useInviteUser: () => ({ mutateAsync: mutate, isPending: false }),
  useUpdateUser: () => ({ mutateAsync: mutate, isPending: false }),
  useUserAction: () => ({ mutateAsync: mutate, isPending: false }),
}));

const row = (name: string) => screen.getByText(name).closest("tr") as HTMLElement;

describe("UsersPage, signed in as the owner", () => {
  beforeEach(() => {
    mutate.mockReset();
    mutate.mockResolvedValue({});
    me = { is_superuser: false };
  });

  it("leaves the superadmin and the owner's own account alone", () => {
    render(<UsersPage />);
    for (const name of ["Sharon K", "Wilson Osoro"]) {
      const r = within(row(name));
      expect(r.queryByRole("combobox")).toBeNull();
      expect(r.queryByRole("button")).toBeNull();
    }
    expect(within(row("Sharon K")).getByText("Superadmin")).toBeInTheDocument();
    expect(within(row("Wilson Osoro")).getByText("You")).toBeInTheDocument();
  });

  it("changes someone's role", async () => {
    render(<UsersPage />);
    await userEvent.selectOptions(within(row("Peter Accounts")).getByRole("combobox"), "viewer");
    expect(mutate).toHaveBeenCalledWith({ id: 4, role: "viewer" });
  });

  it("re-sends a pending invite and switches a deactivated account back on", async () => {
    render(<UsersPage />);
    expect(within(row("Jane Caretaker")).getByText(/link expires/)).toBeInTheDocument();
    await userEvent.click(within(row("Jane Caretaker")).getByRole("button", { name: /Resend invite/ }));
    expect(mutate).toHaveBeenCalledWith({ id: 3, action: "resend" });
    await userEvent.click(within(row("Old Clerk")).getByRole("button", { name: /Switch on/ }));
    expect(mutate).toHaveBeenCalledWith({ id: 5, action: "reactivate" });
  });

  it("asks before switching an account off", async () => {
    render(<UsersPage />);
    await userEvent.click(within(row("Peter Accounts")).getByRole("button", { name: /Switch off/ }));
    expect(mutate).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /Switch off/ }));
    expect(mutate).toHaveBeenCalledWith({ id: 4, action: "deactivate" });
  });

  it("invites someone with only the roles the owner may give", async () => {
    render(<UsersPage />);
    await userEvent.click(screen.getByRole("button", { name: /Invite someone/ }));
    const dialog = screen.getByRole("dialog");
    const roles = within(dialog).getByLabelText(/Role/) as HTMLSelectElement;
    expect([...roles.options].map((o) => o.value)).toEqual(["accountant", "caretaker", "viewer"]);

    await userEvent.type(within(dialog).getByLabelText(/Email/), "mary@example.com");
    await userEvent.selectOptions(roles, "caretaker");
    await userEvent.click(within(dialog).getByRole("button", { name: /Send invite/ }));
    expect(mutate).toHaveBeenCalledWith({ email: "mary@example.com", role: "caretaker", first_name: "", last_name: "" });
  });
});

describe("UsersPage, signed in as the superadmin", () => {
  it("may act on owners and other superadmin accounts too", () => {
    me = { is_superuser: true };
    render(<UsersPage />);
    expect(within(row("Peter Accounts")).getByRole("combobox")).toBeInTheDocument();
    expect(within(row("Sharon K")).getByRole("button", { name: /Switch off/ })).toBeInTheDocument();
  });
});
