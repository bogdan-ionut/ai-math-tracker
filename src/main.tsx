import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource/bodoni-moda/400.css";
import "@fontsource/bodoni-moda/600.css";
import "@fontsource/bodoni-moda/700.css";
import "@fontsource-variable/inter";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";

import "./styles/globals.css";
import { App } from "./app/App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
