/**
 * The building's cover photo: shows the current picture (or the placeholder
 * that stands in when there is none) and lets the owner choose, change or
 * remove one. Choosing a file shrinks it in the browser; the caller decides
 * when to upload the result.
 */
import { ImagePlus, Trash2 } from "lucide-react";
import { useId, useRef, useState } from "react";
import toast from "react-hot-toast";

import { PHOTO_ACCEPT, shrinkPhoto } from "@/lib/buildingPhoto";
import { cn } from "@/lib/cn";

export function PhotoPicker({
  src, isPlaceholder, onPick, onRemove, busy = false, className,
}: {
  /** What to show: the chosen or saved photo, or the placeholder. */
  src: string;
  isPlaceholder: boolean;
  onPick: (photo: Blob) => void;
  /** Omit when there is nothing to remove. */
  onRemove?: () => void;
  busy?: boolean;
  className?: string;
}) {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [preparing, setPreparing] = useState(false);

  async function take(file: File | undefined) {
    if (!file) return;
    setPreparing(true);
    try {
      onPick(await shrinkPhoto(file));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "That photo could not be used.");
    } finally {
      setPreparing(false);
      if (input.current) input.current.value = "";
    }
  }

  const working = busy || preparing;

  return (
    <div className={cn("space-y-2", className)}>
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-content-muted">Photo</p>
      <label
        htmlFor={inputId}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); void take(e.dataTransfer.files[0]); }}
        className={cn(
          "group relative block aspect-[4/3] cursor-pointer overflow-hidden rounded-md border bg-surface-sunk",
          "focus-within:ring-2 focus-within:ring-ring",
          dragging ? "border-teal-600 ring-2 ring-teal-600/30" : "border-border",
        )}
      >
        <img src={src} alt="" className={cn("h-full w-full object-cover transition-opacity", working && "opacity-50")} />
        <div className="absolute inset-x-0 bottom-0 flex items-center gap-2 bg-gradient-to-t from-black/70 to-transparent px-3 pb-3 pt-8 text-xs text-white">
          <ImagePlus className="h-4 w-4 shrink-0" />
          <span className="font-medium">
            {working ? "Preparing photo…" : isPlaceholder ? "Add a photo" : "Change photo"}
          </span>
        </div>
        {isPlaceholder && (
          <span className="absolute left-2 top-2 rounded bg-black/55 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-white">
            Placeholder
          </span>
        )}
        <input
          ref={input}
          id={inputId}
          type="file"
          accept={PHOTO_ACCEPT}
          className="sr-only"
          disabled={working}
          onChange={(e) => void take(e.target.files?.[0])}
        />
      </label>
      <div className="flex items-start justify-between gap-2">
        <p className="text-[11px] text-content-muted">
          {isPlaceholder
            ? "Optional. Without one, a stock picture is shown."
            : "JPEG, PNG or WebP. Resized before upload."}
        </p>
        {onRemove && !isPlaceholder && (
          <button
            type="button"
            onClick={onRemove}
            disabled={working}
            className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-danger hover:bg-danger-soft disabled:opacity-50"
          >
            <Trash2 className="h-3.5 w-3.5" /> Remove
          </button>
        )}
      </div>
    </div>
  );
}
