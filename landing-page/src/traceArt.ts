/* Hero background: a machine reading agent traces.

   A trace sits on a strict grid: it starts from one root, forks into branches that sometimes
   rejoin, and runs left to right. A thin gold scan line sweeps across it at a steady pace and
   grades each step as it passes: grey nodes are waiting, gold means the step passed, rose means
   it failed. When the sweep ends, the trace holds, fades, and the next one fades in.

   The art is half erased behind the hero text, and nodes dim there, so the text stays readable.
   It pauses while the hero is off screen, and draws one still frame when reduced motion is on. */

type Outcome = 'pass' | 'fail';
type Node = { c: number; r: number; x: number; y: number; outcome: Outcome };
type Link = { a: Node; b: Node };
type Rect = { x: number; y: number; w: number; h: number };

const COLS = 8, ROWS = 6;          // the grid
const SWEEP = 7, HOLD = 1.2, FADE = 1; // seconds: scan across, hold the graded trace, fade out
const FAIL_RATE = 0.18;
const TEXT_FADE = 0.5;             // share of the art erased behind the hero text
const COLOUR = { wait: 'rgba(140,160,166,', pass: 'rgba(229,174,79,', fail: 'rgba(196,110,128,' };
const LINE = 'rgba(124,134,214,';

/** Start the art on `canvas`; `textEls` are the hero elements to keep readable. Returns a stop function. */
export function startTraceArt(canvas: HTMLCanvasElement, textEls: () => Element[]): () => void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return () => {};
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let W = 0, H = 0, t = 0, raf = 0, last = 0, onScreen = true;
  let nodes: Node[] = [], links: Link[] = [], textRects: Rect[] = [];

  const gx = (c: number) => W * 0.05 + c * (W * 0.9) / (COLS - 1);
  const gy = (r: number) => H * 0.14 + r * (H * 0.72) / (ROWS - 1);

  // A trace on the grid: it always forks after the root, then forks often (by one or two rows,
  // up to three branches), and branches sometimes rejoin.
  const newTrace = () => {
    nodes = []; links = []; t = 0;
    type Branch = { r: number; n: Node | null };
    let active: Branch[] = [{ r: 2 + Math.floor(Math.random() * 2), n: null }];
    for (let c = 0; c < COLS; c++) {
      const next: Branch[] = [];
      for (const a of active) {
        let rows = [a.r];
        const fork = c === 1 || (c > 1 && c < COLS - 2 && active.length < 3 && Math.random() < 0.55);
        if (fork) { const s = c === 1 || Math.random() < 0.5 ? 1 : 2; rows = [Math.max(0, a.r - s), Math.min(ROWS - 1, a.r + s)]; }
        for (const r of rows) {
          let b = next.find((x) => x.r === r);
          if (!b) {
            b = { r, n: { c, r, x: 0, y: 0, outcome: Math.random() < FAIL_RATE ? 'fail' : 'pass' } };
            nodes.push(b.n!); next.push(b);
          }
          if (a.n) links.push({ a: a.n, b: b.n! });
        }
      }
      if (next.length > 1 && c > 1 && Math.random() < 0.35) { next.sort((p, q) => p.r - q.r); next[1].r = next[0].r; } // rejoin
      active = next.filter((x, i, arr) => arr.findIndex((y) => y.r === x.r) === i);
    }
    place();
  };
  const place = () => { for (const n of nodes) { n.x = gx(n.c); n.y = gy(n.r); } };

  const circle = (x: number, y: number, r: number) => { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); };
  const behindText = (x: number, y: number) => textRects.some((r) => x > r.x - 20 && x < r.x + r.w + 20 && y > r.y - 20 && y < r.y + r.h + 20);
  // A clean S-curve between grid points, leaving and arriving horizontally.
  const curve = (a: Node, b: Node, alpha: number) => {
    const mx = (a.x + b.x) / 2;
    ctx.strokeStyle = LINE + alpha + ')'; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.bezierCurveTo(mx, a.y, mx, b.y, b.x, b.y); ctx.stroke();
  };

  const refreshTextRects = () => {
    const cr = canvas.getBoundingClientRect();
    textRects = textEls().map((el) => { const r = el.getBoundingClientRect(); return { x: r.left - cr.left, y: r.top - cr.top, w: r.width, h: r.height }; });
  };
  // Erase part of the art behind the text with a soft edge: twelve stacked rectangles, each a
  // little larger and erasing a little, fade from TEXT_FADE over the text to nothing 30px out.
  const dimBehindText = () => {
    const steps = 12, grow = 2.5, each = 1 - Math.pow(1 - TEXT_FADE, 1 / steps);
    ctx.save();
    ctx.globalCompositeOperation = 'destination-out';
    ctx.fillStyle = `rgba(0,0,0,${each})`;
    for (const r of textRects) for (let i = 0; i < steps; i++) { const g = i * grow; ctx.fillRect(r.x - 6 - g, r.y - 4 - g, r.w + 12 + 2 * g, r.h + 8 + 2 * g); }
    ctx.restore();
  };

  const draw = () => {
    ctx.clearRect(0, 0, W, H);
    refreshTextRects();
    const sx = W * 0.02 + W * 0.96 * Math.min(1, t / SWEEP);           // scan line position
    const a = Math.min(1, t / 0.6) * (t > SWEEP + HOLD ? Math.max(0, 1 - (t - SWEEP - HOLD) / FADE) : 1);
    for (const l of links) curve(l.a, l.b, (l.b.x <= sx ? 0.5 : 0.18) * a); // read links brighten
    for (const n of nodes) {
      const graded = n.x <= sx, dim = behindText(n.x, n.y) ? 0.35 : 1;
      const state = graded ? n.outcome : 'wait';
      const pulse = graded ? Math.max(0, 1 - (sx - n.x) / (W * 0.96 / SWEEP) / 0.8) : 0; // ring as it is graded
      if (pulse > 0) { ctx.strokeStyle = COLOUR[state] + 0.6 * pulse * a * dim + ')'; ctx.lineWidth = 1.2; circle(n.x, n.y, 4 + 8 * (1 - pulse)); ctx.stroke(); }
      ctx.fillStyle = COLOUR[state] + (graded ? 0.9 : 0.55) * a * dim + ')';
      circle(n.x, n.y, graded ? 3.4 : 2.6); ctx.fill();
    }
    if (t < SWEEP) {
      const glow = ctx.createLinearGradient(sx - 40, 0, sx, 0);
      glow.addColorStop(0, 'rgba(229,174,79,0)'); glow.addColorStop(1, 'rgba(229,174,79,.10)');
      ctx.fillStyle = glow; ctx.fillRect(sx - 40, H * 0.06, 40, H * 0.88);
      ctx.strokeStyle = 'rgba(229,174,79,.55)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(sx, H * 0.06); ctx.lineTo(sx, H * 0.94); ctx.stroke();
      ctx.fillStyle = 'rgba(229,174,79,.8)';
      for (const y of [H * 0.06, H * 0.94]) ctx.fillRect(sx - 4, y - 1, 8, 2);
    }
    dimBehindText();
  };

  const step = (dt: number) => { t += dt; if (t > SWEEP + HOLD + FADE) newTrace(); };
  const resize = () => {
    const r = canvas.getBoundingClientRect();
    if (!r.width) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = r.width; H = r.height; canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!nodes.length) newTrace(); else place();
  };
  const frame = (ts: number) => { step(Math.min(0.05, (ts - last) / 1000 || 0)); last = ts; draw(); raf = requestAnimationFrame(frame); };
  const run = () => {
    cancelAnimationFrame(raf);
    if (reduced) { t = SWEEP; draw(); return; } // a still, fully graded trace
    if (onScreen) { last = performance.now(); raf = requestAnimationFrame(frame); }
  };

  const ro = new ResizeObserver(() => { resize(); run(); });
  ro.observe(canvas);
  const io = new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; run(); });
  io.observe(canvas);

  return () => { cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); };
}
