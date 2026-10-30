// The handle between the chat and the Profile. Drag it, or focus it and use the arrow keys, to
// change the chat width. The width is a percentage of the row, so it holds when the window
// changes size, and the browser keeps it for the next visit.

import { useRef, useState, type RefObject } from "react";
import { cn } from "./ui";

const STORAGE_KEY = "metis-web:chat-width";
const DEFAULT_WIDTH = 34;
const MIN_WIDTH = 22;
const MAX_WIDTH = 60;
const KEY_STEP = 2;

const clamp = (width: number) =>
  Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(width)));

function storedWidth(): number {
  try {
    const value = Number(window.localStorage.getItem(STORAGE_KEY));
    return value ? clamp(value) : DEFAULT_WIDTH;
  } catch {
    return DEFAULT_WIDTH;
  }
}

// The chat width in percent, and a setter that keeps it in range and stores it.
export function useChatWidth(): [number, (width: number) => void] {
  const [width, setWidth] = useState(storedWidth);
  const set = (next: number) => {
    const value = clamp(next);
    setWidth(value);
    try {
      window.localStorage.setItem(STORAGE_KEY, String(value));
    } catch {
      // A browser that refuses storage still resizes for this visit.
    }
  };
  return [width, set];
}

export function PaneDivider({
  rowRef,
  width,
  onWidth,
}: {
  // The row that holds both panes. The pointer position is measured against it.
  rowRef: RefObject<HTMLElement | null>;
  width: number;
  onWidth: (width: number) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const pointer = useRef<number | null>(null);
  const widthAt = (clientX: number) => {
    const row = rowRef.current?.getBoundingClientRect();
    return row ? ((clientX - row.left) / row.width) * 100 : width;
  };
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize chat"
      aria-valuenow={width}
      aria-valuemin={MIN_WIDTH}
      aria-valuemax={MAX_WIDTH}
      tabIndex={0}
      title="Drag to resize"
      onPointerDown={(event) => {
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        pointer.current = event.pointerId;
        setDragging(true);
      }}
      onPointerMove={(event) => {
        if (pointer.current === event.pointerId)
          onWidth(widthAt(event.clientX));
      }}
      onPointerUp={(event) => {
        if (pointer.current !== event.pointerId) return;
        pointer.current = null;
        setDragging(false);
      }}
      onPointerCancel={() => {
        pointer.current = null;
        setDragging(false);
      }}
      onDoubleClick={() => onWidth(DEFAULT_WIDTH)}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") onWidth(width - KEY_STEP);
        else if (event.key === "ArrowRight") onWidth(width + KEY_STEP);
        else if (event.key === "Home") onWidth(MIN_WIDTH);
        else if (event.key === "End") onWidth(MAX_WIDTH);
        else return;
        event.preventDefault();
      }}
      className={cn(
        // A wide, invisible hit area over a one-pixel rule, so the handle is easy to catch.
        "group relative hidden w-px shrink-0 cursor-col-resize touch-none bg-border md:block",
        "before:absolute before:inset-y-0 before:-left-1.5 before:-right-1.5 before:content-['']",
        "focus-visible:outline-none",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "absolute inset-y-0 -left-px w-[3px] transition-colors",
          dragging
            ? "bg-accent"
            : "group-hover:bg-accent/60 group-focus-visible:bg-accent",
        )}
      />
    </div>
  );
}
