import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { RemoteApp } from "./RemoteApp";
import "./styles.css";

const fragment = window.location.hash;
const invitation = fragment.startsWith("#pair=") ? decodeURIComponent(fragment.slice(6)) : "";
if (fragment) history.replaceState(null, "", window.location.pathname + window.location.search);
const remoteMode = Boolean(invitation || sessionStorage.getItem("djgoo-web-session") || localStorage.getItem("djgoo-web-remembered"));
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {remoteMode ? <RemoteApp invite={invitation} /> : <App />}
  </React.StrictMode>
);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("./service-worker.js"));
}
