// Keeps the element the user clicked at the same place on screen while the content around it
// changes: a group that opens or closes, an inline edit that opens or saves, a review that the
// package composes again after a tick.
//
// Before the change, the caller names an anchor (an element with `data-keep-anchor="<id>"`) and
// the hook stores its distance from the top of the scroll container. After each render it moves
// the container by the difference, so the anchor does not move. When the content below gets
// shorter than the scroll position needs, a spacer at the end of the content (`data-keep-spacer`)
// grows to hold the position, and it shrinks again on a later restore that needs less. The caller
// can name several anchors, best first; the first one that still exists is held (a deleted card
// gives way to its neighbour).
//
// `settle` says when to stop. "render" stops after the next restore: use it for a change that
// renders at once, such as a toggle. "send" stops after the busy flag goes on and then off: use it
// for a change that waits for the package. A wheel, touch, key press, scrollbar press, or any
// scroll that the hook did not cause also stops it, so the hook never fights the user.

import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
} from "react";
import type { RefObject } from "react";

export type Settle = "render" | "send";

interface Anchor {
  // Candidates, best first, each with its distance from the top of the container. The first
  // candidate that still exists after the change is the one held still.
  tops: [string, number][];
  settle: Settle;
  sawBusy: boolean;
  at: number;
}

export interface KeepInPlace {
  keep: (anchorId: string | readonly string[], settle?: Settle) => void;
  restore: () => void;
}

const noop: KeepInPlace = { keep: () => undefined, restore: () => undefined };

export const KeepInPlaceContext = createContext<KeepInPlace>(noop);

function escape(id: string): string {
  return typeof CSS !== "undefined" && CSS.escape
    ? CSS.escape(id)
    : id.replace(/["\\]/g, "\\$&");
}

function anchorElement(container: HTMLElement, id: string) {
  return container.querySelector<HTMLElement>(
    `[data-keep-anchor="${escape(id)}"]`,
  );
}

export function useKeepInPlace(
  containerRef: RefObject<HTMLElement | null>,
  busy: boolean,
): KeepInPlace {
  const anchor = useRef<Anchor | null>(null);
  const busyRef = useRef(busy);
  // True while a scroll event comes from a restore, so it does not release the anchor.
  const restoring = useRef(false);

  const keep = useCallback(
    (ids: string | readonly string[], settle: Settle = "render") => {
      const container = containerRef.current;
      if (!container) return;
      const origin = container.getBoundingClientRect().top;
      const tops = (typeof ids === "string" ? [ids] : ids).flatMap(
        (id): [string, number][] => {
          const element = anchorElement(container, id);
          return element
            ? [[id, element.getBoundingClientRect().top - origin]]
            : [];
        },
      );
      if (tops.length === 0) return;
      anchor.current = { tops, settle, sawBusy: false, at: Date.now() };
    },
    [containerRef],
  );

  const restore = useCallback(() => {
    const current = anchor.current;
    const container = containerRef.current;
    if (!current || !container) return;
    const found = current.tops
      .map(([id, top]) => [anchorElement(container, id), top] as const)
      .find(([element]) => element != null);
    if (found) {
      const [element, before] = found;
      const top =
        element!.getBoundingClientRect().top -
        container.getBoundingClientRect().top;
      const wanted = container.scrollTop + top - before;
      // The spacer is only as tall as this scroll position needs: it grows when the content
      // gets shorter, and it shrinks again (to nothing) when the content grows past it.
      const spacer = container.querySelector<HTMLElement>("[data-keep-spacer]");
      if (spacer) {
        const content = container.scrollHeight - spacer.offsetHeight;
        const needed = wanted + container.clientHeight - content;
        spacer.style.height = `${Math.max(0, Math.ceil(needed))}px`;
      }
      // Setting the same position fires no scroll event, so only a real move is marked.
      if (Math.abs(container.scrollTop - wanted) >= 1) {
        restoring.current = true;
        container.scrollTop = wanted;
      }
    }
    if (current.settle === "render") anchor.current = null;
    else if (busyRef.current) current.sawBusy = true;
    // A send that never started (or one that already ended) leaves no anchor behind.
    else if (current.sawBusy || Date.now() - current.at > 1000)
      anchor.current = null;
  }, [containerRef]);

  useLayoutEffect(() => {
    busyRef.current = busy;
    restore();
  });

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    // The spacer exists only to keep the anchored row still. Once the user moves the sheet,
    // shrink it to what the current scroll position needs, so no blank space stays below the
    // content.
    const trim = () => {
      const spacer = container.querySelector<HTMLElement>("[data-keep-spacer]");
      if (!spacer || spacer.offsetHeight === 0) return;
      const content = container.scrollHeight - spacer.offsetHeight;
      const needed = container.scrollTop + container.clientHeight - content;
      spacer.style.height = `${Math.max(0, Math.ceil(needed))}px`;
    };
    const release = () => {
      anchor.current = null;
      trim();
    };
    // A press on the scrollbar (outside the content box) is the user taking over.
    const press = (event: PointerEvent) => {
      if (event.offsetX >= container.clientWidth) release();
    };
    const scroll = () => {
      if (restoring.current) restoring.current = false;
      else release();
    };
    container.addEventListener("wheel", release, { passive: true });
    container.addEventListener("touchmove", release, { passive: true });
    container.addEventListener("keydown", release);
    container.addEventListener("pointerdown", press);
    container.addEventListener("scroll", scroll, { passive: true });
    return () => {
      container.removeEventListener("wheel", release);
      container.removeEventListener("touchmove", release);
      container.removeEventListener("keydown", release);
      container.removeEventListener("pointerdown", press);
      container.removeEventListener("scroll", scroll);
    };
  }, [containerRef]);

  return useMemo(() => ({ keep, restore }), [keep, restore]);
}

// For a component inside the container that re-renders on its own state: it restores the anchor
// after each of its own renders, and returns `keep` for its click handlers.
export function useKeepAnchor(): KeepInPlace["keep"] {
  const { keep, restore } = useContext(KeepInPlaceContext);
  useLayoutEffect(() => {
    restore();
  });
  return keep;
}
