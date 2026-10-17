/**
 * The reset page has to speak the backend's field name.
 *
 * It posted `{ token, password }` while PasswordResetConfirmSerializer
 * requires `new_password`, so every genuine reset link came back 400 and the
 * page blamed the link: "Reset link is invalid or has expired." Nobody could
 * complete a password reset. This pins the wire contract.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PasswordResetConfirmPage from "./PasswordResetConfirmPage";

const post = vi.fn();

vi.mock("@/lib/api", () => ({ api: { post: (...args: unknown[]) => post(...args) } }));
vi.mock("react-hot-toast", () => ({ default: { success: vi.fn(), error: vi.fn() } }));
vi.mock("react-router-dom", async () => ({
  ...(await vi.importActual<typeof import("react-router-dom")>("react-router-dom")),
  useParams: () => ({ token: "tok-abc" }),
  useNavigate: () => vi.fn(),
  Link: ({ to, children }: { to: string; children: React.ReactNode }) => <a href={to}>{children}</a>,
}));

const PASSWORD = "BrandNewPass456!x";

async function submit(user: ReturnType<typeof userEvent.setup>, password = PASSWORD) {
  const [newPw, confirmPw] = screen.getAllByDisplayValue("");
  await user.type(newPw, password);
  await user.type(confirmPw, password);
  await user.click(screen.getByRole("button", { name: /update password/i }));
}

describe("PasswordResetConfirmPage", () => {
  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({ data: { detail: "Password updated successfully." } });
  });

  it("posts new_password, the field the serializer requires", async () => {
    const user = userEvent.setup();
    render(<PasswordResetConfirmPage />);
    await submit(user);

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const [url, body] = post.mock.calls[0];
    expect(url).toBe("/auth/password-reset/confirm/");
    expect(body).toEqual({ token: "tok-abc", new_password: PASSWORD });
  });

  it("does not send the old `password` key", async () => {
    const user = userEvent.setup();
    render(<PasswordResetConfirmPage />);
    await submit(user);

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][1]).not.toHaveProperty("password");
  });

  it("carries the token from the URL", async () => {
    const user = userEvent.setup();
    render(<PasswordResetConfirmPage />);
    await submit(user);

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][1]).toMatchObject({ token: "tok-abc" });
  });

  it("refuses a password shorter than the server's 12-character floor", async () => {
    const user = userEvent.setup();
    render(<PasswordResetConfirmPage />);
    await submit(user, "Short1!");

    expect(await screen.findByText(/Password must be at least 12 characters/i)).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
  });
});
