/**
 * The landlord's bug, at the component that caused it.
 *
 * The old field was a bare <input type="date">, which renders in the browser's
 * locale. On an en-US machine that asked for mm/dd/yyyy, so a tenancy starting
 * 1 October 2026 could not be entered as 01/10/2026 at all.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useForm } from "react-hook-form";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { DatePicker } from "@/components/ui/DatePicker";

/** The shape every page uses: react-hook-form's register(), uncontrolled. */
function RegisteredForm({
  onSubmitted, defaultDate = "",
}: { onSubmitted: (v: { when: string }) => void; defaultDate?: string }) {
  const { register, handleSubmit, reset } = useForm<{ when: string }>({
    defaultValues: { when: defaultDate },
  });
  return (
    <form onSubmit={handleSubmit(onSubmitted)}>
      <DatePicker label="When" {...register("when")} />
      <button type="submit">Save</button>
      <button type="button" onClick={() => reset({ when: "2027-03-04" })}>Reset</button>
    </form>
  );
}

const box = () => screen.getByLabelText("When");

describe("DatePicker", () => {
  it("accepts the date as the landlord typed it and submits ISO", async () => {
    const user = userEvent.setup();
    const onSubmitted = vi.fn();
    render(<RegisteredForm onSubmitted={onSubmitted} />);

    await user.type(box(), "01102026");
    expect(box()).toHaveValue("01/10/2026");

    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmitted).toHaveBeenCalledWith(
      expect.objectContaining({ when: "2026-10-01" }),
      expect.anything(),
    );
  });

  it("reads day-first, so 01/10 is October and not January", async () => {
    const user = userEvent.setup();
    const onSubmitted = vi.fn();
    render(<RegisteredForm onSubmitted={onSubmitted} />);

    await user.type(box(), "01/10/2026");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmitted.mock.calls[0][0].when).toBe("2026-10-01");
  });

  it("shows a form's default date day-first", () => {
    render(<RegisteredForm onSubmitted={vi.fn()} defaultDate="2026-10-01" />);
    expect(box()).toHaveValue("01/10/2026");
  });

  it("redraws when the form is reset under it", async () => {
    // ExpensesPage and ManualIncomePage both reset() back to today after a
    // save. Nothing dispatches a DOM event for that, so the box has to notice
    // on its own that the value it is holding has changed.
    const user = userEvent.setup();
    render(<RegisteredForm onSubmitted={vi.fn()} defaultDate="2026-10-01" />);
    expect(box()).toHaveValue("01/10/2026");

    await user.click(screen.getByRole("button", { name: "Reset" }));
    expect(box()).toHaveValue("04/03/2027");
  });

  it("holds nothing until the date is finished", async () => {
    const user = userEvent.setup();
    const onSubmitted = vi.fn();
    render(<RegisteredForm onSubmitted={onSubmitted} />);

    await user.type(box(), "01/10");
    await user.click(screen.getByRole("button", { name: "Save" }));
    // Not "2026-01-10", not a guess — a required-field check should read this
    // as "not filled in yet".
    expect(onSubmitted.mock.calls[0][0].when).toBe("");
  });

  it("works controlled too, the way BuildingsPage uses it", async () => {
    const user = userEvent.setup();
    const seen: string[] = [];
    function Controlled() {
      const [iso, setIso] = useState("2026-10-01");
      return (
        <DatePicker
          label="When"
          value={iso}
          onChange={(e) => { seen.push(e.target.value); setIso(e.target.value); }}
        />
      );
    }
    render(<Controlled />);
    expect(box()).toHaveValue("01/10/2026");

    await user.clear(box());
    await user.type(box(), "25122026");
    expect(box()).toHaveValue("25/12/2026");
    expect(seen.at(-1)).toBe("2026-12-25");
  });

  it("tells the reader what shape the date should be", () => {
    render(<RegisteredForm onSubmitted={vi.fn()} />);
    expect(box()).toHaveAttribute("placeholder", "dd/mm/yyyy");
  });

  it("shows an error message and marks the field invalid", () => {
    render(<DatePicker label="When" name="when" id="when" error="Required" />);
    expect(screen.getByText("Required")).toBeInTheDocument();
    expect(box()).toHaveAttribute("aria-invalid", "true");
  });
});

describe("DatePicker focus", () => {
  it("sends focus to the box you can actually see", async () => {
    // react-hook-form focuses the registered field when validation fails, and
    // the registered field is the invisible one holding the ISO value.
    render(<RegisteredForm onSubmitted={vi.fn()} />);
    const hidden = document.querySelector('input[type="date"]') as HTMLInputElement;

    hidden.focus();

    expect(document.activeElement).toBe(screen.getByLabelText("When"));
  });
});
