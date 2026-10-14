// Select one existing image at a time, while preserving up to four per evidence class.
(() => {
  const dialog = document.getElementById("exception-evidence-picker");
  if (!dialog) return;
  const attachmentInput = document.querySelector('input[name="attachments"]');
  attachmentInput?.addEventListener("change", () => {
    if (attachmentInput.files.length > 4) {
      attachmentInput.value = "";
      window.alert("异常图片最多上传 4 张，请重新选择。");
    }
  });
  const dateInput = document.getElementById("exception-evidence-date");
  const taskSelect = document.getElementById("exception-evidence-task");
  const list = document.getElementById("exception-evidence-list");
  const confirm = document.getElementById("exception-evidence-confirm");
  const title = document.getElementById("exception-evidence-title");
  const previous = document.getElementById("exception-evidence-prev");
  const next = document.getElementById("exception-evidence-next");
  const pageLabel = document.getElementById("exception-evidence-page");
  const fields = {
    delivery: {name: "delivery_evidence", box: document.getElementById("exception-selected-delivery")},
    consolidation: {name: "media_evidence", box: document.getElementById("exception-selected-consolidation")},
  };
  let kind = "delivery";
  let rows = [];

  function selectedInputs(field) {
    return [...field.box.querySelectorAll(`input[name="${field.name}"]`)];
  }
  function addChip(field, input, row) {
    const chip = document.createElement("div");
    chip.className = "d-flex align-items-center gap-2 border rounded p-2 my-1";
    const image = document.createElement("img");
    if (row?.url) image.src = row.url;
    image.alt = "已选证据预览";
    image.style.cssText = "width:72px;height:72px;object-fit:contain";
    const caption = document.createElement("span");
    caption.className = "small flex-grow-1";
    caption.textContent = row?.label || `已选图片 #${input.value}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn btn-outline-danger btn-sm";
    remove.textContent = "×";
    remove.setAttribute("aria-label", "取消引用这张图片");
    remove.addEventListener("click", () => { input.remove(); chip.remove(); });
    chip.append(image, caption, remove);
    field.box.appendChild(chip);
  }
  for (const field of Object.values(fields)) {
    for (const input of selectedInputs(field)) addChip(field, input, null);
  }
  for (const [key, field] of Object.entries(fields)) {
    const ids = selectedInputs(field).map((input) => input.value);
    if (!ids.length) continue;
    const url = new URL(dialog.dataset.apiUrl, location.href);
    url.searchParams.set("kind", key);
    url.searchParams.set("ids", ids.join(","));
    fetch(url, {credentials: "same-origin"}).then((response) => response.json()).then((data) => {
      for (const row of data.evidence || []) {
        const input = selectedInputs(field).find((item) => item.value === String(row.id));
        const chip = input?.nextElementSibling;
        if (chip) { chip.querySelector("img").src = row.url; chip.querySelector("span").textContent = row.label; }
      }
    }).catch(() => {});
  }
  function render(items) {
    list.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "cdd-muted";
      empty.textContent = "这一天没有可引用的图片。";
      list.appendChild(empty);
      return;
    }
    for (const item of items) {
      const row = document.createElement("label");
      row.className = "d-flex gap-2 align-items-center border-bottom p-2";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "exception-evidence-choice";
      radio.value = item.id;
      radio.className = "form-check-input flex-shrink-0";
      const image = document.createElement("img");
      image.src = item.url;
      image.alt = item.label;
      image.loading = "lazy";
      image.style.cssText = "width:92px;height:92px;object-fit:contain";
      const copy = document.createElement("span");
      copy.className = "small";
      copy.textContent = `${item.label} · ${item.time}`;
      row.append(radio, image, copy);
      list.appendChild(row);
    }
  }
  async function loadChoices(keepTask = false, requestedPage = 1) {
    const url = new URL(dialog.dataset.apiUrl, location.href);
    url.searchParams.set("kind", kind);
    url.searchParams.set("date", dateInput.value);
    url.searchParams.set("page", String(requestedPage));
    if (keepTask && taskSelect.value) url.searchParams.set("task", taskSelect.value);
    list.textContent = "正在读取图片……";
    try {
      const response = await fetch(url, {credentials: "same-origin"});
      if (!response.ok || response.redirected) throw new Error("读取失败");
      const data = await response.json();
      rows = data.evidence;
      pageLabel.textContent = `第 ${data.page} / ${data.pages} 页，共 ${data.count} 张`;
      previous.hidden = !data.has_previous;
      next.hidden = !data.has_next;
      previous.dataset.page = String(data.page - 1);
      next.dataset.page = String(data.page + 1);
      if (!keepTask) {
        taskSelect.replaceChildren(new Option("当天全部", ""));
        for (const task of data.tasks) taskSelect.add(new Option(task.label, task.id));
      }
      render(rows);
    } catch (_error) {
      list.textContent = "无法读取证据，请检查网络后重试。";
    }
  }
  document.querySelectorAll("[data-cdd-evidence-open]").forEach((button) => {
    button.addEventListener("click", () => {
      kind = button.dataset.cddEvidenceOpen;
      title.textContent = kind === "delivery" ? "引用已有配送证据" : "引用已有归拢图片";
      taskSelect.replaceChildren(new Option("当天全部", ""));
      dialog.showModal();
      loadChoices();
    });
  });
  dateInput.addEventListener("change", () => loadChoices());
  taskSelect.addEventListener("change", () => loadChoices(true));
  previous.addEventListener("click", () => loadChoices(true, Number(previous.dataset.page)));
  next.addEventListener("click", () => loadChoices(true, Number(next.dataset.page)));
  confirm.addEventListener("click", () => {
    const choice = list.querySelector('input[name="exception-evidence-choice"]:checked');
    if (!choice) return;
    const field = fields[kind];
    const current = selectedInputs(field);
    if (current.some((input) => input.value === choice.value)) {
      dialog.close();
      return;
    }
    if (current.length >= 4) {
      alert("这一类证据最多引用 4 张，请先移除一张。");
      return;
    }
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = field.name;
    input.value = choice.value;
    field.box.appendChild(input);
    addChip(field, input, rows.find((item) => String(item.id) === choice.value));
    dialog.close();
  });
})();
