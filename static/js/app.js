document.documentElement.dataset.theme =
  localStorage.getItem("cdd-theme") || document.documentElement.dataset.theme || "light";

window.cddSetTheme = (theme) => {
  if (!["light", "dark", "warm", "fresh"].includes(theme)) return;
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("cdd-theme", theme);
};

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js"));
}
