import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { LoginGate } from "./LoginGate";
import "./globals.css";

const root = document.getElementById("root");
if (!root) throw new Error("No #root element to mount into.");

createRoot(root).render(
  <StrictMode>
    <LoginGate>
      <App />
    </LoginGate>
  </StrictMode>,
);
