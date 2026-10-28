import { describe, expect, it } from "vitest";

import { optionalEmail } from "./email";

describe("optionalEmail", () => {
  it("accepts a pasted address with spaces around it, trimmed", () => {
    expect(optionalEmail.parse("  jane.tenant@example.com ")).toBe("jane.tenant@example.com");
  });

  it("accepts a blank or all-space box as no email", () => {
    expect(optionalEmail.parse("")).toBe("");
    expect(optionalEmail.parse("   ")).toBe("");
    expect(optionalEmail.parse(undefined)).toBeUndefined();
  });

  it("still rejects something that is not an address", () => {
    expect(optionalEmail.safeParse("jane.tenant@example").success).toBe(false);
  });
});
