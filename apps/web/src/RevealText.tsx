import { useEffect, useRef, useState } from "react";
import { REVEAL_INTERVAL_MS, transitionFrames } from "./reveal";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() =>
    typeof window === "undefined" || typeof window.matchMedia !== "function"
      ? false
      : window.matchMedia(REDUCED_MOTION_QUERY).matches,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(REDUCED_MOTION_QUERY);
    const update = () => setReduced(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return reduced;
}

// A string is the whole contract. The component knows nothing about the specification field, its path,
// or the element that presents it. Its first value is the baseline, so reopening a stored interview
// draws complete text; only a later value received by the same mounted component is an arrival.
export function RevealText({ value }: { value: string }) {
  const reducedMotion = usePrefersReducedMotion();
  const [displayed, setDisplayed] = useState(value);
  const displayedRef = useRef(value);
  const previousRef = useRef(value);

  useEffect(() => {
    const previous = previousRef.current;
    previousRef.current = value;

    if (reducedMotion) {
      displayedRef.current = value;
      setDisplayed(value);
      return;
    }

    const frames = transitionFrames({
      displayed: displayedRef.current,
      previous,
      next: value,
      reducedMotion: false,
    });
    if (frames.length === 0) return;

    let index = 0;
    let timer: number | undefined;
    const advance = () => {
      const frame = frames[index];
      displayedRef.current = frame;
      setDisplayed(frame);
      index += 1;
      if (index < frames.length) {
        timer = window.setTimeout(advance, REVEAL_INTERVAL_MS);
      }
    };

    timer = window.setTimeout(advance, REVEAL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [reducedMotion, value]);

  return (
    <>
      {/* The changing visual text stays out of the accessibility tree. Assistive technology gets
          the complete value once, instead of hearing the field again for every revealed word. */}
      <span aria-hidden>{displayed}</span>
      <span className="sr-only">{value}</span>
    </>
  );
}
