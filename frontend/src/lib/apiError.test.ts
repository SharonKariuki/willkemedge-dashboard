import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";

import { getErrorMessage } from "./apiError";

function axiosErrorWith(data: unknown, code?: string): AxiosError {
  const err = new AxiosError("Request failed", code);
  err.response = {
    data,
    status: 400,
    statusText: "Bad Request",
    headers: {},
    config: { headers: new AxiosHeaders() },
  };
  return err;
}

describe("getErrorMessage", () => {
  it("returns the DRF detail message", () => {
    const err = axiosErrorWith({ detail: "This unit is not vacant." });
    expect(getErrorMessage(err)).toBe("This unit is not vacant.");
  });

  it("returns the first non_field_errors entry", () => {
    const err = axiosErrorWith({ non_field_errors: ["Unique constraint violated."] });
    expect(getErrorMessage(err)).toBe("Unique constraint violated.");
  });

  it("returns the first field error message", () => {
    const err = axiosErrorWith({ monthly_rent: ["A valid number is required."] });
    expect(getErrorMessage(err)).toBe("A valid number is required.");
  });

  it("returns a plain string body", () => {
    const err = axiosErrorWith("Service unavailable");
    expect(getErrorMessage(err)).toBe("Service unavailable");
  });

  it("returns a timeout message when the request aborts", () => {
    const err = axiosErrorWith(undefined, "ECONNABORTED");
    expect(getErrorMessage(err)).toMatch(/timed out/i);
  });

  it("falls back when nothing useful is present", () => {
    const err = axiosErrorWith({});
    expect(getErrorMessage(err, "Custom fallback")).toBe("Custom fallback");
  });

  it("uses the message of a plain Error", () => {
    expect(getErrorMessage(new Error("Boom"))).toBe("Boom");
  });

  it("uses the fallback for unknown values", () => {
    expect(getErrorMessage(null, "Default")).toBe("Default");
  });
});
