// Theme choice: "auto" follows the system, "dark" / "light" are fixed. Stored per browser (a convenience).
import { useEffect, useState } from "react";

export type ThemeChoice = "auto" | "dark" | "light";
const KEY = "ta-theme";

function read(): ThemeChoice {
  try {
    const value = localStorage.getItem(KEY);
    return value === "dark" || value === "light" || value === "auto" ? value : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(choice: ThemeChoice) {
  document.documentElement.dataset.theme = choice;
}

export function useTheme(): [ThemeChoice, (c: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(read);
  useEffect(() => {
    applyTheme(choice);
    try {
      localStorage.setItem(KEY, choice);
    } catch {
      // private mode – the choice lasts for this page only
    }
  }, [choice]);
  return [choice, setChoice];
}
