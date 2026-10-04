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

// Native dialogs keep small edit/preview actions on the current page and inherit live themes.
document.addEventListener("click", (event) => {
  const opener = event.target.closest("[data-cdd-modal-open]");
  if (opener) {
    const dialog = document.getElementById(opener.dataset.cddModalOpen);
    if (dialog?.showModal) dialog.showModal();
    return;
  }
  const closer = event.target.closest("[data-cdd-modal-close]");
  if (closer) closer.closest("dialog")?.close();
});
document.querySelectorAll("dialog.cdd-modal").forEach((dialog) => {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
});
document.querySelectorAll("form[data-cdd-confirm-value], form[data-cdd-require-input]").forEach((form) => {
  const field = form.querySelector("input[name='confirmation'], textarea[name='reason']");
  const submit = form.querySelector("[data-cdd-confirm-submit]");
  if (!field || !submit) return;
  const update = () => {
    const requiredValue = form.dataset.cddConfirmValue;
    submit.disabled = requiredValue
      ? field.value.trim() !== requiredValue
      : field.value.trim().length === 0;
  };
  field.addEventListener("input", update);
  update();
});

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
