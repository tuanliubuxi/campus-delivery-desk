document.addEventListener("DOMContentLoaded", () => {
  const dialog = document.getElementById("customer-picker");
  const select = document.getElementById("id_customer");
  if (!dialog || !select) return;
  const query = dialog.querySelector("#customer-picker-query");
  const building = dialog.querySelector("#customer-picker-building");
  const results = dialog.querySelector("[data-customer-picker-results]");
  const message = dialog.querySelector("[data-customer-picker-message]");
  const confirm = dialog.querySelector("[data-customer-picker-confirm]");
  let mode = "search";
  let selected = "";
  document.querySelectorAll("[data-cdd-customer-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      mode = button.dataset.cddCustomerMode;
      selected = "";
      results.replaceChildren();
      confirm.disabled = true;
      message.textContent = "";
      dialog.querySelector("[data-customer-picker-title]").textContent = mode === "building" ? "按楼栋找客户" : "搜索客户";
      dialog.querySelector("[data-customer-search-field]").hidden = mode !== "search";
      dialog.querySelector("[data-customer-building-field]").hidden = mode !== "building";
    });
  });
  dialog.querySelector("[data-customer-picker-search]").addEventListener("click", async () => {
    const url = new URL(dialog.dataset.customerPickerUrl, window.location.origin);
    const value = mode === "building" ? building.value : query.value.trim();
    if (!value) { message.textContent = mode === "building" ? "请先选择楼栋" : "请输入客户名称或手机尾号"; return; }
    url.searchParams.set(mode === "building" ? "building" : "q", value);
    selected = "";
    confirm.disabled = true;
    results.replaceChildren();
    message.textContent = "正在查找…";
    try {
      const response = await fetch(url, {credentials: "same-origin", headers: {Accept: "application/json"}});
      if (!response.ok) throw new Error("查询暂时失败，请稍后重试");
      const data = await response.json();
      message.textContent = data.results.length ? `找到 ${data.results.length} 位客户（最多显示 100 位）` : "没有匹配客户";
      data.results.forEach((customer) => {
        const label = document.createElement("label");
        label.className = "cdd-customer-picker-option";
        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "customer-picker-selection";
        radio.value = String(customer.id);
        radio.addEventListener("change", () => { selected = radio.value; confirm.disabled = false; });
        const detail = document.createElement("span");
        detail.className = "cdd-min-width-zero cdd-ellipsis";
        detail.textContent = `${customer.name} · ${customer.recipients || "未填收件人"} · ${customer.phone || "无尾号"} · ${customer.building}`;
        detail.title = detail.textContent;
        label.append(radio, detail);
        results.append(label);
      });
    } catch (error) { message.textContent = error.message; }
  });
  query.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); dialog.querySelector("[data-customer-picker-search]").click(); }
  });
  confirm.addEventListener("click", () => {
    if (!selected) return;
    select.value = selected;
    select.dispatchEvent(new Event("change", {bubbles: true}));
    dialog.close();
  });
});
