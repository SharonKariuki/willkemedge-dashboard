import { z } from "zod";

/**
 * A tenant's email: optional, and trimmed before it is checked. A space picked
 * up when pasting or from a phone keyboard made a good address fail, and on the
 * registration form that failure was not even shown.
 */
export const optionalEmail = z
  .string()
  .trim()
  .refine((v) => v === "" || z.string().email().safeParse(v).success, "Enter a valid email")
  .optional();
