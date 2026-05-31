/**
 * apiError.ts — extract a human-readable message from a failed API call.
 *
 * DRF errors arrive in a few shapes:
 *   { detail: "Not found." }
 *   { field_name: ["This field is required."] }
 *   "Plain string body"
 * This helper surfaces the most specific message it can find, falling back
 * to a calm, brand-appropriate sentence when nothing useful is present.
 */
import { AxiosError } from "axios";

type FieldErrors = Record<string, unknown>;

function firstFieldMessage(data: FieldErrors): string | null {
  for (const value of Object.values(data)) {
    if (typeof value === "string" && value.trim()) return value;
    if (Array.isArray(value)) {
      const first = value.find((v) => typeof v === "string" && v.trim());
      if (typeof first === "string") return first;
    }
  }
  return null;
}

export function getErrorMessage(err: unknown, fallback = "Something went wrong. Please try again."): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data;

    if (typeof data === "string" && data.trim()) return data;

    if (data && typeof data === "object") {
      const record = data as FieldErrors;
      const detail = record.detail;
      if (typeof detail === "string" && detail.trim()) return detail;

      const nonField = record.non_field_errors;
      if (Array.isArray(nonField) && typeof nonField[0] === "string") return nonField[0];

      const field = firstFieldMessage(record);
      if (field) return field;
    }

    if (err.code === "ECONNABORTED") {
      return "The request timed out. Please check your connection and try again.";
    }

    // An Axios error with no extractable server message: prefer the caller's
    // fallback over the generic "Request failed" axios message.
    return fallback;
  }

  if (err instanceof Error && err.message) return err.message;

  return fallback;
}
