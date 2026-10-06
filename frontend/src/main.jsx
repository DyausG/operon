import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-sans-condensed/latin-500.css";
import "@fontsource/ibm-plex-sans-condensed/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/primitives.css";
import "./styles/shell.css";
import "./styles/kpi.css";
import "./styles/incident-switcher.css";
import "./styles/signal.css";
import "./styles/stage.css";
import "./styles/record.css";
import "./styles/inspector.css";
import "./styles/app-shell.css";
import "./styles/components.css";
import "./styles/pages.css";
import "./styles/login.css";
import "./styles/charts.css";
// V2 workbench: IBM's official Plex files (unmodified) and the scoped V2 token/component styles.
import "./v2/styles/fonts.js";
import "./v2/styles/tokens.css";
import "./v2/styles/base.css";
import "./v2/styles/components.css";
import "./v2/styles/shell.css";
import "./v2/styles/screens.css";
import App from "./App.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
