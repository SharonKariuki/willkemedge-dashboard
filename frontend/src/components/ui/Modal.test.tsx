import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Modal } from "./Modal";

describe("Modal", () => {
  it("does not render when closed", () => {
    render(
      <Modal open={false} onClose={() => {}} title="Hidden">
        <button>Inside</button>
      </Modal>,
    );
    expect(screen.queryByText("Hidden")).not.toBeInTheDocument();
  });

  it("renders content and an accessible dialog when open", () => {
    render(
      <Modal open onClose={() => {}} title="Edit tenant">
        <button>Save</button>
      </Modal>,
    );
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("closes on Escape by default", async () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="Closable">
        <button>Save</button>
      </Modal>,
    );
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close on Escape when disabled", async () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} closeOnEscape={false} title="Sticky">
        <button>Save</button>
      </Modal>,
    );
    await userEvent.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("traps focus within the dialog when tabbing", async () => {
    const user = userEvent.setup();
    render(
      <Modal open onClose={() => {}} title="Trap">
        <button>First</button>
        <button>Last</button>
      </Modal>,
    );

    const close = screen.getByRole("button", { name: "Close" });
    const first = screen.getByRole("button", { name: "First" });
    const last = screen.getByRole("button", { name: "Last" });

    // Focus starts on the close button (first focusable).
    expect(close).toHaveFocus();

    // Shift+Tab from the first focusable wraps to the last.
    await user.tab({ shift: true });
    expect(last).toHaveFocus();

    // Tab from the last focusable wraps back to the first.
    await user.tab();
    expect(close).toHaveFocus();

    // A forward tab moves to the next control inside the dialog.
    await user.tab();
    expect(first).toHaveFocus();
  });

  it("restores focus to the trigger element on close", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Open</button>
          <Modal open={open} onClose={() => setOpen(false)} title="Restorer">
            <button>Inside</button>
          </Modal>
        </>
      );
    }

    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open" });
    opener.focus();
    await user.click(opener);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(opener).toHaveFocus();
  });
});
