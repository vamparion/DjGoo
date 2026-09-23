import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { RemoteApp } from "./RemoteApp";
import "./styles.css";

const PENDING_INVITE = "djgoo-pending-web-invite";
const REMOTE_CACHE_RELOAD = "djgoo-remote-cache-reload";
const fragment = window.location.hash;
const fragmentInvitation = fragment.startsWith("#pair=") ? decodeURIComponent(fragment.slice(6)) : "";
const invitation = fragmentInvitation || sessionStorage.getItem(PENDING_INVITE) || "";
sessionStorage.removeItem(PENDING_INVITE);
if (fragment) history.replaceState(null, "", window.location.pathname + window.location.search);
const publicWebHost = window.location.hostname === "vamparion.github.io";
const remoteMode = Boolean(publicWebHost || invitation || sessionStorage.getItem("djgoo-web-session") || localStorage.getItem("djgoo-web-remembered"));

async function start() {
  if (remoteMode && "serviceWorker" in navigator) {
    const registrations = await navigator.serviceWorker.getRegistrations().catch(() => []);
    await Promise.all(registrations.map(registration => registration.unregister()));
    if ("caches" in window) {
      const keys = await caches.keys().catch(() => []);
      await Promise.all(keys.filter(key => key.startsWith("djgoo-control-")).map(key => caches.delete(key)));
    }
    if (navigator.serviceWorker.controller && !sessionStorage.getItem(REMOTE_CACHE_RELOAD)) {
      sessionStorage.setItem(REMOTE_CACHE_RELOAD, "1");
      if (invitation) sessionStorage.setItem(PENDING_INVITE, invitation);
      window.location.replace(`${window.location.pathname}${window.location.search}${window.location.search ? "&" : "?"}djgoo_refresh=${Date.now()}`);
      return;
    }
    sessionStorage.removeItem(REMOTE_CACHE_RELOAD);
  }

  createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      {remoteMode ? <RemoteApp invite={invitation} /> : <App />}
    </React.StrictMode>
  );

  if (!remoteMode && "serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("./service-worker.js"));
  }
}

void start();
