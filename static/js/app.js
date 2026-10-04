// Shared progressive enhancement for theme persistence and shell interactions.
const serverTheme = document.documentElement.dataset.theme || "light";
document.documentElement.dataset.theme = document.body?.dataset.authenticated === "true"
  ? serverTheme
  : localStorage.getItem("cdd-theme") || serverTheme;

window.cddSetTheme = (theme) => {
  if (!["light", "dark", "warm", "fresh"].includes(theme)) return;
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("cdd-theme", theme);
  const url = document.body?.dataset.themeUrl;
  if (url) {
    const data = new FormData();
    data.append("theme", theme);
    fetch(url, {
      method: "POST",
      body: data,
      headers: { "X-CSRFToken": cddCookie("csrftoken") },
      credentials: "same-origin",
    });
  }
};

function cddCookie(name) {
  const item = document.cookie.split("; ").find((row) => row.startsWith(`${name}=`));
  return item ? decodeURIComponent(item.split("=")[1]) : "";
}

const heartbeatSeconds = Number(document.body?.dataset.heartbeatInterval || 0);
const heartbeatUrl = document.body?.dataset.heartbeatUrl;
if (heartbeatSeconds > 0 && heartbeatUrl) {
  let heartbeatPending = false;
  const sendHeartbeat = async () => {
    if (heartbeatPending || document.visibilityState === "hidden") return;
    heartbeatPending = true;
    try {
      const response = await fetch(heartbeatUrl, {
      method: "POST",
      headers: { "X-CSRFToken": cddCookie("csrftoken") },
      credentials: "same-origin",
      });
      if (response.status === 401) window.location.assign("/login/");
    } catch (_error) {
      // A temporary network/certificate failure must not create an unhandled promise.
    } finally {
      heartbeatPending = false;
    }
  };
  window.setInterval(sendHeartbeat, heartbeatSeconds * 1000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") sendHeartbeat();
  });
  window.addEventListener("focus", sendHeartbeat);
  window.addEventListener("online", sendHeartbeat);
  sendHeartbeat();
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js"));
}
