import { useCallback, useEffect, useRef, useState } from 'react';
import { startTraceArt } from './traceArt';

/* ── Icons ── */
const Arrow = () => <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h11M11 6l4 4-4 4" /></svg>;
const Check = () => <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 10 3 3 7-7" /></svg>;
const Github = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.7a9.5 9.5 0 0 0-3 18.5c.5.1.7-.2.7-.5v-1.9c-2.8.6-3.4-1.2-3.4-1.2-.5-1.2-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 0 1.6 1 1.6 1 .9 1.6 2.4 1.1 2.9.9.1-.7.4-1.1.7-1.3-2.2-.3-4.6-1.1-4.6-4.7 0-1 .4-1.9 1-2.6-.1-.3-.4-1.3.1-2.6 0 0 .8-.3 2.6 1a9 9 0 0 1 4.8 0c1.8-1.3 2.6-1 2.6-1 .5 1.3.2 2.3.1 2.6.6.7 1 1.6 1 2.6 0 3.7-2.3 4.5-4.6 4.7.4.3.7 1 .7 1.9v2.8c0 .3.2.6.7.5A9.5 9.5 0 0 0 12 2.7Z" /></svg>;
const FileDoc = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6" /><path d="M8 13h8M8 17h5" /></svg>;
const TraceNodes = () => <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="4" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="12" cy="20" r="2" /><path d="M12 6v4M12 14v4" /></svg>;
const Verdict = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 12l2 2 4-4" /><circle cx="12" cy="12" r="10" /></svg>;
const Xmark = () => <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m6 6 8 8M14 6l-8 8" /></svg>;
const Spinner = () => <svg className="wt-spin" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 0 1 10 10" /></svg>;

const GITHUB_URL = 'https://github.com/govtech-responsibleai/metis';
const DOCS_URL = 'https://govtech-responsibleai.github.io/metis/docs/';
const asset = (path: string) => `${import.meta.env.BASE_URL}${path}`;
const FULL_NAME = 'Measurement and Evaluation of Trustworthy Intelligent Systems';
const INSTALL_CMD = 'git clone https://github.com/govtech-responsibleai/metis.git && cd metis && make install';
const IC_WIZARD = 'https://img.icons8.com/?size=100&id=36868&format=png&color=9B7520';
const IC_USER = 'https://img.icons8.com/?size=100&id=23264&format=png&color=5C6569';
const IC_BOT_ROSE = 'https://img.icons8.com/?size=100&id=lUk2otclIHsF&format=png&color=AB596A';
const IC_BOT_BLUE = 'https://img.icons8.com/?size=100&id=lUk2otclIHsF&format=png&color=3C468B';

const RestartIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 2v6h-6" /><path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
    <path d="M3 22v-6h6" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
  </svg>
);

/* ── Data ── */
const steps = [
  { number: '01', label: 'DEFINE', product: 'Wizard', title: 'Start with what good looks like.', text: 'The Wizard interviews your team and turns a description of your agent into a Specification of features, behaviours, and measurable criteria.' },
  { number: '02', label: 'DESIGN', product: 'Wizard · Library', title: 'Turn expected behaviours into realistic tests.', text: 'Generate personas, everyday and edge-case scenarios, and repeated trials. Each criterion is matched to the grader that measures it.' },
  { number: '03', label: 'EXECUTE', product: 'Engine', title: 'Test the full trajectory.', text: 'The Engine runs adaptive, multi-turn conversations through your API or a real browser, scoring every step, tool call, and recovery.' },
  { number: '04', label: 'IMPROVE', product: 'Insights', title: 'Know exactly what to fix.', text: 'Insights rolls scores up through your specification, so you see how behaviours perform across personas, scenarios, and trials.' },
];

type WizMsg = { role: 'wizard' | 'user'; text: string; files?: string[]; specLines?: number };
const wizMsgs: WizMsg[] = [
  { role: 'wizard', text: "Tell me about your target: what it does and who it's for." },
  { role: 'user', text: "We've built an AI agent for staff. It searches knowledge bases, drafts replies, and manages documents.", files: ['PRD.pdf', 'User Research.docx', 'Policies.pdf'], specLines: 2 },
  { role: 'wizard', text: "I've read your documents. The assistant handles enterprise search, email drafting, and document management. What should happen when a user asks for information from a restricted source?", specLines: 6 },
  { role: 'user', text: "It should only search authorised sources and tell the user if it can't access something." },
  { role: 'wizard', text: "I'll set that as acceptance criteria: Factual Accuracy, Evidence Source Suitability, and Claim Support by Evidence.", specLines: 11 },
  { role: 'user', text: "What about the drafting side — how do we know the replies are correct?" },
  { role: 'wizard', text: "I'll add a second behaviour for drafting with Output Correctness, Input Interpretation Accuracy, and Capability Limits Handling. Now let me generate test cases.", specLines: 16 },
  { role: 'wizard', text: "I've created three personas and two scenarios. Each test case pairs a persona with a scenario and runs multiple trials.", specLines: 24 },
];

const specLines = [
  'target:', '  name: Target AI Agent', '',
  'features:', '  - name: Enterprise Search and Knowledge Retrieval',
  '    behaviours:',
  '      - name: Find and use enterprise information',
  '        criteria:', '          - Factual Accuracy', '          - Evidence Source Suitability',
  '          - Claim Support by Evidence',
  '      - name: Draft and verify responses',
  '        criteria:', '          - Output Correctness', '          - Input Interpretation Accuracy',
  '          - Capability Limits Handling', '',
  'personas:', '  - collaborative knowledge worker',
  '  - focused questioner', '  - policy seeker',
  'scenarios:', '  - Draft a reply using a past event record',
  '  - Retrieve policy details across sources',
];

const engMsgs = [
  { role: 'user' as const, text: "I need to reply to Priya's thread about the team offsite. Can you check what we decided last year?" },
  { role: 'assistant' as const, text: "Last year's offsite deck shows the team chose Sentosa with 40 attendees and an $18,000 budget. The venue was booked 10 weeks in advance." },
  { role: 'user' as const, text: "Great, draft a reply suggesting we start booking earlier this time." },
  { role: 'assistant' as const, text: "Hi Priya, thanks for kicking this off. Last year we booked Sentosa 10 weeks ahead and the best rooms were already gone. Could we aim for 14 weeks this time?" },
  { role: 'user' as const, text: "Make it shorter." },
  { role: 'assistant' as const, text: "Hi Priya, last year we booked 10 weeks out and lost the best rooms. Can we try 14 weeks this time?" },
];

const traceSpans = [
  { type: 'TRACE', name: 'Trial 1 — TC-001 × knowledge-worker', ms: 35000, depth: 0 },
  { type: 'AGENT', name: 'search_agent', ms: 14500, depth: 1 },
  { type: 'TOOL', name: 'search_knowledge_base("offsite")', ms: 3100, depth: 2 },
  { type: 'TOOL', name: 'read_document("offsite_deck_2025")', ms: 2400, depth: 2 },
  { type: 'AGENT', name: 'drafting_agent', ms: 10200, depth: 1 },
  { type: 'TOOL', name: 'compose_email("re: Offsite planning")', ms: 4200, depth: 2 },
  { type: 'TOOL', name: 'check_policy("travel_policy")', ms: 1800, depth: 2 },
  { type: 'AGENT', name: 'synthesis_agent', ms: 8500, depth: 1 },
  { type: 'LLM', name: 'gpt-4o · Draft reply', ms: 6200, tokens: 410, depth: 2 },
];

const engStepMap = [
  { chat: [0], trace: [0, 1] }, { chat: [], trace: [2] },
  { chat: [1], trace: [3] }, { chat: [2], trace: [4] },
  { chat: [], trace: [5] }, { chat: [3], trace: [6] },
  { chat: [4], trace: [7] }, { chat: [5], trace: [8] },
];

/* Evaluation pipeline — grader names from taxonomy_v8.csv measure dimension */
const pipelineCriteria = [
  { id: 'Factual Accuracy', grader: 'FactualAccuracyGrader', score: 0.30, threshold: 0.70, reason: 'The agent response states 40 attendees. The source document says 42.' },
  { id: 'Evidence Source Suitability', grader: 'EvidenceSourceGrader', score: 0.67, threshold: 0.70, reason: 'Retrieved the correct offsite deck, but also cited the 2023 policy which has been replaced.' },
  { id: 'Claim Support by Evidence', grader: 'ClaimSupportGrader', score: 0.90, threshold: 0.70, reason: 'The reply references the planning deck and the thread. Claims are traceable to sources.' },
];

/* Captured trace as a call graph: the orchestrator branches to two subagents, each branch loops once,
   and both branches join in the reply. Icon paths are from Lucide (lucide.dev, ISC licence). */
const LUCIDE: Record<string, React.ReactNode> = {
  user: <><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></>,
  bot: <><path d="M12 8V4H8" /><rect width="16" height="12" x="4" y="8" rx="2" /><path d="M2 14h2M20 14h2M15 13v2M9 13v2" /></>,
  search: <><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></>,
  database: <><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5V19A9 3 0 0 0 21 19V5" /><path d="M3 12A9 3 0 0 0 21 12" /></>,
  file: <><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v4a2 2 0 0 0 2 2h4" /><path d="M10 9H8M16 13H8M16 17H8" /></>,
  pen: <><path d="M12 20h9" /><path d="M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z" /></>,
  merge: <><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M6 21V9a9 9 0 0 0 9 9" /></>,
  mail: <><path d="m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7" /><rect x="2" y="4" width="20" height="16" rx="2" /></>,
  shield: <><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" /><path d="m9 12 2 2 4-4" /></>,
  send: <><path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z" /><path d="m21.854 2.147-10.94 10.939" /></>,
};
const G_W = 1120, G_H = 26;
type GraphNode = { id: string; label: string; kind: 'persona' | 'agent' | 'tool' | 'output'; icon: keyof typeof LUCIDE; col: number; y: number };
const graphNodes: GraphNode[] = [
  { id: 'user', label: 'Simulated user', kind: 'persona', icon: 'user', col: 0, y: 72 },
  { id: 'orch', label: 'orchestrator', kind: 'agent', icon: 'bot', col: 1, y: 72 },
  { id: 'search', label: 'search_agent', kind: 'agent', icon: 'search', col: 2, y: 40 },
  { id: 'draft', label: 'drafting_agent', kind: 'agent', icon: 'pen', col: 2, y: 104 },
  { id: 'kb', label: 'search_knowledge_base', kind: 'tool', icon: 'database', col: 3, y: 40 },
  { id: 'doc', label: 'read_document', kind: 'tool', icon: 'file', col: 3, y: 72 },
  { id: 'email', label: 'compose_email', kind: 'tool', icon: 'mail', col: 3, y: 104 },
  { id: 'sum', label: 'synthesis_agent', kind: 'agent', icon: 'merge', col: 4, y: 56 },
  { id: 'policy', label: 'check_policy', kind: 'tool', icon: 'shield', col: 4, y: 104 },
  { id: 'reply', label: 'Reply', kind: 'output', icon: 'send', col: 5, y: 80 },
];
/* Pill width from the label length: 12px Inter for plain words, 12px mono for code names. */
const gSans = (nd: GraphNode) => nd.kind === 'persona' || nd.kind === 'output';
const gw = (nd: GraphNode) => Math.round(32 + nd.label.length * (gSans(nd) ? 6.8 : 7.25));
/* Columns spread across the full width, with equal gaps between the widest pill of each column. */
const gColW = graphNodes.reduce<number[]>((w, nd) => { w[nd.col] = Math.max(w[nd.col] ?? 0, gw(nd)); return w; }, []);
const gGap = (G_W - gColW.reduce((t, w) => t + w, 0)) / (gColW.length - 1);
const gColX = gColW.map((_, c) => gColW.slice(0, c).reduce((t, w) => t + w + gGap, 0));
const gx = (nd: GraphNode) => gColX[nd.col];
const gNode = (id: string) => graphNodes.find((nd) => nd.id === id)!;
const gEdge = (from: string, to: string) => {
  const a = gNode(from), b = gNode(to);
  const x1 = gx(a) + gw(a), x2 = gx(b) - 3, mx = (x1 + x2) / 2;
  return a.y === b.y ? `M${x1},${a.y} L${x2},${b.y}` : `M${x1},${a.y} C${mx},${a.y} ${mx},${b.y} ${x2},${b.y}`;
};
const gMid = (id: string) => gx(gNode(id)) + gw(gNode(id)) / 2;
type GraphEdge = { d: string; loop?: boolean };
/* A loop arcs from one node back to an earlier one, above or below the row. */
const gLoop = (from: string, to: string, side: 1 | -1): GraphEdge => {
  const x1 = gMid(from), x2 = gMid(to), y = gNode(from).y + side * G_H / 2, peak = y + side * 20;
  return { d: `M${x1},${y} C${x1},${peak} ${x2},${peak} ${x2},${y + side * 3}`, loop: true };
};
const graphEdges: GraphEdge[] = [
  ...[['user', 'orch'], ['orch', 'search'], ['orch', 'draft'], ['search', 'kb'], ['search', 'doc'], ['draft', 'email'],
    ['kb', 'sum'], ['doc', 'sum'], ['email', 'policy'], ['sum', 'reply'], ['policy', 'reply']].map(([from, to]) => ({ d: gEdge(from, to) })),
  /* The search subagent reads the results and searches again. */
  gLoop('kb', 'search', -1),
  /* A failed policy check sends the draft back to compose_email. */
  gLoop('policy', 'email', 1),
];
/* The trace nodes each criterion's grader read its evidence from, by pipelineCriteria index. */
const graphEvidence = [['kb', 'sum', 'reply'], ['search', 'kb', 'doc'], ['draft', 'email', 'policy']];
/* usePipeline finishes the graders in this order. */
const GRADE_ORDER = [2, 1, 0];

const insightTree = [
  { depth: 0, label: 'Target AI Agent', value: 80, pass: true },
  { depth: 1, label: 'Search & Knowledge Retrieval', value: 70, pass: true },
  { depth: 2, label: 'Find and use enterprise info', value: 70, pass: true },
  { depth: 3, label: 'Factual Accuracy', value: 50, pass: false },
  { depth: 3, label: 'Evidence Source Suitability', value: 67, pass: false },
  { depth: 3, label: 'Claim Support by Evidence', value: 92, pass: true },
  { depth: 2, label: 'Draft and verify responses', value: 89, pass: true },
  { depth: 3, label: 'Output Correctness', value: 80, pass: true },
  { depth: 3, label: 'Input Interpretation Accuracy', value: 88, pass: true },
  { depth: 3, label: 'Capability Limits Handling', value: 100, pass: true },
];

const insightBars = [
  { label: 'Factual Accuracy', pct: 50, threshold: 75, passed: 2, total: 4 },
  { label: 'Evidence Source Suitability', pct: 67, threshold: 80, passed: 2, total: 3 },
  { label: 'Claim Support by Evidence', pct: 92, threshold: 85, passed: 4, total: 4 },
  { label: 'Output Correctness', pct: 80, threshold: 70, passed: 3, total: 4 },
  { label: 'Input Interpretation Accuracy', pct: 88, threshold: 80, passed: 4, total: 4 },
  { label: 'Capability Limits Handling', pct: 100, threshold: 90, passed: 4, total: 4 },
];

/* ── Hooks ── */
const noMotion = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function useSequence(total: number, active: boolean, ms: number) {
  const [n, setN] = useState(() => noMotion() ? total : 0);
  useEffect(() => {
    if (noMotion()) { setN(total); return; }
    if (!active || n >= total) return;
    const delay = n === 0 ? Math.min(300, ms) : ms;
    const t = setTimeout(() => setN((v) => v >= total ? v : v + 1), delay);
    return () => clearTimeout(t);
  }, [active, n, total, ms]);
  const replay = useCallback(() => setN(0), []);
  return { n, done: n >= total, replay };
}

function useTimer(active: boolean, max = 72) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (noMotion()) { setTick(max); return; }
    if (!active || tick >= max) return;
    const t = setInterval(() => setTick((v) => v >= max ? (clearInterval(t), v) : v + 1), 500);
    return () => clearInterval(t);
  }, [active, tick, max]);
  const replay = useCallback(() => setTick(0), []);
  const simSec = tick * 5;
  return { tick, simSec, mm: pad2(Math.floor(simSec / 60)), ss: pad2(simSec % 60), replay };
}
const pad2 = (n: number) => String(n).padStart(2, '0');

/* Keep the newest shown message in view inside a height-capped chat. Scrolls only the chat,
   never the page. `key` changes whenever another message appears. */
function useFollowLatest(ref: React.RefObject<HTMLDivElement | null>, key: unknown) {
  // Fade the top edge once earlier messages are scrolled out of view.
  useEffect(() => {
    const box = ref.current;
    if (!box) return;
    const onScroll = () => box.classList.toggle('scrolled', box.scrollTop > 4);
    box.addEventListener('scroll', onScroll, { passive: true });
    return () => box.removeEventListener('scroll', onScroll);
  }, [ref]);

  useEffect(() => {
    const box = ref.current;
    if (!box || box.scrollHeight <= box.clientHeight) return;
    const shown = box.querySelectorAll<HTMLElement>('.wt-msg.show');
    const last = shown[shown.length - 1];
    if (!last) return;
    const top = Math.max(0, last.offsetTop + last.offsetHeight - box.clientHeight + 8);
    box.scrollTo({ top, behavior: noMotion() ? 'auto' : 'smooth' });
  }, [ref, key]);
}

/* Pipeline: 0=idle, 1=interaction, 2=trace, 3=grading, 4=done */
function usePipeline(active: boolean) {
  const [phase, setPhase] = useState(() => noMotion() ? 4 : 0);
  const [gradersDone, setGradersDone] = useState<Set<number>>(() => noMotion() ? new Set([0, 1, 2]) : new Set());
  const [run, setRun] = useState(0);

  useEffect(() => {
    if (noMotion()) { setPhase(4); setGradersDone(new Set([0, 1, 2])); return; }
    if (!active) return;
    const ts = [
      setTimeout(() => setPhase(1), 100),
      setTimeout(() => setPhase(2), 1200),
      setTimeout(() => setPhase(3), 2200),
      setTimeout(() => setGradersDone(new Set([2])), 3200),
      setTimeout(() => setGradersDone(new Set([1, 2])), 3700),
      setTimeout(() => setGradersDone(new Set([0, 1, 2])), 4200),
      setTimeout(() => setPhase(4), 4800),
    ];
    return () => ts.forEach(clearTimeout);
  }, [active, run]);

  const replay = useCallback(() => {
    setPhase(0);
    setGradersDone(new Set());
    setRun((r) => r + 1);
  }, []);

  return { phase, gradersDone, replay };
}

/* ── Hero background ── */
function HeroArt() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    return startTraceArt(ref.current, () => [...document.querySelectorAll('.hero h1, .hero-lede, .hero-actions, .hero-credit')]);
  }, []);
  return <canvas ref={ref} className="hero-art" aria-hidden="true" />;
}

/* ── Hero card stack ── */
const productShots = [
  { src: asset('product/wizard-mainpage.png'), label: 'Wizard · Home', alt: 'METIS Wizard web app: the home page with a large METIS wordmark' },
  { src: asset('product/wizard-scenarios.webp'), label: 'Wizard · Scenarios', alt: 'METIS Wizard web app: scenarios and the test cases selected to run' },
  { src: asset('product/engine-tui.webp'), label: 'Engine · Terminal', alt: 'METIS Engine terminal dashboard simulating three scenarios in parallel' },
  { src: asset('product/insights-dashboard.webp'), label: 'Insights · Results', alt: 'METIS Insights report: specification results tree with a selected criterion' },
  { src: asset('product/insights-detail.webp'), label: 'Insights · Trials', alt: 'METIS Insights report: pass rates per criterion and the trial-by-criterion grid' },
];
const STACK_DEPTH = 3;

function HeroStack() {
  const [front, setFront] = useState(0);
  const [paused, setPaused] = useState(false);
  const n = productShots.length;

  useEffect(() => {
    if (paused || noMotion()) return;
    const t = setInterval(() => setFront((i) => (i + 1) % n), 4000);
    return () => clearInterval(t);
  }, [paused, n]);

  return (
    <div className="hero-stack" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
      <div className="stack-cards">
        {productShots.map((shot, i) => {
          const depth = (i - front + n) % n;
          return (
            <figure key={shot.src} className={`stack-card depth-${depth < STACK_DEPTH ? depth : 'hidden'}`} aria-hidden={depth !== 0}
              style={{ zIndex: n - depth }}>
              <span className="stack-chip">{shot.label}</span>
              <img src={shot.src} alt={shot.alt} loading={i < 2 ? 'eager' : 'lazy'} />
            </figure>
          );
        })}
      </div>
      <div className="stack-nav">
        <div className="stack-dots" role="group" aria-label="Product screenshots">
          {productShots.map((shot, i) => (
            <button key={shot.src} type="button" aria-pressed={i === front} aria-label={shot.label} onClick={() => setFront(i)} />
          ))}
        </div>
        <span className="stack-label">{productShots[front].label}</span>
      </div>
      <span className="sr-only" aria-live="polite">{productShots[front].label}</span>
    </div>
  );
}

/* ── Install command ── */
function CopyCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  const codeRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(t);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
    } catch {
      // Without clipboard access, select the text and try the older copy command; if that
      // fails too, the selection stays so the user can copy it themselves.
      const range = document.createRange();
      if (codeRef.current) range.selectNodeContents(codeRef.current);
      window.getSelection()?.removeAllRanges();
      window.getSelection()?.addRange(range);
      if (document.execCommand('copy')) setCopied(true);
    }
  };

  return (
    <div className="cta-install">
      <div className="cta-install-head"><span>Quickstart</span>
        <button type="button" onClick={copy}>{copied ? <><Check /> Copied</> : 'Copy'}</button>
      </div>
      <pre><span aria-hidden="true">$ </span><code ref={codeRef}>{command}</code></pre>
    </div>
  );
}

/* ── App ── */
export default function App() {
  // `seen`: a stage has peeked into view and fades in. `vis`: it reached mid-screen and animates.
  const [seen, setSeen] = useState<Set<number>>(() => new Set());
  const [vis, setVis] = useState<Set<number>>(() => new Set());
  const refs = useRef<(HTMLDivElement | null)[]>([null, null, null, null]);

  // Wizard
  const [wizPhase, setWizPhase] = useState<'idle' | 'prompt' | 'files' | 'thinking' | 'chat' | 'done'>(() => noMotion() ? 'done' : 'idle');
  const wizStarted = useRef(false);
  const wizTimers = useRef<number[]>([]);
  const wizChat = useSequence(wizMsgs.length - 2, wizPhase === 'chat' || wizPhase === 'done', 1500);
  const wizChatRef = useRef<HTMLDivElement>(null);
  const engChatRef = useRef<HTMLDivElement>(null);

  // Engine
  const engStep = useSequence(engStepMap.length, vis.has(1), 1200);
  const engTimer = useTimer(vis.has(1));

  // Pipeline (new Stage 3)
  const pipeline = usePipeline(vis.has(2));
  // While grading, the graph highlights the evidence of the grader that finished last.
  // After that, hovering a grader card highlights its evidence.
  const [graphHover, setGraphHover] = useState<number | null>(null);
  const lastGraded = pipeline.phase === 3 ? GRADE_ORDER.filter((i) => pipeline.gradersDone.has(i)).at(-1) ?? null : null;
  const graphActive = graphHover ?? lastGraded;
  const graphActivePass = graphActive !== null && pipelineCriteria[graphActive].score >= pipelineCriteria[graphActive].threshold;

  // Insights
  const insVisible = vis.has(3);
  const [insPhase, setInsPhase] = useState(() => noMotion() ? 3 : 0);
  const [jiggled, setJiggled] = useState<Set<number>>(() => new Set());
  const [insRun, setInsRun] = useState(0);

  useEffect(() => {
    const els = refs.current.filter(Boolean) as HTMLDivElement[];
    const obs = new IntersectionObserver(
      (entries) => setVis((prev) => {
        const next = new Set(prev);
        for (const e of entries) { const i = els.indexOf(e.target as HTMLDivElement); if (i >= 0 && e.isIntersecting) next.add(i); }
        return next;
      }),
      // A stage starts only once its top passes into the upper 45% of the screen, where the
      // reader is looking, so the next stage stays idle while they watch the one above it.
      { rootMargin: '0px 0px -55% 0px' },
    );
    const peek = new IntersectionObserver(
      (entries) => setSeen((prev) => {
        const next = new Set(prev);
        for (const e of entries) { const i = els.indexOf(e.target as HTMLDivElement); if (i >= 0 && e.isIntersecting) next.add(i); }
        return next;
      }),
      { threshold: 0.05 },
    );
    els.forEach((el) => { obs.observe(el); peek.observe(el); });
    // A short last stage may never reach the middle band, so reaching the page end starts all.
    const onScroll = () => {
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
        setVis(new Set(els.map((_, i) => i)));
        window.removeEventListener('scroll', onScroll);
      }
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => { obs.disconnect(); peek.disconnect(); window.removeEventListener('scroll', onScroll); };
  }, []);

  // Wizard phases
  const startWizard = useCallback(() => {
    wizTimers.current.forEach(clearTimeout);
    wizTimers.current = [];
    setWizPhase('prompt');
    wizTimers.current.push(
      window.setTimeout(() => setWizPhase('files'), 1500),
      window.setTimeout(() => setWizPhase('thinking'), 2200),
      window.setTimeout(() => setWizPhase('chat'), 4000),
    );
  }, []);

  useEffect(() => {
    if (noMotion()) { setWizPhase('done'); return; }
    if (vis.has(0) && !wizStarted.current) { wizStarted.current = true; startWizard(); }
  }, [vis, startWizard]);

  useEffect(() => () => wizTimers.current.forEach(clearTimeout), []);

  // Insights
  useEffect(() => {
    if (noMotion()) { setInsPhase(3); return; }
    if (!insVisible) return;
    const ts = [
      setTimeout(() => setInsPhase(1), 400),
      setTimeout(() => setInsPhase(2), 1400),
      setTimeout(() => setInsPhase(3), 2400),
    ];
    return () => ts.forEach(clearTimeout);
  }, [insVisible, insRun]);

  const barsShown = insPhase >= 2;
  useEffect(() => {
    if (!barsShown) return;
    const ts = insightBars.flatMap((b, i) =>
      b.pct >= b.threshold ? [setTimeout(() => setJiggled((s) => new Set(s).add(i)), 1400 + i * 200)] : [],
    );
    return () => ts.forEach(clearTimeout);
  }, [barsShown]);

  // Compute visible spec lines
  const visibleSpecLines = (() => {
    const p = wizPhase as string;
    const totalRevealed = p === 'done' ? wizMsgs.length : p === 'chat' ? 2 + wizChat.n : p === 'thinking' || p === 'files' ? 2 : p === 'prompt' ? 1 : 0;
    let lines = 0;
    for (let i = 0; i < totalRevealed; i++) { if (wizMsgs[i]?.specLines) lines = wizMsgs[i].specLines!; }
    return lines;
  })();

  // Engine visible sets
  const engVisChat = new Set<number>();
  const engVisTrace = new Set<number>();
  for (let s = 0; s < engStep.n; s++) {
    engStepMap[s].chat.forEach((i) => engVisChat.add(i));
    engStepMap[s].trace.forEach((i) => engVisTrace.add(i));
  }

  const wizMsgVisible = (i: number) => {
    const p = wizPhase as string;
    if (p === 'done') return true;
    if (i === 0) return p !== 'idle';
    if (i === 1) return p === 'files' || p === 'thinking' || p === 'chat';
    if (i === 2) return p === 'thinking' || p === 'chat';
    return p === 'chat' && wizChat.n >= i - 1;
  };
  const wizMsgIsThinking = (i: number) => wizPhase === 'thinking' && i === 2;
  const wizShown = wizMsgs.filter((_, i) => wizMsgVisible(i)).length;
  useFollowLatest(wizChatRef, `${wizShown}-${wizPhase}`);
  useFollowLatest(engChatRef, engVisChat.size);

  return (
    <div className="site-shell">
      <header className="site-header">
        <div className="container header-inner">
          <a className="header-brand" href="#top" aria-label="METIS home">
            <img src={asset('metis-logo.png')} alt="" />
            <strong>METIS</strong>
            <span>{FULL_NAME}</span>
          </a>
          <a className="button secondary header-github" href={GITHUB_URL}><Github /> GitHub</a>
        </div>
      </header>

      <main id="top">
        <section className="hero container">
          <HeroArt />
          <div className="hero-copy">
            <h1>Test your AI agents against <em>what they should actually do.</em></h1>
            <p className="hero-lede">Most evaluation tools score an agent's final answer. METIS evaluates the full trajectory against structured specifications: every decision, every tool call, every recovery.</p>
            <div className="hero-actions">
              <a className="button primary" href={GITHUB_URL}><Github /> View on GitHub</a>
              <a className="button secondary" href={DOCS_URL}>Read the docs <Arrow /></a>
            </div>
            <p className="hero-credit">Built by AI Practice, GovTech Singapore · Open source (MIT)</p>
          </div>
          <HeroStack />
        </section>

        <section className="methodology" id="methodology"><div className="container">
          <div className="section-heading"><div><div className="section-kicker">The evaluation loop</div><h2>Evaluate your agent against requirements you define.</h2></div><p>Each step ties back to the expectations you set, from how tests are designed to what the results tell you. Read our <a href="https://playbooks.aip.gov.sg/evaluation-playbook/" className="inline-link">Evaluation Playbook</a>.</p></div>
          <div className="steps">{steps.map((s) => (
            <article key={s.number} className="step">
              <div className="step-top"><span>{s.number} · {s.label}</span><b>{s.product}</b></div>
              <h3>{s.title}</h3><p>{s.text}</p>
            </article>
          ))}</div>
        </div></section>

        <section className="walkthrough" id="product"><div className="container">
          <div className="section-heading"><div><h2>See how METIS works.</h2></div><p>Follow a single evaluation of a Target AI Agent, from specification to results.</p></div>

          <div className="wt-stages">

            {/* ─ Stage 1: Wizard ─ */}
            <div className={`wt-stage ${seen.has(0) ? 'vis' : ''}`} ref={(el) => { refs.current[0] = el; }}>
              <div className="wt-head"><span className="wt-num wizard">01</span><div><h3>Wizard</h3><small>CREATE A SPECIFICATION</small></div>
                <button className="wt-replay" aria-label="Replay" onClick={() => { wizStarted.current = true; wizChat.replay(); startWizard(); }}><RestartIcon /></button>
              </div>
              <div className="wt-wizard-layout">
                <div className="wt-wizard-left">
                  <div className="wt-chat capped" ref={wizChatRef}>
                    {wizMsgs.map((m, i) => (
                      <div className={`wt-msg ${m.role} ${wizMsgVisible(i) ? 'show' : ''}`} key={i}>
                        <div className="wt-msg-head">
                          <img src={m.role === 'wizard' ? IC_WIZARD : IC_USER} alt="" className="wt-msg-icon" />
                          <span className="wt-msg-role">{m.role === 'wizard' ? 'Wizard' : 'You'}</span>
                        </div>
                        <div className={`wt-msg-bubble ${wizMsgIsThinking(i) ? 'wt-typing-bubble' : ''}`}>
                          {wizMsgIsThinking(i) ? <><i /><i /><i /></> : m.text}
                          {m.files && <div className="wt-msg-files">{m.files.map((f) => <span key={f} className="wt-file-chip"><FileDoc />{f}</span>)}</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="wt-wizard-right">
                  <div className={`wt-spec ${visibleSpecLines > 0 ? 'vis' : ''}`}>
                    <div className="wt-spec-chrome">specification.yaml</div>
                    <code><pre>{specLines.map((line, i) => (
                      <span key={i} className={`wt-spec-line ${i < visibleSpecLines ? 'vis' : ''}`} style={{ transitionDelay: `${i * 80}ms` }}>{line}{'\n'}</span>
                    ))}{visibleSpecLines > 0 && visibleSpecLines < specLines.length && <span className="wt-cursor">▋</span>}</pre></code>
                  </div>
                </div>
              </div>
            </div>

            <div className={`wt-connector ${vis.has(0) ? 'vis' : ''}`}><div className="wt-conn-track" /><div className="wt-conn-runner"><FileDoc /></div><span className="wt-conn-label">specification.yaml</span></div>

            {/* ─ Stage 2: Engine ─ */}
            <div className={`wt-stage ${seen.has(1) ? 'vis' : ''}`} ref={(el) => { refs.current[1] = el; }}>
              <div className="wt-head"><span className="wt-num engine">02</span><div><h3>Engine</h3><small>SIMULATE & CAPTURE TRACES</small></div>
                <button className="wt-replay" aria-label="Replay" onClick={() => { engStep.replay(); engTimer.replay(); }}><RestartIcon /></button>
              </div>
              <div className="wt-engine-panels">
                <div className="wt-tui">
                  <div className="wt-tui-head">METIS Engine Simulate — target-ai-agent</div>
                  <div className="wt-tui-body">
                    <div className="wt-tui-row"><span>Elapsed</span><b className="wt-timer">00:{engTimer.mm}:{engTimer.ss}</b></div>
                    <div className="wt-tui-row"><span>Scenarios</span><div className="wt-tui-bar"><div style={{ width: '33.3%' }} /></div><b>1/3</b></div>
                    <div className="wt-tui-row"><span>Trials</span><div className="wt-tui-bar"><div style={{ width: '44.4%' }} /></div><b>4/9</b></div>
                    <div className="wt-tui-workers">
                      {[{ id: 'TC-001', w: 'w0', name: 'knowledge-worker', start: 5 }, { id: 'TC-002', w: 'w1', name: 'focused-questioner', start: 120 }, { id: 'TC-003', w: 'w2', name: 'policy-seeker', start: 240 }].map((tc) => (
                        <div key={tc.id}>{tc.id} · <b>[{tc.w}]</b> {tc.name} {engTimer.simSec > tc.start ? <><Spinner /><span className="wt-sim">simulating</span></> : <span className="wt-wait">waiting</span>}</div>
                      ))}
                    </div>
                    {engTimer.simSec > 10 && <div className="wt-tui-log">
                      <div>[experiment] RUN: knowledge-worker × S-1</div>
                      {engTimer.simSec > 30 && <div>[sim] START: knowledge-worker × S-1 (max_turns=10)</div>}
                      {engTimer.simSec > 120 && <div>[sim] COMPLETE: TC-001 trial 1/3 — 3 turns, 35s</div>}
                      {engTimer.simSec > 180 && <div>[experiment] RUN: focused-questioner × S-2</div>}
                    </div>}
                  </div>
                </div>
                <div className="wt-trace">
                  <div className="wt-trace-head">EXECUTION TRACE</div>
                  <div className="wt-trace-body">
                    {traceSpans.map((sp, i) => (
                      <div className={`wt-span ${sp.type.toLowerCase()} ${engVisTrace.has(i) ? 'show' : ''}`} key={i} style={{ paddingLeft: `${sp.depth * 14}px` }}>
                        <span className={`wt-span-type ${sp.type.toLowerCase()}`}>{sp.type}</span>
                        <span className="wt-span-name">{sp.name}</span>
                        <div className="wt-span-bar"><div style={{ width: engVisTrace.has(i) ? `${(sp.ms / 35000) * 100}%` : '0%' }} /></div>
                        <span className="wt-span-ms">{(sp.ms / 1000).toFixed(1)}s{'tokens' in sp ? ` · ${sp.tokens}t` : ''}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <div className="wt-scenario-banner"><span className="wt-banner-tag">SCENARIO</span><strong>Draft a reply using a past event record</strong><span className="wt-banner-meta">persona: collaborative knowledge worker</span></div>
              <div className="wt-chat compact capped" ref={engChatRef}>
                {engMsgs.map((m, i) => (
                  <div className={`wt-msg ${m.role} ${engVisChat.has(i) ? 'show' : ''}`} key={i}>
                    <div className="wt-msg-head"><img src={m.role === 'user' ? IC_BOT_ROSE : IC_BOT_BLUE} alt="" className="wt-msg-icon" /><span className="wt-msg-role">{m.role === 'user' ? 'Simulated user' : 'Target AI Agent'}</span></div>
                    <div className="wt-msg-bubble">{m.text}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className={`wt-connector ${vis.has(1) ? 'vis' : ''}`}><div className="wt-conn-track" /><div className="wt-conn-runner"><TraceNodes /></div><span className="wt-conn-label">execution trace</span></div>

            {/* ─ Stage 3: Evaluation Pipeline ─ */}
            <div className={`wt-stage ${seen.has(2) ? 'vis' : ''}`} ref={(el) => { refs.current[2] = el; }}>
              <div className="wt-head"><span className="wt-num graders">03</span><div><h3>Evaluate</h3><small>GRADE AGAINST CRITERIA</small></div>
                <button className="wt-replay" aria-label="Replay" onClick={pipeline.replay}><RestartIcon /></button>
              </div>

              <div className="wt-pipeline">
                {/* Trace graph */}
                <div className={`wt-pipe-trace ${pipeline.phase >= 2 ? 'vis' : ''}`}>
                  <div className="wt-pipe-trace-label">CAPTURED TRACE</div>
                  <div className="wt-graph-scroll">
                    <svg className="wt-graph" viewBox={`-2 0 ${G_W + 4} 140`} role="img"
                      aria-label="Trace graph. The simulated user talks to the orchestrator agent. The orchestrator calls two subagents. search_agent calls search_knowledge_base and read_document, searches again after it reads the results, and synthesis_agent combines them. drafting_agent calls compose_email, and check_policy sends the draft back for revision once. Both branches join in the reply.">
                      <defs>
                        {['step', 'loop'].map((k) => (
                          <marker key={k} id={`wt-arrow-${k}`} className={k} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto">
                            <path d="M0,0 L8,4 L0,8 Z" />
                          </marker>
                        ))}
                      </defs>
                      {graphEdges.map((e, i) => (
                        <g key={i} className={`wt-graph-edge ${e.loop ? 'loop' : ''}`} style={{ transitionDelay: `${400 + i * 110}ms` }}>
                          <path d={e.d} pathLength={1} markerEnd={`url(#wt-arrow-${e.loop ? 'loop' : 'step'})`} />
                        </g>
                      ))}
                      {graphNodes.map((nd, i) => {
                        const hit = graphActive !== null && graphEvidence[graphActive].includes(nd.id);
                        const x = gx(nd), y = nd.y;
                        return (
                          <g key={nd.id} className={`wt-graph-node ${nd.kind} ${hit ? (graphActivePass ? 'pass' : 'fail') : ''}`} style={{ transitionDelay: `${i * 70}ms` }}>
                            <title>{nd.kind}</title>
                            <rect x={x} y={y - G_H / 2} width={gw(nd)} height={G_H} rx={6} />
                            <svg className="icon" x={x + 9} y={y - 6.5} width={13} height={13} viewBox="0 0 24 24">{LUCIDE[nd.icon]}</svg>
                            <text className="name" x={x + 27} y={y + 3.5}>{nd.label}</text>
                          </g>
                        );
                      })}
                    </svg>
                  </div>
                </div>

                {/* Fan-out indicator */}
                <div className={`wt-pipe-fanout ${pipeline.phase >= 3 ? 'vis' : ''}`}>
                  <div className="wt-fanout-line" /><span>Same trace sent to each criterion</span><div className="wt-fanout-line" />
                </div>

                {/* Parallel graders */}
                <div className={`wt-pipe-graders ${pipeline.phase >= 3 ? 'vis' : ''}`}>
                  {pipelineCriteria.map((c, i) => {
                    const done = pipeline.gradersDone.has(i);
                    const pass = c.score >= c.threshold;
                    return (
                      <div className={`wt-pipe-grader ${done ? (pass ? 'pass' : 'fail') : 'running'} ${graphActive === i ? 'active' : ''}`} key={c.id}
                        onMouseEnter={() => done && setGraphHover(i)} onMouseLeave={() => setGraphHover(null)}>
                        <div className="wt-pipe-grader-head">
                          <span className="wt-pipe-grader-type">{c.grader}</span>
                          {!done && <Spinner />}
                        </div>
                        <strong>{c.id}</strong>
                        {done ? (
                          <>
                            <div className="wt-pipe-score">Score: <b>{c.score.toFixed(2)}</b> <span>(threshold ≥ {c.threshold})</span></div>
                            <span className={`wt-badge ${pass ? 'pass' : 'fail'}`}>{pass ? <><Check /> Passed</> : <><Xmark /> Failed</>}</span>
                            <p className="wt-pipe-reason">{c.reason}</p>
                          </>
                        ) : (
                          <p className="wt-pipe-evaluating">Evaluating trace evidence…</p>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Converge indicator */}
                <div className={`wt-pipe-fanout ${pipeline.phase >= 4 ? 'vis' : ''}`}>
                  <div className="wt-fanout-line" /><span>Orchestrator applies thresholds</span><div className="wt-fanout-line" />
                </div>

                {/* Aggregated result */}
                <div className={`wt-pipe-result ${pipeline.phase >= 4 ? 'vis' : ''}`}>
                  <div className="wt-pipe-result-head">EVALUATION RESULT</div>
                  <div className="wt-pipe-result-body">
                    {pipelineCriteria.map((c) => {
                      const pass = c.score >= c.threshold;
                      return <div key={c.id} className={`wt-pipe-result-row ${pass ? 'pass' : 'fail'}`}><span>{c.id}</span><b>{c.score.toFixed(2)}</b><span className={`wt-badge ${pass ? 'pass' : 'fail'}`}>{pass ? 'Passed' : 'Failed'}</span></div>;
                    })}
                  </div>
                  <div className="wt-pipe-result-summary"><strong>1 of 3</strong> criteria passed this trial. Graders scored independently; the orchestrator applied each criterion's threshold.</div>
                </div>
              </div>
            </div>

            <div className={`wt-connector ${vis.has(2) ? 'vis' : ''}`}><div className="wt-conn-track" /><div className="wt-conn-runner"><Verdict /></div><span className="wt-conn-label">graded results</span></div>

            {/* ─ Stage 4: Insights ─ */}
            <div className={`wt-stage ${seen.has(3) ? 'vis' : ''}`} ref={(el) => { refs.current[3] = el; }}>
              <div className="wt-head"><span className="wt-num insights">04</span><div><h3>Insights</h3><small>PRESENT RESULTS</small></div>
                <button className="wt-replay" aria-label="Replay" onClick={() => { setInsPhase(0); setJiggled(new Set()); setInsRun((r) => r + 1); }}><RestartIcon /></button>
              </div>
              <div className="wt-insights">
                <div className={`wt-ins-panel ${insPhase >= 1 ? 'vis' : ''}`}>
                  <div className="wt-ins-title">SPECIFICATION RESULTS</div>
                  <div className="wt-tree">{insightTree.map((node, i) => (
                    <div className={`wt-tree-node ${node.pass ? 'pass' : 'fail'}`} key={i} style={{ paddingLeft: `${node.depth * 14}px`, transitionDelay: `${i * 180}ms` }}>
                      {node.depth > 0 && <span className="wt-tree-branch" />}
                      <span className="wt-tree-label">{node.label}</span>
                      <span className={`wt-tree-val ${node.pass ? 'pass' : 'fail'}`}>{node.value}%</span>
                    </div>
                  ))}</div>
                </div>

                <div className={`wt-ins-panel ${insPhase >= 2 ? 'vis' : ''}`}>
                  <div className="wt-ins-title">PASS RATES BY CRITERION</div>
                  <div className="wt-bars">{insightBars.map((b, i) => {
                    const passes = b.pct >= b.threshold;
                    return (
                      <div className={`wt-bar-row ${jiggled.has(i) && passes ? 'jiggle' : ''}`} key={i}>
                        <span className="wt-bar-label">{b.label}</span>
                        <div className="wt-bar-track"><div className="wt-bar-threshold" style={{ left: `${b.threshold}%` }} /><div className={`wt-bar-fill ${passes ? 'pass' : 'fail'}`} style={{ '--pct': `${b.pct}%` } as React.CSSProperties} /></div>
                        <span className={`wt-bar-val ${passes ? 'pass' : 'fail'}`}>{b.pct}%</span>
                        <span className="wt-bar-count">{b.passed}/{b.total}</span>
                      </div>
                    );
                  })}</div>
                </div>

                <div className={`wt-ins-panel ${insPhase >= 3 ? 'vis' : ''}`}>
                  <div className="wt-ins-title">TRIAL TRANSCRIPT & VERDICTS</div>
                  <div className="wt-mini-chat">
                    <div className="wt-mini-msg user">Reply about the offsite. What did we decide?</div>
                    <div className="wt-mini-msg asst">Sentosa, 40 attendees, booked 10 weeks ahead.</div>
                  </div>
                  <div className="wt-verdicts">
                    <div className="wt-verdict fail"><Xmark /><div><strong>Answer correctness</strong><span>Agent response says 40; deck says 42.</span></div></div>
                    <div className="wt-verdict pass"><Check /><div><strong>Source traceability</strong><span>References deck and thread.</span></div></div>
                  </div>
                </div>
              </div>
            </div>

          </div>
        </div></section>

        <section className="cta-section" id="get-started"><div className="container">
          <div className="cta-panel">
            <div className="cta-copy">
              <h2>Start evaluating with confidence.</h2>
              <p>Define what your agent should do, test the full trajectory, and know exactly what to fix before you ship.</p>
              <div className="cta-actions">
                <a className="button primary" href={GITHUB_URL}><Github /> View on GitHub</a>
                <a className="button secondary" href={DOCS_URL}>Read the docs <Arrow /></a>
              </div>
            </div>
            <CopyCommand command={INSTALL_CMD} />
          </div>
        </div></section>

      </main>

      <footer>
        <div className="container footer-inner">
          <div className="footer-top">
            <div className="footer-brand-group">
              <img src={asset('metis-logo.png')} alt="" className="footer-logo" />
              <div>
                <strong className="footer-name">METIS</strong>
                <span className="footer-full-name">{FULL_NAME}</span>
              </div>
            </div>
            <div className="footer-links">
              <a href="https://github.com/govtech-responsibleai">GitHub</a>
              <a href="https://blog.ai.gov.sg">Blog</a>
              <a href="https://huggingface.co/govtech">Hugging Face</a>
              <a href="https://playbooks.aip.gov.sg/responsibleai/">RAI Playbook</a>
              <a href="https://playbooks.aip.gov.sg/evaluation-playbook/">Eval Playbook</a>
            </div>
          </div>
          <div className="footer-bottom">
            <span className="footer-attr">Developed by AI Practice, GovTech Singapore</span>
            <span className="footer-copy">&copy; 2026 Government Technology Agency of Singapore</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
