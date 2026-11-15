import { describe, expect, it } from "vitest";

import { type PermissionCatalog, canTurnOn, effective, toggle } from "./permissions";

const catalog: PermissionCatalog = {
  permissions: [
    { value: "view_finance", area: "Money", label: "See the books", hint: "", requires: [], grantable: true },
    { value: "record_money", area: "Money", label: "Record money", hint: "", requires: ["view_finance"], grantable: true },
    { value: "forgive_money", area: "Money", label: "Void", hint: "", requires: ["view_finance"], grantable: false },
    { value: "view_property", area: "Properties", label: "See properties", hint: "", requires: [], grantable: true },
    { value: "record_water", area: "Water", label: "Water", hint: "", requires: ["view_property"], grantable: true },
  ],
  roleCapabilities: {
    viewer: ["view_finance", "view_property"],
    caretaker: ["view_property", "record_water"],
    accountant: ["view_finance", "record_money", "view_property", "record_water"],
  },
  scopedRoles: ["caretaker"],
};

describe("a person's permissions", () => {
  it("adds to and takes from the role", () => {
    const caps = effective(catalog, "viewer", { added: ["record_money"], removed: ["view_property"] });
    expect([...caps].sort()).toEqual(["record_money", "view_finance"]);
  });

  it("drops anything whose requirement is gone", () => {
    expect(effective(catalog, "accountant", { added: [], removed: ["view_finance"] }).has("record_money")).toBe(false);
  });

  it("gives a building-limited role nothing extra", () => {
    expect(effective(catalog, "caretaker", { added: ["view_finance"], removed: [] }).has("view_finance")).toBe(false);
  });

  it("ticking brings the requirement along; unticking takes dependants away", () => {
    const noBooks = { added: [], removed: ["view_finance"] };
    expect(toggle(catalog, "viewer", noBooks, "record_money", true)).toEqual({ added: ["record_money"], removed: [] });
    expect(toggle(catalog, "accountant", { added: [], removed: [] }, "view_finance", false))
      .toEqual({ added: [], removed: ["view_finance", "record_money"] });
  });

  it("only lets the editor tick what they may give, or what the person already held", () => {
    expect(canTurnOn(catalog, "viewer", "record_money", [])).toBe(true);
    expect(canTurnOn(catalog, "viewer", "forgive_money", [])).toBe(false);
    expect(canTurnOn(catalog, "viewer", "forgive_money", ["forgive_money"])).toBe(true);
    expect(canTurnOn(catalog, "caretaker", "view_finance", [])).toBe(false);
    // Whatever the role has can always come back.
    expect(canTurnOn(catalog, "caretaker", "record_water", [])).toBe(true);
  });
});
