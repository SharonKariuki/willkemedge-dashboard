/**
 * DatePicker — a date field that reads and writes day/month/year.
 *
 * It used to be a bare `<input type="date">`. That input renders in the
 * *browser's* locale, not the page's, so on a machine set to en-US it showed
 * `mm/dd/yyyy`: the landlord trying to start a tenancy on 1 October 2026 was
 * being asked for `10/01/2026`, and typing `01-10-2026` — the way the date is
 * written everywhere else in this business — was rejected outright.
 *
 * So the box people type in is now plain text, always `dd/mm/yyyy`, and the
 * native picker is still one tap away behind the calendar button for anyone
 * who would rather pick than type.
 *
 * What leaves this component is unchanged: ISO `YYYY-MM-DD`, exactly what the
 * API stores and what the surrounding forms already compare and sort on. A
 * half-typed date emits `""`, so a required-field check reads it as "not
 * filled in yet" rather than flashing an error at someone mid-keystroke.
 *
 * Drop-in for both shapes already in use:
 *   <DatePicker {...register("move_in_date")} />        // react-hook-form
 *   <DatePicker value={iso} onChange={handleChange} />  // controlled
 */
import { Calendar } from "lucide-react";
import { forwardRef, useEffect, useId, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { fromDayFirst, maskDayFirst, toDayFirst } from "@/lib/dates";

interface DatePickerProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: string;
  error?: string;
  className?: string;
  wrapperClassName?: string;
}

export const DatePicker = forwardRef<HTMLInputElement, DatePickerProps>(
  (
    {
      label, error, className, wrapperClassName,
      value, defaultValue, onChange, onBlur, name, id,
      disabled, required, placeholder, min, max,
      ...rest
    },
    ref,
  ) => {
    // The real field: holds ISO, carries the form library's ref and name, and
    // is what the native picker writes into. Kept in the layout (rather than
    // `display:none`) because a picker cannot be opened on a box the browser
    // isn't rendering.
    const isoRef = useRef<HTMLInputElement | null>(null);
    const textInputRef = useRef<HTMLInputElement | null>(null);
    const [text, setText] = useState(() => toDayFirst(String(value ?? defaultValue ?? "")));
    const textRef = useRef(text);
    textRef.current = text;

    // One rule, deliberately on every render: if the ISO the field is holding
    // is not the date shown in the box, the box is stale and gets redrawn.
    //
    // That covers every way a value arrives from outside without an event to
    // listen for — `defaultValues` on mount, `reset()` after a save, a parent's
    // setState. It cannot fight the person typing, because a part-typed date
    // emits `""` and the field holds `""` too, so the two agree and nothing
    // moves until the date is complete.
    useEffect(() => {
      const incoming = value !== undefined
        ? String(value ?? "")
        : (isoRef.current?.value ?? "");
      if (isoRef.current && isoRef.current.value !== incoming) {
        isoRef.current.value = incoming;
      }
      if (incoming !== fromDayFirst(textRef.current)) {
        setText(toDayFirst(incoming));
      }
    });

    /** Hand the form an ISO date, shaped like the change event it expects. */
    const emit = (iso: string) => {
      if (isoRef.current) isoRef.current.value = iso;
      if (!onChange) return;
      onChange({
        type: "change",
        target: { name, id, value: iso, type: "text" },
        currentTarget: { name, id, value: iso, type: "text" },
      } as unknown as React.ChangeEvent<HTMLInputElement>);
    };

    const handleTyping = (e: React.ChangeEvent<HTMLInputElement>) => {
      const next = maskDayFirst(e.target.value);
      setText(next);
      emit(fromDayFirst(next));
    };

    /** The native picker wrote an ISO date into the real field. */
    const handlePicked = (e: React.ChangeEvent<HTMLInputElement>) => {
      const iso = e.target.value;
      setText(toDayFirst(iso));
      emit(iso);
    };

    const openPicker = () => {
      // Supported everywhere this dashboard runs, but it throws if the input
      // is disabled or the click didn't count as a user gesture — and failing
      // to open a convenience is not worth an error to someone who can simply
      // type the date instead.
      try {
        isoRef.current?.showPicker?.();
      } catch {
        textInputRef.current?.focus();
      }
    };

    // The box a person types in is a different element from the one holding
    // the value, so the label has to point at it explicitly — and it needs an
    // id of its own even when the caller supplied none.
    const generatedId = useId();
    const textId = `${id ?? name ?? generatedId}-typed`;
    const errorId = error ? `${textId}-error` : undefined;

    return (
      <div className={wrapperClassName}>
        {label && (
          <label
            htmlFor={textId}
            className="mb-1 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink-500"
          >
            {label}
          </label>
        )}
        <div className="relative">
          <button
            type="button"
            onClick={openPicker}
            disabled={disabled}
            tabIndex={-1}
            aria-label="Open calendar"
            className={cn(
              "absolute left-0 top-0 flex h-full w-9 items-center justify-center",
              "text-ink-400 transition-colors hover:text-ink-700",
              disabled ? "cursor-not-allowed" : "cursor-pointer",
            )}
          >
            <Calendar className="h-4 w-4" />
          </button>

          <input
            {...rest}
            ref={textInputRef}
            id={textId}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            placeholder={placeholder ?? "dd/mm/yyyy"}
            value={text}
            onChange={handleTyping}
            onBlur={onBlur}
            disabled={disabled}
            required={required}
            aria-invalid={error ? true : undefined}
            aria-describedby={errorId}
            className={cn(
              "w-full rounded-md bg-surface-raised hairline pl-9 pr-3 py-2.5 text-sm text-ink-900",
              "placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-sage-500/40",
              className,
            )}
          />

          {/* The value of record. Reachable by the picker, invisible to a
              reader, and skipped by the keyboard — the text box above is the
              one you tab to. */}
          <input
            ref={(node) => {
              isoRef.current = node;
              if (typeof ref === "function") ref(node);
              else if (ref) ref.current = node;
            }}
            type="date"
            name={name}
            id={id}
            // react-hook-form focuses the offending field when a submit fails
            // validation, and it knows only about this one. Landing on a 1px
            // invisible box would leave the person with a red message and no
            // idea which field it belongs to.
            onFocus={() => textInputRef.current?.focus()}
            defaultValue={String(defaultValue ?? "")}
            onChange={handlePicked}
            disabled={disabled}
            min={min}
            max={max}
            tabIndex={-1}
            aria-hidden="true"
            className="pointer-events-none absolute bottom-0 left-3 h-px w-px opacity-0"
          />
        </div>
        {error && (
          <p id={errorId} className="mt-1 text-[11px] text-status-unpaid">{error}</p>
        )}
      </div>
    );
  },
);

DatePicker.displayName = "DatePicker";
