import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import QuickActions from "./QuickActions";

let me: Record<string, unknown> = {};
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ user: me }) }));

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

const renderAs = (user: Record<string, unknown>) => {
  me = user;
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <QuickActions />
      <Routes><Route path="*" element={<Where />} /></Routes>
    </MemoryRouter>,
  );
};

const labels = async () => {
  await userEvent.click(screen.getByRole("button", { name: /Quick actions/ }));
  return within(screen.getByRole("menu")).getAllByRole("menuitem").map((b) => b.textContent);
};

describe("Quick actions", () => {
  it("gives the owner everything, starting with inviting someone", async () => {
    renderAs({ role: "owner", is_superuser: false, capabilities: ["view_finance","record_money","forgive_money","view_property","manage_property","record_water","log_maintenance","send_messages","view_activity","manage_users"] });
    const items = await labels();
    expect(items[0]).toMatch(/Invite someone/);
    expect(items).toHaveLength(10);
  });

  it("gives a caretaker only water and maintenance", async () => {
    renderAs({ role: "caretaker", capabilities: ["view_property", "record_water", "log_maintenance"] });
    const items = await labels();
    expect(items.map((t) => t?.replace(/Open the unit.*/, ""))).toEqual(["Capture water readings", "Log maintenance"]);
  });

  it("follows a person's own changes, not just their role", async () => {
    renderAs({ role: "viewer", capabilities: ["view_finance", "view_property", "record_money"] });
    const items = await labels();
    expect(items.some((t) => t?.startsWith("Record an expense"))).toBe(true);
    expect(items.some((t) => t?.startsWith("Invite someone"))).toBe(false);
  });

  it("opens the form it names", async () => {
    renderAs({ role: "accountant", capabilities: ["view_finance", "record_money", "view_property"] });
    await userEvent.click(screen.getByRole("button", { name: /Quick actions/ }));
    await userEvent.click(screen.getByRole("menuitem", { name: /Record an expense/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/expenses?new=1");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("closes on Escape and returns focus to the button", async () => {
    renderAs({ role: "accountant", capabilities: ["view_finance", "record_money"] });
    await userEvent.click(screen.getByRole("button", { name: /Quick actions/ }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByRole("button", { name: /Quick actions/ })).toHaveFocus();
  });

  it("isn't shown to someone with nothing on the list", () => {
    renderAs({ role: "viewer", capabilities: ["view_property"] });
    expect(screen.queryByRole("button", { name: /Quick actions/ })).toBeNull();
  });
});
