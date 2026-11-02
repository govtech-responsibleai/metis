import {useId} from 'react';
import styles from './styles.module.css';

// What each step of the workshop walkthrough uses. Step 1 is the installation, which no part of
// the picture stands for, so it has no entry. A part that the step does not use is dimmed.
// Without a `step`, every part is lit, which gives the overview.
const IN_USE = {
  2: ['browser', 'app'],
  3: ['wizard', 'gateway', 'modelCalls'],
  4: ['engine', 'app', 'langfuse', 'gateway', 'callApp', 'logTraces', 'modelCalls'],
  5: ['browser', 'langfuse', 'openSession'],
  6: ['engine', 'langfuse', 'gateway', 'readTraces', 'modelCalls'],
  7: ['engine', 'browser'],
};

const DESCRIPTION =
  "The participant's laptop runs the METIS Wizard, the METIS engine and a browser. The engine plays " +
  'simulated users against the toy app, which logs traces to Langfuse. The engine later reads ' +
  'those traces back to grade them, and the browser opens them in Langfuse. A model gateway ' +
  'serves the language model calls.';

// A picture of the system that the walkthrough uses. `step` is the walkthrough step (1 to 7) to
// light up; leave it out to light up everything. Nothing in it is specific to one deployment:
// there are no addresses, keys or logins, so it is safe to publish.
export default function SystemDiagram({step}) {
  const id = useId();
  const arrow = `${id}-arrow`;
  const shadow = `${id}-shadow`;
  const lit = step === undefined ? null : IN_USE[step] ?? [];
  const part = (name) => (lit === null || lit.includes(name) ? styles.on : styles.off);

  return (
    <figure className={styles.figure}>
      <svg
        viewBox="0 80 960 490"
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

        <rect y="80" width="960" height="490" rx="16" fill="#ffffff" />

        {/* Participant's laptop */}
        <rect x="40" y="110" width="300" height="340" rx="18" fill="#f1f5f9" stroke="#94a3b8" strokeWidth="1.5" />
        <text x="64" y="138" fontSize="15" fontWeight="700" fill="#334155">
          Participant's laptop
        </text>

        <g className={part('wizard')}>
          <rect x="64" y="160" width="252" height="64" rx="12" fill="#ffffff" stroke="#3b82f6" strokeWidth="2" filter={`url(#${shadow})`} />
          <text x="84" y="188" fontSize="15" fontWeight="700" fill="#1e293b">METIS Wizard</text>
          <text x="84" y="208" fontSize="12.5" fill="#64748b">Drafts the specification</text>
        </g>
        <g className={part('engine')}>
          <rect x="64" y="250" width="252" height="84" rx="12" fill="#ffffff" stroke="#3b82f6" strokeWidth="2" filter={`url(#${shadow})`} />
          <text x="84" y="278" fontSize="15" fontWeight="700" fill="#1e293b">METIS engine</text>
          <text x="84" y="299" fontSize="12.5" fill="#64748b">simulate · evaluate</text>
          <text x="84" y="318" fontSize="12.5" fill="#64748b">insights report</text>
        </g>
        <g className={part('browser')}>
          <rect x="64" y="360" width="252" height="64" rx="12" fill="#ffffff" stroke="#3b82f6" strokeWidth="2" filter={`url(#${shadow})`} />
          <text x="84" y="398" fontSize="15" fontWeight="700" fill="#1e293b">Browser</text>
        </g>

        {/* Toy app */}
        <g className={part('app')}>
          <rect x="440" y="110" width="200" height="100" rx="14" fill="#ecfdf5" stroke="#10b981" strokeWidth="2" filter={`url(#${shadow})`} />
          <text x="540" y="146" fontSize="16" fontWeight="700" fill="#065f46" textAnchor="middle">Toy app</text>
          <text x="540" y="167" fontSize="12.5" fill="#047857" textAnchor="middle">Employee assistant with</text>
          <text x="540" y="185" fontSize="12.5" fill="#047857" textAnchor="middle">policy and report specialists</text>
        </g>

        {/* Langfuse */}
        <g className={part('langfuse')}>
          <rect x="740" y="250" width="180" height="100" rx="14" fill="#fdf2f8" stroke="#ec4899" strokeWidth="2" filter={`url(#${shadow})`} />
          <text x="830" y="294" fontSize="16" fontWeight="700" fill="#9d174d" textAnchor="middle">Langfuse</text>
          <text x="830" y="316" fontSize="12.5" fill="#be185d" textAnchor="middle">Stores every conversation</text>
          <text x="830" y="334" fontSize="12.5" fill="#be185d" textAnchor="middle">as a trace</text>
        </g>

        {/* Model gateway */}
        <g className={part('gateway')}>
          <rect x="440" y="470" width="200" height="70" rx="14" fill="#fffbeb" stroke="#f59e0b" strokeWidth="2" filter={`url(#${shadow})`} />
          <text x="540" y="502" fontSize="16" fontWeight="700" fill="#92400e" textAnchor="middle">Model gateway</text>
          <text x="540" y="522" fontSize="12.5" fill="#b45309" textAnchor="middle">LLM access</text>
        </g>

        {/* Connections */}
        <g className={part('callApp')}>
          <path d="M316,270 H540 V212" fill="none" stroke="#475569" strokeWidth="2" markerEnd={`url(#${arrow})`} />
          <text x="558" y="262" fontSize="12.5" fill="#334155">interacts with app</text>
        </g>
        <g className={part('logTraces')}>
          <path d="M640,160 H830 V248" fill="none" stroke="#475569" strokeWidth="2" markerEnd={`url(#${arrow})`} />
          <text x="735" y="150" fontSize="12.5" fill="#334155" textAnchor="middle">logs traces</text>
        </g>
        <g className={part('readTraces')}>
          <path d="M738,314 H318" fill="none" stroke="#475569" strokeWidth="2" markerEnd={`url(#${arrow})`} />
          <text x="528" y="306" fontSize="12.5" fill="#334155" textAnchor="middle">reads traces</text>
        </g>
        <g className={part('openSession')}>
          <path d="M316,392 H830 V352" fill="none" stroke="#475569" strokeWidth="2" markerEnd={`url(#${arrow})`} />
          <text x="573" y="384" fontSize="12.5" fill="#334155" textAnchor="middle">inspects a Langfuse session</text>
        </g>
        <g className={part('modelCalls')}>
          <path d="M190,450 V505 H438" fill="none" stroke="#475569" strokeWidth="2" markerEnd={`url(#${arrow})`} />
          <text x="206" y="496" fontSize="12.5" fill="#334155">model calls</text>
        </g>
      </svg>
    </figure>
  );
}
