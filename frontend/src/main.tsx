// Slovak needs latin + latin-ext only; fonts are bundled so the app works offline.
import "@fontsource/barlow/latin-400.css";
import "@fontsource/barlow/latin-ext-400.css";
import "@fontsource/barlow/latin-500.css";
import "@fontsource/barlow/latin-ext-500.css";
import "@fontsource/barlow/latin-600.css";
import "@fontsource/barlow/latin-ext-600.css";
import "@fontsource/barlow/latin-700.css";
import "@fontsource/barlow/latin-ext-700.css";
import "@fontsource/barlow-semi-condensed/latin-500.css";
import "@fontsource/barlow-semi-condensed/latin-ext-500.css";
import "@fontsource/barlow-semi-condensed/latin-600.css";
import "@fontsource/barlow-semi-condensed/latin-ext-600.css";
import "@fontsource/barlow-semi-condensed/latin-700.css";
import "@fontsource/barlow-semi-condensed/latin-ext-700.css";
import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { applyTheme } from "./app/theme";
import { router } from "./router";

try {
  applyTheme((localStorage.getItem("ta-theme") as "auto" | "dark" | "light" | null) ?? "dark");
} catch {
  applyTheme("dark");
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
