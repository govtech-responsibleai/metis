// The colour theme. The user picks System, Light, or Dark, and the browser keeps the choice for the
// next visit. System follows the operating system setting and changes when that setting changes.
// The resolved theme is the `data-theme` attribute on <html>, which `globals.css` reads.
// `index.html` runs the same resolution before the first paint, so a dark page never flashes white.

import { useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";
export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "metis-web:theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

export function parseThemeChoice(value: string | null): ThemeChoice {
  return value === "light" || value === "dark" ? value : "system";
}

export function resolveTheme(choice: ThemeChoice, systemDark: boolean): Theme {
  if (choice === "system") return systemDark ? "dark" : "light";
  return choice;
}

function storedChoice(): ThemeChoice {
  try {
    return parseThemeChoice(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

function systemDark(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia(DARK_QUERY).matches
  );
}

// The theme choice, and a setter that stores it and applies it to the page.
export function useThemeChoice(): [ThemeChoice, (choice: ThemeChoice) => void] {
  const [choice, setChoice] = useState(storedChoice);

  useEffect(() => {
    const apply = () => {
      document.documentElement.dataset.theme = resolveTheme(
        choice,
        systemDark(),
      );
    };
    apply();
    if (choice !== "system" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(DARK_QUERY);
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, [choice]);

  const set = (next: ThemeChoice) => {
    setChoice(next);
    try {
      if (next === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
      else window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // A browser that refuses storage still changes the theme for this visit.
    }
  };
  return [choice, set];
}
