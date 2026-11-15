import { describe, expect, it } from "vitest";

import type { StoredUser } from "@/lib/authStorage";

import { roleLabel, userName } from "./access";

const user = (over: Partial<StoredUser>): StoredUser =>
  ({ id: 1, email: "grace.njeri@example.com", role: "accountant", is_superuser: false, ...over }) as StoredUser;

describe("who the signed-in person is shown as", () => {
  it("shows the superadmin as Superadmin, whatever role their account carries", () => {
    const me = user({ email: "someone@example.com", role: "owner", is_superuser: true });
    expect(roleLabel(me)).toBe("Superadmin");
    expect(userName(me)).toBe("Superadmin");
  });

  it("uses a name when the account has one", () => {
    expect(userName(user({ first_name: "Wilson", last_name: "Osoro", role: "owner" }))).toBe("Wilson Osoro");
    expect(roleLabel(user({ role: "owner" }))).toBe("Owner");
  });

  it("names each role", () => {
    for (const [role, label] of [
      ["accountant", "Accountant"], ["auditor", "Auditor"], ["caretaker", "Caretaker"], ["viewer", "Viewer"],
    ] as const) {
      expect(roleLabel(user({ role }))).toBe(label);
    }
  });

  it("falls back to the front of the email, never someone else's name", () => {
    expect(userName(user({}))).toBe("grace.njeri");
  });
});
