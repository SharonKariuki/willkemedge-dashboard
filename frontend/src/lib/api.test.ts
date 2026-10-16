import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { authStorage } from "./authStorage";

/**
 * The API rotates refresh tokens and blacklists the one it was given
 * (ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION). Keeping the old refresh
 * token after a refresh meant the SECOND expiry window always failed, logging
 * every user out about 30 minutes after sign-in however active they were.
 */
describe("api token refresh", () => {
  // Access tokens the fake server currently accepts.
  let validAccess: string;

  beforeEach(() => {
    localStorage.clear();
    authStorage.setSession("access-0", "refresh-0", { id: 1, email: "a@b.c", username: "a" });
    validAccess = "access-0";

    api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
      const auth = String(config.headers?.Authorization ?? "");
      if (auth === `Bearer ${validAccess}`) {
        return { data: { ok: true }, status: 200, statusText: "OK", headers: {}, config };
      }
      throw new AxiosError("expired", "ERR_BAD_REQUEST", config, null, {
        data: {}, status: 401, statusText: "Unauthorized", headers: {}, config,
      });
    };
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps the rotated refresh token so the next refresh still works", async () => {
    // Server: a refresh token works once, then is blacklisted.
    const blacklisted = new Set<string>();
    let n = 0;
    const post = vi.spyOn(axios, "post").mockImplementation(async (_url, body) => {
      const { refresh } = body as { refresh: string };
      if (blacklisted.has(refresh)) throw new Error("Token is blacklisted");
      blacklisted.add(refresh);
      n += 1;
      validAccess = `access-${n}`;
      return { data: { access: validAccess, refresh: `refresh-${n}` } };
    });

    // First expiry window.
    validAccess = "rotated-away";
    await expect(api.get("/dashboard/summary/")).resolves.toMatchObject({ status: 200 });
    expect(authStorage.getRefresh()).toBe("refresh-1");

    // Second expiry window — failed before the fix.
    validAccess = "rotated-away-again";
    await expect(api.get("/dashboard/summary/")).resolves.toMatchObject({ status: 200 });
    expect(post).toHaveBeenLastCalledWith(
      expect.stringContaining("/auth/refresh/"),
      { refresh: "refresh-1" },
      expect.anything(),
    );
    expect(authStorage.getAccess()).toBe("access-2");
  });

  it("keeps the stored refresh token when the server does not rotate", async () => {
    vi.spyOn(axios, "post").mockImplementation(async () => {
      validAccess = "access-new";
      return { data: { access: "access-new" } };
    });

    validAccess = "rotated-away";
    await api.get("/dashboard/summary/");
    expect(authStorage.getRefresh()).toBe("refresh-0");
    expect(authStorage.getAccess()).toBe("access-new");
  });
});
