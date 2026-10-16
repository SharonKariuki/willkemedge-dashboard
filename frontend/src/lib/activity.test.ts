import { describe, expect, it } from "vitest";

import {
  changedFields,
  dayHeading,
  describeDevice,
  groupActivity,
  timeOfDay,
  whoDidIt,
  type ActivityRow,
} from "./activity";

function row(id: number, patch: Partial<ActivityRow> = {}): ActivityRow {
  return {
    id,
    created_at: "2026-09-28T07:14:00Z",
    kind: "change",
    action: "payment.update",
    summary: `row ${id}`,
    object_type: "payment",
    object_id: 1,
    object_label: "",
    old_values: {},
    new_values: {},
    is_financial: false,
    actor: null,
    actor_label: "",
    actor_role: "",
    source: "web",
    source_detail: "",
    ip_address: null,
    user_agent: "",
    session_id: "",
    request_id: `req-${id}`,
    ...patch,
  };
}

describe("groupActivity", () => {
  it("heads a request with its named action and folds the field changes under it", () => {
    const groups = groupActivity([
      row(3, { kind: "event", action: "payment.void", request_id: "a" }),
      row(2, { request_id: "a", is_financial: true }),
      row(1, { request_id: "b" }),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0].head.id).toBe(3);
    expect(groups[0].details.map((r) => r.id)).toEqual([2]);
    expect(groups[0].isFinancial).toBe(true);
    expect(groups[1].head.id).toBe(1);
  });

  it("heads a command's group with its announcement, which is written first", () => {
    const groups = groupActivity([
      row(3, { request_id: "cmd" }),
      row(2, { request_id: "cmd" }),
      row(1, { kind: "event", action: "command.run", request_id: "cmd" }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].head.action).toBe("command.run");
    expect(groups[0].details.map((r) => r.id)).toEqual([3, 2]);
  });

  it("never merges rows without a request id", () => {
    expect(groupActivity([row(2, { request_id: "" }), row(1, { request_id: "" })])).toHaveLength(2);
  });
});

describe("whoDidIt", () => {
  it("names the person and their role", () => {
    expect(whoDidIt(row(1, { actor_label: "Grace Njeri", actor_role: "accountant" }))).toBe(
      "Grace Njeri (Accountant)",
    );
  });

  it("says what the system was doing when nobody was signed in", () => {
    expect(whoDidIt(row(1, { source: "command", source_detail: "reconcile_donholm" }))).toBe(
      "Server command: reconcile_donholm",
    );
    expect(whoDidIt(row(1, { source: "bank" }))).toBe("Bank notification");
    expect(whoDidIt(row(1, { kind: "auth", object_label: "x@y.com" }))).toBe("x@y.com");
  });
});

describe("describeDevice", () => {
  it("reads the common browsers and systems", () => {
    expect(
      describeDevice(
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Mobile Safari/537.36",
      ),
    ).toBe("Chrome on Android");
    expect(
      describeDevice(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36 Edg/128.0",
      ),
    ).toBe("Edge on Windows");
    expect(describeDevice("")).toBe("");
  });
});

describe("Nairobi time", () => {
  it("shows the day and time in Nairobi, not the browser's zone", () => {
    // 22:30 UTC on the 27th is 01:30 on the 28th in Nairobi.
    expect(dayHeading("2026-09-27T22:30:00Z")).toBe("Monday, 28 September 2026");
    expect(timeOfDay("2026-09-27T22:30:00Z")).toBe("01:30");
  });
});

describe("changedFields", () => {
  it("lists only fields that have a before and an after", () => {
    const fields = changedFields(
      row(1, { old_values: { monthly_rent: "25000.00" }, new_values: { monthly_rent: "22000.00", unit_id: 4 } }),
    );
    expect(fields).toEqual([{ field: "monthly rent", before: "25000.00", after: "22000.00" }]);
  });
});
