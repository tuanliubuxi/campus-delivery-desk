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

// A modal must never scroll the page behind it, including after an inner scroller reaches its edge.
let cddBackgroundScroll = null;
function cddSyncModalScrollLock() {
  const hasOpenDialog = Boolean(document.querySelector("dialog[open]"));
  if (hasOpenDialog && cddBackgroundScroll === null) {
    const body = document.body;
    cddBackgroundScroll = {
      y: window.scrollY,
      position: body.style.position,
      top: body.style.top,
      width: body.style.width,
      overflow: document.documentElement.style.overflow,
    };
    body.style.position = "fixed";
    body.style.top = `-${cddBackgroundScroll.y}px`;
    body.style.width = "100%";
    document.documentElement.style.overflow = "hidden";
  } else if (!hasOpenDialog && cddBackgroundScroll !== null) {
    const saved = cddBackgroundScroll;
    cddBackgroundScroll = null;
    document.body.style.position = saved.position;
    document.body.style.top = saved.top;
    document.body.style.width = saved.width;
    document.documentElement.style.overflow = saved.overflow;
    window.scrollTo(0, saved.y);
  }
}
new MutationObserver(cddSyncModalScrollLock).observe(document.documentElement, {
  attributes: true,
  attributeFilter: ["open"],
  childList: true,
  subtree: true,
});
cddSyncModalScrollLock();

document.addEventListener("submit", (event) => {
  const input = event.target.querySelector("[data-cdd-page-number]");
  if (!input) return;
  const value = input.value.trim();
  if (!/^[1-9][0-9]*$/.test(value)) {
    event.preventDefault();
    input.setCustomValidity("请输入正整数页码");
    input.reportValidity();
    return;
  }
  input.setCustomValidity("");
  input.value = String(Math.min(Number(value), Number(input.dataset.maxPage)));
  const dialog = event.target.closest("dialog");
  if (event.target.hasAttribute("data-cdd-remote-page-form") && dialog) {
    event.preventDefault();
    const url = new URL(dialog.dataset.cddModalUrl, location.href);
    url.searchParams.set(input.name, input.value);
    loadRemoteModal(dialog, url.href);
  }
});
document.addEventListener("input", (event) => {
  if (event.target.matches("[data-cdd-page-number]")) event.target.setCustomValidity("");
});

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
    if (dialog?.showModal) {
      dialog.showModal();
      if (dialog.matches("[data-cdd-wage-slip]")) cddShowWageSlip(dialog, "card");
    }
    return;
  }
  const closer = event.target.closest("[data-cdd-modal-close]");
  if (closer) closer.closest("dialog")?.close();
});
function cddShowWageSlip(dialog, style) {
  const theme = document.documentElement.dataset.theme || "light";
  const url = new URL(style === "formal" ? dialog.dataset.formalUrl : dialog.dataset.cardUrl, location.href);
  url.searchParams.set("theme", theme);
  dialog.querySelectorAll("[data-cdd-slip-style]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.cddSlipStyle === style));
  });
  const preview = dialog.querySelector("[data-cdd-slip-image]");
  const message = dialog.querySelector("[data-cdd-slip-message]");
  const download = dialog.querySelector("[data-cdd-slip-download]");
  preview.hidden = true;
  message.hidden = false;
  message.textContent = "正在载入预览……";
  download.classList.add("disabled");
  download.setAttribute("aria-disabled", "true");
  preview.onload = () => {
    preview.hidden = false;
    message.hidden = true;
    download.classList.remove("disabled");
    download.removeAttribute("aria-disabled");
  };
  preview.onerror = () => {
    preview.hidden = true;
    message.textContent = "预览加载失败，请确认登录状态后重试。";
  };
  preview.src = url.toString();
  url.searchParams.set("download", "1");
  download.href = url.toString();
}
document.addEventListener("click", (event) => {
  const tab = event.target.closest("[data-cdd-slip-style]");
  if (tab) cddShowWageSlip(tab.closest("[data-cdd-wage-slip]"), tab.dataset.cddSlipStyle);
});
function cddUpdateWageAdjustment(form) {
  const type = form.querySelector("#wage-adjustment-type");
  const amount = form.querySelector("#wage-adjustment-amount");
  const preview = form.querySelector("#wage-adjustment-preview");
  const button = form.querySelector("#wage-adjustment-submit");
  if (!type || !amount || !preview || !button) return;
  const negative = new Set(["OVERPAY_CORRECTION", "REFUND_CORRECTION", "REVIEWED_LOSS"]);
  const value = Number(amount.value);
  const total = Number(preview.dataset.current) + (negative.has(type.value) ? -value : value);
  const valid = amount.value !== "" && Number.isFinite(value) && value > 0 && total > 0;
  preview.textContent = `调整后预计应发 ¥${total.toFixed(2)}${valid ? "" : "；必须大于 0 元"}`;
  preview.classList.toggle("text-danger", !valid);
  button.disabled = !valid;
}
function cddInitWageAdjustments(root = document) {
  root.querySelectorAll("#wage-adjustment-submit").forEach((button) => {
    cddUpdateWageAdjustment(button.form);
  });
}
document.addEventListener("input", (event) => {
  if (event.target.matches("#wage-adjustment-amount")) cddUpdateWageAdjustment(event.target.form);
});
document.addEventListener("change", (event) => {
  if (event.target.matches("#wage-adjustment-type")) cddUpdateWageAdjustment(event.target.form);
});
document.addEventListener("htmx:afterSwap", (event) => cddInitWageAdjustments(event.detail.target));
document.addEventListener("htmx:beforeSwap", (event) => {
  const innerDialog = event.detail.elt?.closest("dialog.cdd-modal");
  if (innerDialog?.open && innerDialog.closest("[data-cdd-wage-content]")) innerDialog.close();
});
cddInitWageAdjustments();
function cddWageRequestError(event) {
  const panel = event.detail.target?.closest(".cdd-wage-workflow-modal") ||
    event.detail.elt.closest(".cdd-wage-workflow-modal") ||
    document.getElementById(event.detail.elt.dataset.cddModalOpen || "");
  if (!panel) return;
  const content = panel.querySelector("[data-cdd-wage-content]") || panel.querySelector("[id^='wage-flow-content-']");
  if (content) content.insertAdjacentHTML("afterbegin", '<div class="alert alert-danger" role="alert">操作未完成，请检查登录状态和网络后重试。</div>');
}
document.addEventListener("htmx:responseError", cddWageRequestError);
document.addEventListener("htmx:sendError", cddWageRequestError);
function cddCloseSortMenus(except = null) {
  document.querySelectorAll("details.cdd-sort-menu[open]").forEach((menu) => {
    if (menu !== except) menu.open = false;
  });
}
document.addEventListener("pointerdown", (event) => {
  cddCloseSortMenus(event.target.closest("details.cdd-sort-menu"));
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") cddCloseSortMenus();
});
document.addEventListener("scroll", () => cddCloseSortMenus(), true);
document.addEventListener("toggle", (event) => {
  if (event.target.matches?.("details.cdd-sort-menu") && event.target.open) {
    cddCloseSortMenus(event.target);
  }
}, true);
document.addEventListener("toggle", async (event) => {
  const panel = event.target;
  if (!panel.matches?.("details[data-cdd-evidence-url]") || !panel.open || panel.dataset.cddEvidenceLoaded) return;
  const result = panel.querySelector("[data-cdd-evidence-result]");
  if (!result) return;
  result.textContent = "正在加载原始证据……";
  try {
    const response = await fetch(panel.dataset.cddEvidenceUrl, {credentials: "same-origin"});
    if (!response.ok || response.redirected) throw new Error("证据不可读取");
    result.innerHTML = await response.text();
    panel.dataset.cddEvidenceLoaded = "1";
  } catch (_error) {
    result.textContent = "原始证据暂不可读取，请检查登录状态后重试。";
  }
}, true);
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
document.addEventListener("click", (event) => {
  if (event.target.matches?.("dialog.cdd-modal") && !event.target.hasAttribute("data-cdd-locked")) {
    event.target.close();
  }
});
document.addEventListener("cancel", (event) => {
  if (event.target.matches?.("dialog.cdd-modal[data-cdd-locked]")) event.preventDefault();
}, true);
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
