import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/app.css";

try {
  document.documentElement.dataset.theme = localStorage.getItem("twin.theme") || "dark";
} catch { /* storage unavailable */ }

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
