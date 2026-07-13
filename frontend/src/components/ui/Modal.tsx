import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import { cn } from "@/lib/cn";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  eyebrow?: string;
  size?: "sm" | "md" | "lg" | "xl";
  /** Replaces the default title/eyebrow header structure entirely. */
  header?: ReactNode;
  /** Slot rendered in the header right side, before the close button. */
  headerActions?: ReactNode;
  /** Optional footer area, typically for action buttons. */
  footer?: ReactNode;
  children: ReactNode;
  /** Disable click-outside dismissal (e.g. forms with unsaved input). */
  closeOnBackdrop?: boolean;
  /** Disable Escape-key dismissal. */
  closeOnEscape?: boolean;
  /** Override accessible label when no visible title is set. */
  ariaLabel?: string;
}

const SIZE_CLASSES: Record<NonNullable<ModalProps["size"]>, string> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-2xl",
  xl: "max-w-3xl",
};

export function Modal({
  open,
  onClose,
  title,
  eyebrow,
  size = "lg",
  header,
  headerActions,
  footer,
  children,
  closeOnBackdrop = true,
  closeOnEscape = true,
  ariaLabel,
}: ModalProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Lock scroll, move focus into the dialog, and restore focus to the
  // triggering element when the dialog closes.
  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus?.();
    };
  }, [open]);

  // Escape to close + focus trap (Tab / Shift+Tab cycles within the dialog).
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape" && closeOnEscape) {
        onClose();
        return;
      }
      if (event.key !== "Tab") return;

      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter((el) => !el.hasAttribute("disabled") && el.getAttribute("aria-hidden") !== "true");
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement | null;

      if (event.shiftKey) {
        if (active === first || !dialog.contains(active)) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last || !dialog.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, closeOnEscape, onClose]);

  if (!open) return null;

  const hasHeader = header !== undefined || title !== undefined || eyebrow !== undefined || headerActions !== undefined;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={typeof title === "string" ? title : ariaLabel}
    >
      <div
        className="absolute inset-0 bg-neutral-950/50 backdrop-blur-sm animate-fade-up"
        onClick={closeOnBackdrop ? onClose : undefined}
        aria-hidden
      />
      <div
        ref={dialogRef}
        className={cn(
          "relative flex w-full max-h-[90vh] flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-lg animate-fade-up",
          SIZE_CLASSES[size],
        )}
      >
        {hasHeader && (
          <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-border bg-surface px-6 py-5">
            {header ?? (
              <div className="min-w-0 flex-1">
                {eyebrow && (
                  <p className="text-xs font-semibold uppercase tracking-wider text-teal-700">
                    {eyebrow}
                  </p>
                )}
                {title && (
                  <p className="text-xl font-semibold leading-tight text-content">
                    {title}
                  </p>
                )}
              </div>
            )}
            <div className="flex shrink-0 items-center gap-2">
              {headerActions}
              <button
                ref={closeButtonRef}
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="rounded-md p-1.5 text-content-muted transition-colors hover:bg-hover hover:text-content focus:outline-none focus:ring-2 focus:ring-ring/40"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-6 py-6">{children}</div>

        {footer && (
          <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-end gap-2.5 border-t border-border bg-surface px-6 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
