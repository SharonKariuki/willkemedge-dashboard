/** The "First rent month" control shared by the register, edit and move-in-again forms. */
import type { UseFormRegisterReturn } from "react-hook-form";

import { LATE_MOVE_IN_DAY, monthAfter, monthLabel } from "./firstRentMonth";
import { Field, inputCls } from "./shared";

export function FirstRentMonthField({
  registration, moveIn, value, error, onUse,
}: {
  registration: UseFormRegisterReturn;
  /** The move-in date ("YYYY-MM-DD"), when known. */
  moveIn?: string;
  value?: string;
  error?: string;
  /** Sets the field to a month, for the late-move-in suggestion. */
  onUse: (month: string) => void;
}) {
  const moveInMonth = moveIn ? moveIn.slice(0, 7) : "";
  const lateInMonth = !!moveIn && Number(moveIn.slice(8, 10)) >= LATE_MOVE_IN_DAY;
  const next = moveIn ? monthAfter(moveIn) : "";
  const hint = value
    ? `Rent is charged from ${monthLabel(value)}.`
    : moveInMonth
      ? `Blank = ${monthLabel(moveInMonth)}, the move-in month, charged in full.`
      : "Blank = the move-in month, charged in full.";
  return (
    <div>
      <Field label="First rent month" error={error} hint={hint}>
        <input type="month" min={moveInMonth || undefined} {...registration} className={inputCls} />
      </Field>
      {lateInMonth && value !== next && (
        <p className="mt-1 text-[11px] text-ink-500">
          Moving in late in the month?{" "}
          <button
            type="button"
            className="underline underline-offset-2 hover:text-ink-900"
            onClick={() => onUse(next)}
          >
            Start rent in {monthLabel(next)}
          </button>
        </p>
      )}
    </div>
  );
}
