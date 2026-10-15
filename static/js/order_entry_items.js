// A shared ordinary/backfill editor. The server validates every row again.
window.cddShowOrderValidation = function (form, errors) {
  if (!form.closest("main")?.querySelector("[data-cdd-order-entry]")) return;
  let dialog = document.getElementById("cdd-order-validation-dialog");
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = "cdd-order-validation-dialog";
    dialog.className = "cdd-modal";
    const panel = document.createElement("div");
    panel.className = "cdd-modal-panel";
    const heading = document.createElement("h2");
    heading.className = "h5";
    heading.textContent = "请检查录单信息";
    const list = document.createElement("ul");
    list.dataset.cddValidationList = "";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "btn btn-primary";
    close.textContent = "返回修改";
    close.addEventListener("click", () => dialog.close());
    panel.append(heading, list, close);
    dialog.append(panel);
    document.body.append(dialog);
  }
  const list = dialog.querySelector("[data-cdd-validation-list]");
  list.replaceChildren();
  [...new Set(errors)].forEach((message) => {
    const row = document.createElement("li");
    row.textContent = message;
    list.append(row);
  });
  if (!dialog.open) dialog.showModal();
};
document.querySelectorAll("[data-cdd-order-entry]").forEach((main) => {
  const form = main.querySelector("form[method='post']");
  const initialErrors = [...form.querySelectorAll(".alert-danger, .text-danger, .errorlist")]
    .map((node) => node.textContent.trim()).filter(Boolean);
  if (initialErrors.length) window.cddShowOrderValidation(form, initialErrors);
});
document.querySelectorAll("[data-cdd-item-editor]").forEach((editor) => {
  const form = editor.closest("form");
  const kind = editor.dataset.kind;
  const stored = form.querySelector('[name="entry_items"]');
  const dialog = editor.querySelector("[data-cdd-item-dialog]");
  const valueInput = editor.querySelector("[data-cdd-item-value]");
  const sizeInput = editor.querySelector("[data-cdd-item-size]");
  const outsideBox = editor.querySelector("[data-cdd-item-outside]");
  const outsideInput = editor.querySelector("[data-cdd-item-outside-input]");
  const error = editor.querySelector("[data-cdd-item-error]");
  const dialogError = editor.querySelector("[data-cdd-item-dialog-error]");
  let rows = [];
  let currentArea = "";
  try {
    const existing = JSON.parse(stored.value || "[]");
    if (Array.isArray(existing)) rows = existing;
  } catch (_ignored) { /* Invalid submitted JSON will be rejected by the server. */ }

  function sync() {
    stored.value = JSON.stringify(rows);
    editor.querySelectorAll("[data-cdd-item-rows]").forEach((body) => body.replaceChildren());
    rows.forEach((row, index) => {
      const area = kind === "EXPRESS" ? row.pickup_area : "all";
      const body = editor.querySelector(`[data-cdd-item-rows="${area}"]`);
      if (!body) return;
      const tr = document.createElement("tr");
      const first = document.createElement("td");
      first.textContent = kind === "EXPRESS"
        ? ({UNKNOWN: "未知", SMALL: "小件", MEDIUM: "中件", LARGE: "大件", OVERSIZE: "超大件"}[row.size_class] || row.size_class)
        : String(index + 1);
      const second = document.createElement("td");
      second.textContent = kind === "EXPRESS" ? `${row.pickup_identifier}${row.outside_pickup_location ? ` · ${row.outside_pickup_location}` : ""}` : row;
      const last = document.createElement("td");
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn btn-sm btn-outline-danger";
      remove.textContent = "×";
      remove.setAttribute("aria-label", "删除此条目");
      remove.addEventListener("click", () => { rows.splice(index, 1); sync(); });
      last.append(remove);
      tr.append(first, second, last);
      body.append(tr);
    });
    error.textContent = "";
  }
  editor.querySelectorAll("[data-cdd-add-item]").forEach((button) => button.addEventListener("click", () => {
    currentArea = button.dataset.cddAddItem;
    valueInput.value = "";
    if (sizeInput) sizeInput.value = "UNKNOWN";
    if (outsideInput) outsideInput.value = "";
    if (outsideBox) outsideBox.hidden = currentArea !== "OUTSIDE";
    dialogError.textContent = "";
    dialog.showModal();
    valueInput.focus();
  }));
  editor.querySelectorAll("[data-cdd-area-tab]").forEach((button) => button.addEventListener("click", () => {
    editor.querySelectorAll("[data-cdd-area-tab]").forEach((tab) => {
      const active = tab === button;
      tab.setAttribute("aria-selected", String(active));
      tab.classList.toggle("btn-primary", active);
      tab.classList.toggle("btn-outline-primary", !active);
    });
    editor.querySelectorAll("[data-cdd-item-area]").forEach((pane) => {
      pane.hidden = pane.dataset.cddItemArea !== button.dataset.cddAreaTab;
    });
  }));
  editor.querySelector("[data-cdd-item-cancel]").addEventListener("click", () => dialog.close());
  editor.querySelector("[data-cdd-item-confirm]").addEventListener("click", () => {
    const value = valueInput.value.trim();
    if (!value || (currentArea === "OUTSIDE" && !outsideInput.value.trim())) {
      dialogError.textContent = currentArea === "OUTSIDE" && !outsideInput.value.trim() ? "请填写校外取件地点" : "请填写标识";
      return;
    }
    if (rows.length >= 50) { dialogError.textContent = "每次最多添加 50 条"; return; }
    rows.push(kind === "EXPRESS" ? {
      pickup_area: currentArea,
      outside_pickup_location: currentArea === "OUTSIDE" ? outsideInput.value.trim() : "",
      pickup_identifier: value,
      size_class: sizeInput.value,
    } : value);
    sync();
    dialog.close();
  });
  form.addEventListener("submit", (event) => {
    if (rows.length) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    error.textContent = "请先添加至少一条取件或取餐信息";
    window.cddShowOrderValidation(form, [error.textContent]);
    error.scrollIntoView({block: "center", behavior: "smooth"});
  }, true);
  sync();
});
