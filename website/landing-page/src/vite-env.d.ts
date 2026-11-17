/// <reference types="vite/client" />

declare module 'vanta/dist/vanta.net.min' {
  const effect: (opts: Record<string, unknown>) => { destroy: () => void };
  export default effect;
}
