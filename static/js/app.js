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
  const remoteOpener = event.target.closest("[data-cdd-remote-modal]");
  if (remoteOpener) {
    const dialog = document.getElementById(remoteOpener.dataset.cddRemoteModal);
    if (dialog?.showModal) {
      dialog.showModal();
      loadRemoteModal(dialog, remoteOpener.dataset.cddModalUrl);
    }
    return;
  }
  const remotePage = event.target.closest("[data-cdd-remote-page]");
  if (remotePage) {
    const dialog = remotePage.closest("dialog");
    if (dialog?.dataset.cddModalUrl) {
      event.preventDefault();
      loadRemoteModal(dialog, new URL(remotePage.getAttribute("href"), dialog.dataset.cddModalUrl).href);
    }
    return;
  }
  const opener = event.target.closest("[data-cdd-modal-open]");
  if (opener) {
    const dialog = document.getElementById(opener.dataset.cddModalOpen);
    if (dialog?.showModal) dialog.showModal();
    return;
  }
  const closer = event.target.closest("[data-cdd-modal-close]");
  if (closer) closer.closest("dialog")?.close();
});
async function loadRemoteModal(dialog, url) {
  const content = dialog.querySelector("[data-cdd-remote-content]");
  if (!content) return;
  dialog.dataset.cddModalUrl = url;
  content.textContent = "正在加载登录历史……";
  try {
    const response = await fetch(url, {credentials: "same-origin", headers: {"X-CDD-Modal": "1"}});
    if (!response.ok || response.redirected) throw new Error("无法读取登录历史");
    content.innerHTML = await response.text();
  } catch (_error) {
    content.textContent = "登录历史暂时无法加载，请稍后重试。";
  }
}
document.querySelectorAll("dialog.cdd-modal").forEach((dialog) => {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog && !dialog.hasAttribute("data-cdd-locked")) dialog.close();
  });
  if (dialog.hasAttribute("data-cdd-locked")) {
    dialog.addEventListener("cancel", (event) => event.preventDefault());
  }
});
// Flash messages survive redirects; open them after the page is ready without losing focus context.
document.querySelectorAll("dialog.cdd-modal[data-cdd-auto-open]").forEach((dialog) => {
  if (dialog.showModal) dialog.showModal();
});
document.addEventListener("change", (event) => {
  if (!event.target.matches("[data-cdd-settlement-group]") || !event.target.checked) return;
  event.target.form.querySelectorAll("[data-cdd-settlement-group]").forEach((input) => {
    if (input !== event.target) input.checked = false;
  });
});
document.addEventListener("change", (event) => {
  if (event.target.id !== "id_express_round" || !event.target.closest("form")?.querySelector(".cdd-consolidation-options")) return;
  const url = new URL(window.location.href);
  url.searchParams.set("express_round", event.target.value);
  window.location.assign(url.toString());
});
document.querySelectorAll("[data-cdd-exception-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const selected = button.dataset.cddExceptionTab;
    document.querySelectorAll("[data-cdd-exception-tab]").forEach((tab) => {
      tab.classList.toggle("btn-primary", tab.dataset.cddExceptionTab === selected);
      tab.classList.toggle("btn-outline-primary", tab.dataset.cddExceptionTab !== selected);
    });
    document.querySelectorAll("[data-cdd-exception-panel]").forEach((panel) => {
      panel.classList.toggle("is-mobile-active", panel.dataset.cddExceptionPanel === selected);
    });
  });
});
const appHeader = document.querySelector(".cdd-app-header");
if (appHeader && window.ResizeObserver) {
  const syncHeaderHeight = () => document.documentElement.style.setProperty(
    "--cdd-header-height", `${appHeader.getBoundingClientRect().height}px`,
  );
  new ResizeObserver(syncHeaderHeight).observe(appHeader);
  syncHeaderHeight();
}
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
