import { afterEach, describe, expect, it, vi } from "vitest";

import { askAndVoid, liveTotal } from "./voidEntry";

vi.mock("react-hot-toast", () => ({ default: { error: vi.fn(), success: vi.fn() } }));

afterEach(() => vi.restoreAllMocks());

describe("liveTotal", () => {
  it("leaves voided entries out", () => {
    expect(
      liveTotal([
        { amount: "1000.00" },
        { amount: "250.50", is_void: false },
        { amount: "9999.00", is_void: true },
      ]),
    ).toBe(1250.5);
    expect(liveTotal(undefined)).toBe(0);
  });
});

describe("askAndVoid", () => {
  it("voids with the reason given", () => {
    vi.spyOn(window, "prompt").mockReturnValue("  Entered twice ");
    const run = vi.fn().mockResolvedValue(undefined);
    askAndVoid("expense", run);
    expect(run).toHaveBeenCalledWith("Entered twice");
  });

  it("does nothing when cancelled or left blank", () => {
    const run = vi.fn();
    vi.spyOn(window, "prompt").mockReturnValueOnce(null).mockReturnValueOnce("   ");
    askAndVoid("expense", run);
    askAndVoid("expense", run);
    expect(run).not.toHaveBeenCalled();
  });
});
