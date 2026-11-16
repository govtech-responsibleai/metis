// The picture on the login page: traces while METIS grades them. The traces run off the
// edges of the panel. The observations to the left of the gold line have a result, and the
// ones to the right wait for theirs. It is the still form of the trace art on the landing
// page (landing-page/src/traceArt.ts).

import { useId, useLayoutEffect, useRef, useState } from "react";

type Outcome = "pass" | "fail";
type Point = { x: number; y: number; column: number; outcome: Outcome };
type Link = [Point, Point];
// One trace. `rows` are the heights that it can use, and `start` are the rows where it
// comes in from the left edge.
type Band = { rows: number[]; start: number[]; seed: number };
type Trace = { nodes: Point[]; links: Link[]; top: number; bottom: number };

// "panel" is the half of a wide window: the text is at the bottom and the trace takes the
// space above it. "banner" is the strip at the top of a phone screen: the trace fills it and
// has no labels, because the text lies on the trace.
export type LoginArtLayout = "panel" | "banner";

const WIDTH = 600;
// The height follows the shape of the panel, so no part is cut off. This is the height
// before the panel is measured.
const HEIGHT = 800;
// The first and the last column are outside the picture, so the links cross its edges.
const COLUMNS = [-50, 67, 183, 300, 417, 533, 650];
const GRADED_TO = 358;
const FAIL_RATE = 0.18;

// A trace that fills the space from `from` to `to`, with about `gap` between its rows. It
// comes in from the left edge on two rows.
function band(from: number, to: number, gap: number, seed: number): Band {
  const count = Math.max(2, Math.round((to - from) / gap));
  const rows = Array.from(
    { length: count + 1 },
    (_, row) => from + ((to - from) * row) / count,
  );
  const start = [Math.floor(count / 3), Math.ceil((2 * count) / 3)];
  return { rows, start: [...new Set(start)], seed };
}

// The traces for a panel of this height. A row at -55, or 55 under the height, is outside
// the picture, so the links cross the top or the bottom edge.
function bands(layout: LoginArtLayout, height: number): Band[] {
  if (layout === "banner") return [band(-30, height + 30, 85, 9)];
  return [band(-55, 0.56 * height, 105, 5)];
}

const FILL: Record<Outcome, string> = {
  pass: "fill-gold",
  fail: "fill-brand-fail",
};
const RING: Record<Outcome, string> = {
  pass: "stroke-gold",
  fail: "stroke-brand-fail",
};

// A small seeded generator, so the picture is the same on each visit.
function seeded(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function buildTrace(band: Band): Trace {
  const random = seeded(band.seed);
  const last = band.rows.length - 1;
  const nodes: Point[] = [];
  const links: Link[] = [];
  let active: { row: number; node: Point | null }[] = band.start.map((row) => ({
    row,
    node: null,
  }));
  COLUMNS.forEach((x, column) => {
    const next = new Map<number, Point>();
    const mayFork = column > 0 && active.length < 4;
    for (const branch of active) {
      const roll = random();
      let rows = [branch.row];
      if (column > 0 && mayFork && roll < 0.45)
        rows = [branch.row - 1, branch.row + 1];
      else if (column > 0 && roll > 0.75)
        rows = [branch.row + (random() < 0.5 ? -1 : 1)];
      for (const wanted of new Set(
        rows.map((row) => Math.min(last, Math.max(0, row))),
      )) {
        let node = next.get(wanted);
        if (!node) {
          const outcome = random() < FAIL_RATE ? "fail" : "pass";
          node = { x, y: band.rows[wanted], column, outcome };
          next.set(wanted, node);
          nodes.push(node);
        }
        if (branch.node) links.push([branch.node, node]);
      }
    }
    active = [...next].map(([row, node]) => ({ row, node }));
  });
  return {
    nodes,
    links,
    top: Math.min(...band.rows) - 50,
    bottom: Math.max(...band.rows) + 50,
  };
}

// The sweep: when the page opens, the gold line moves once from the left edge to its place
// and each observation gets its result as the line passes it. Then the picture is still.
// The classes are in globals.css.
const SWEEP_START = 0.3;
const SWEEP_SECONDS = 2.2;
const SWEEP_FROM = -60;

// When the line reaches `x`, in seconds. The line slows down as it arrives (a quadratic
// ease-out, the curve of `.login-art-line`), and this is the inverse of that curve.
function reachedAt(x: number): number {
  const share = (x - SWEEP_FROM) / (GRADED_TO - SWEEP_FROM);
  const done = Math.min(1, Math.max(0, share));
  return SWEEP_START + SWEEP_SECONDS * (1 - Math.sqrt(1 - done));
}

const appearsAt = (seconds: number) => ({
  animationDelay: `${seconds.toFixed(2)}s`,
});

const graded = (point: Point) => point.x <= GRADED_TO;
// The observations that the line passed last carry a ring.
const justGraded = (point: Point) => graded(point) && point.column === 3;

function curve([from, to]: Link): string {
  const middle = (from.x + to.x) / 2;
  return `M${from.x} ${from.y}C${middle} ${from.y} ${middle} ${to.y} ${to.x} ${to.y}`;
}

// `before` puts the bubble to the left of its observation, clear of the gold line.
type Bubble = { point: Point; label: string; dot: string; before?: boolean };

// The legend. "Pass" and "Fail" go on the observations that the line passed last, the ones
// with a ring. "Not graded" goes on an observation that waits.
function bubbles(traces: Trace[], height: number): Bubble[] {
  const inView = (column: number) =>
    traces
      .flatMap((trace) => trace.nodes)
      .filter(
        (node) => node.column === column && node.y > 70 && node.y < height - 12,
      );
  const [fail, pass] = inView(3);
  const wait = inView(4).at(-1);
  const found: Bubble[] = [];
  if (fail) {
    fail.outcome = "fail";
    found.push({
      point: fail,
      label: "Fail",
      dot: "fill-brand-fail",
      before: true,
    });
  }
  if (pass) {
    pass.outcome = "pass";
    found.push({
      point: pass,
      label: "Pass",
      dot: "fill-gold",
      before: true,
    });
  }
  if (wait)
    found.push({ point: wait, label: "Not graded", dot: "fill-brand-wait" });
  return found;
}

// `size` is the text size in the units of the picture. The bubble takes all its measures
// from it, so the label stays readable when the panel is narrow.
function BubbleMark({
  point,
  label,
  dot,
  before = false,
  size,
}: Bubble & { size: number }) {
  const width = label.length * 0.56 * size + 2.5 * size;
  const high = 2 * size;
  const left = before ? point.x + size - width : point.x - size;
  const top = point.y - high - 18;
  return (
    <g
      className="login-art-show"
      style={appearsAt(
        before ? reachedAt(point.x) + 0.15 : SWEEP_START + SWEEP_SECONDS + 0.1,
      )}
    >
      <rect
        x={left}
        y={top}
        width={width}
        height={high}
        rx="8"
        className="fill-brand-navy stroke-white/20"
      />
      <circle
        cx={left + size}
        cy={top + size}
        r={size * 0.27}
        className={dot}
      />
      <text
        x={left + size * 1.75}
        y={top + size * 1.35}
        fontSize={size}
        fontWeight="500"
        className="fill-brand-paper"
      >
        {label}
      </text>
    </g>
  );
}

export function LoginArt({
  layout,
  className,
}: {
  layout: LoginArtLayout;
  className?: string;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [height, setHeight] = useState(HEIGHT);
  // The label text is 15 units, and more when the panel is narrow, so it is never under
  // 12px on the screen.
  const [textSize, setTextSize] = useState(15);
  useLayoutEffect(() => {
    const element = svg.current;
    if (!element) return;
    const measure = () => {
      const { width: wide, height: high } = element.getBoundingClientRect();
      if (wide <= 0 || high <= 0) return;
      setHeight(Math.round((WIDTH * high) / wide));
      setTextSize(Math.max(15, Math.round((12.5 * WIDTH) / wide)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const traces = bands(layout, height).map(buildTrace);
  const legend = layout === "banner" ? [] : bubbles(traces, height);
  // Two pictures can be on the page at one time, so each one names its own gradient.
  const sweep = useId();
  return (
    <svg
      ref={svg}
      viewBox={`0 0 ${WIDTH} ${height}`}
      className={className}
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={sweep} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="hsl(var(--gold))" stopOpacity="0" />
          <stop offset="1" stopColor="hsl(var(--gold))" stopOpacity="0.12" />
        </linearGradient>
      </defs>
      {traces.map((trace, index) => (
        <g key={index}>
          {trace.links.map((link, at) => (
            <g key={at}>
              <path
                d={curve(link)}
                strokeWidth="1.8"
                className="stroke-brand-link/25"
              />
              {graded(link[1]) && (
                <path
                  d={curve(link)}
                  strokeWidth="1.8"
                  className="login-art-show stroke-brand-link/50"
                  style={appearsAt(reachedAt(link[1].x))}
                />
              )}
            </g>
          ))}
          <g className="login-art-line">
            <rect
              x={GRADED_TO - 48}
              y={trace.top}
              width="48"
              height={trace.bottom - trace.top}
              fill={`url(#${sweep})`}
            />
            <path
              d={`M${GRADED_TO} ${trace.top}V${trace.bottom}M${GRADED_TO - 5} ${trace.top}h10M${GRADED_TO - 5} ${trace.bottom}h10`}
              strokeWidth="1.8"
              className="stroke-gold/70"
            />
          </g>
          {trace.nodes.map((point, at) => (
            <g key={at}>
              <circle
                cx={point.x}
                cy={point.y}
                r="4.5"
                className="fill-brand-wait/70"
              />
              {graded(point) && (
                <>
                  <circle
                    cx={point.x}
                    cy={point.y}
                    r="13"
                    strokeWidth="1.2"
                    className={`${RING[point.outcome]} ${justGraded(point) ? "login-art-ring-stay" : "login-art-ring"}`}
                    style={appearsAt(reachedAt(point.x))}
                  />
                  <circle
                    cx={point.x}
                    cy={point.y}
                    r="6"
                    className={`login-art-show ${FILL[point.outcome]}`}
                    style={appearsAt(reachedAt(point.x))}
                  />
                </>
              )}
            </g>
          ))}
        </g>
      ))}
      {legend.map((bubble) => (
        <BubbleMark key={bubble.label} {...bubble} size={textSize} />
      ))}
    </svg>
  );
}
