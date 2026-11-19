import {useId} from 'react';
import styles from './styles.module.css';

// What each step of a walkthrough uses. A part that the step does not use is dimmed. The two
// walkthroughs number their steps differently, so each has its own table, picked by the
// `walkthrough` prop. Without a `step`, every part is lit, which gives the overview. A step with
// no entry, such as installing METIS, dims every part.
const IN_USE = {
  beginner: {
    1: ['app', 'langfuse', 'logTraces'], // try a demo session and open its trace
    4: ['metis'], // the Wizard drafts the specification
    5: ['metis', 'app', 'langfuse', 'callApp', 'logTraces', 'readTraces'], // simulate and grade
    6: ['metis', 'langfuse', 'openSession'], // open a trace from the Trials tab
    7: ['metis'], // read the report
  },
  advanced: {
    2: ['app'], // look at the target application
    3: ['metis'], // the Wizard drafts the specification
    4: ['metis', 'app', 'langfuse', 'callApp', 'logTraces'], // simulate
    5: ['metis', 'langfuse', 'openSession'], // find a trial's session in Langfuse
    6: ['metis', 'langfuse', 'readTraces'], // grade the traces
    7: ['metis'], // read the report
  },
};

const DESCRIPTION =
  'METIS drafts specifications, plays simulated users against the toy app, reads traces from ' +
  'Langfuse to grade them, and generates a report. The toy app logs every conversation to ' +
  'Langfuse as a trace.';

//  Layout (all three boxes are peers, no container):
//
//     METIS            Toy app
//     (left)        (top-centre)
//       |  \_____/     |
//       |              | logs traces
//       |<-- reads --->|
//       |-- inspects ->| Langfuse
//       |              (right)
//
export default function SystemDiagram({walkthrough, step}) {
  const id = useId();
  const arrow = `${id}-arrow`;
  const shadow = `${id}-shadow`;
  const lit = step === undefined ? null : IN_USE[walkthrough]?.[step] ?? [];
  const part = (name) => (lit === null || lit.includes(name) ? styles.on : styles.off);

  // Box geometry
  const metis = {x: 60, y: 180, w: 240, h: 90};
  const app = {x: 410, y: 70, w: 220, h: 90};
  const langfuse = {x: 690, y: 180, w: 210, h: 90};

  // Y coords for the two METIS↔Langfuse horizontal arrows (inside both boxes' vertical span)
  const readY = metis.y + 28;   // "reads traces" ← (upper)
  const inspectY = metis.y + 62; // "inspects session" → (lower)

  // Midpoint X between METIS right edge and Langfuse left edge (for label placement)
  const midX = (metis.x + metis.w + langfuse.x) / 2;

  return (
    <figure className={styles.figure}>
      <svg
        viewBox="0 40 960 260"
        role="img"
        aria-label={step === undefined ? 'System architecture' : `System architecture, step ${step}`}
        aria-description={DESCRIPTION}
        fontFamily="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif">
        <defs>
          <marker
            id={arrow}
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="8"
            markerHeight="8"
            orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="#475569" />
          </marker>
          <filter id={shadow} x="-5%" y="-5%" width="110%" height="120%">
            <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="#0f172a" floodOpacity="0.12" />
          </filter>
        </defs>

        <rect y="40" width="960" height="260" rx="16" fill="#ffffff" />

        {/* METIS (left) */}
        <g className={part('metis')}>
          <rect x={metis.x} y={metis.y} width={metis.w} height={metis.h} rx="14" fill="#eff6ff" stroke="#3b82f6" strokeWidth="2" filter={`url(#${shadow})`} />
          <text x={metis.x + metis.w / 2} y={metis.y + 38} fontSize="18" fontWeight="700" fill="#1e293b" textAnchor="middle">METIS</text>
          <text x={metis.x + metis.w / 2} y={metis.y + 60} fontSize="13" fill="#64748b" textAnchor="middle">Engine, Wizard &amp; Insights</text>
        </g>

        {/* Toy app (top-centre) */}
        <g className={part('app')}>
          <rect x={app.x} y={app.y} width={app.w} height={app.h} rx="14" fill="#ecfdf5" stroke="#10b981" strokeWidth="2" filter={`url(#${shadow})`} />
          <text x={app.x + app.w / 2} y={app.y + 35} fontSize="16" fontWeight="700" fill="#065f46" textAnchor="middle">Toy app</text>
          <text x={app.x + app.w / 2} y={app.y + 55} fontSize="12.5" fill="#047857" textAnchor="middle">Employee assistant with</text>
          <text x={app.x + app.w / 2} y={app.y + 72} fontSize="12.5" fill="#047857" textAnchor="middle">policy and report specialists</text>
        </g>

        {/* Langfuse (right, same Y as METIS) */}
        <g className={part('langfuse')}>
          <rect x={langfuse.x} y={langfuse.y} width={langfuse.w} height={langfuse.h} rx="14" fill="#fdf2f8" stroke="#ec4899" strokeWidth="2" filter={`url(#${shadow})`} />
          <text x={langfuse.x + langfuse.w / 2} y={langfuse.y + 38} fontSize="16" fontWeight="700" fill="#9d174d" textAnchor="middle">Langfuse</text>
          <text x={langfuse.x + langfuse.w / 2} y={langfuse.y + 58} fontSize="12.5" fill="#be185d" textAnchor="middle">Stores every conversation</text>
          <text x={langfuse.x + langfuse.w / 2} y={langfuse.y + 75} fontSize="12.5" fill="#be185d" textAnchor="middle">as a trace</text>
        </g>


        {/* --- Connections --- */}

        {/* METIS --interacts with app--> Toy app (up from METIS top to Toy app bottom) */}
        <g className={part('callApp')}>
          <path d={`M${metis.x + metis.w - 40},${metis.y} V${app.y + app.h / 2} H${app.x}`} fill="none" stroke="#475569" strokeWidth="2" markerEnd={`url(#${arrow})`} />
          <text x={metis.x + metis.w - 28} y={app.y + app.h / 2 - 8} fontSize="12.5" fill="#334155">interacts with app</text>
        </g>

        {/* Toy app --logs traces--> Langfuse (right then down) */}
        <g className={part('logTraces')}>
          <path d={`M${app.x + app.w},${app.y + app.h / 2} H${langfuse.x + langfuse.w / 2} V${langfuse.y}`} fill="none" stroke="#475569" strokeWidth="2" markerEnd={`url(#${arrow})`} />
          <text x={app.x + app.w + 12} y={app.y + app.h / 2 - 8} fontSize="12.5" fill="#334155">logs traces</text>
        </g>

        {/* Langfuse --reads traces--> METIS (straight horizontal, upper) */}
        <g className={part('readTraces')}>
          <path d={`M${langfuse.x},${readY} H${metis.x + metis.w}`} fill="none" stroke="#475569" strokeWidth="2" markerEnd={`url(#${arrow})`} />
          <text x={midX} y={readY - 8} fontSize="12.5" fill="#334155" textAnchor="middle">reads traces</text>
        </g>

        {/* METIS --inspects session--> Langfuse (straight horizontal, lower) */}
        <g className={part('openSession')}>
          <path d={`M${metis.x + metis.w},${inspectY} H${langfuse.x}`} fill="none" stroke="#475569" strokeWidth="2" markerEnd={`url(#${arrow})`} />
          <text x={midX} y={inspectY + 18} fontSize="12.5" fill="#334155" textAnchor="middle">inspects a Langfuse session</text>
        </g>

      </svg>
    </figure>
  );
}
