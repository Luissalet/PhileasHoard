import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { installCopilot } from "./copilot-context.js";
import "./hoard-theme.css";
import "./index.css";

// The assistant panel (added by the family launcher) asks for the open object and the unsaved fields.
installCopilot(window);

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// PWA: register the service worker so the app can be installed. Only over HTTPS or localhost; never breaks the app.
if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
  try {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    });
  } catch {
    // installing is optional
  }
}
