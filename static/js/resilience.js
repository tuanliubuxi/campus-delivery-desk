// Weak-network helpers: explicit connectivity state, text drafts, and retryable uploads.
(() => {
  const offlineBanner = document.querySelector("[data-cdd-offline-banner]");

  function updateConnectivity() {
    if (!offlineBanner) return;
    offlineBanner.hidden = navigator.onLine;
  }

  window.addEventListener("online", updateConnectivity);
  window.addEventListener("offline", updateConnectivity);
  updateConnectivity();

  function storage(action, key, value) {
    try {
      if (action === "get") return window.localStorage.getItem(key);
      if (action === "set") window.localStorage.setItem(key, value);
      if (action === "remove") window.localStorage.removeItem(key);
    } catch (_error) {
      // Private browsing or a full quota must not prevent the underlying HTML form from working.
    }
    return null;
  }

  function draftKey(form, index) {
    const explicit = form.dataset.cddDraftKey || `${window.location.pathname}:${index}`;
    return `cdd-draft:v1:${explicit}`;
  }

  function draftFields(form) {
    return [...form.elements].filter((field) => {
      if (!field.name || field.disabled || field.hasAttribute("data-cdd-draft-ignore")) return false;
      if (["password", "file", "submit", "button"].includes(field.type)) return false;
      if (field.name === "csrfmiddlewaretoken") return false;
      return field.matches("input, textarea, select");
    });
  }

  function captureDraft(form) {
    const values = {};
    const fields = draftFields(form);
    for (const field of fields) {
      const group = fields.filter((candidate) => candidate.name === field.name);
      if (field.type === "radio") {
        const checked = group.find((candidate) => candidate.checked);
        values[field.name] = checked ? checked.value : null;
      } else if (field.type === "checkbox" && group.length > 1) {
        values[field.name] = group.filter((candidate) => candidate.checked).map((item) => item.value);
      } else if (field.type === "checkbox") {
        values[field.name] = field.checked;
      } else if (field.multiple) {
        values[field.name] = [...field.selectedOptions].map((option) => option.value);
      } else {
        values[field.name] = field.value;
      }
    }
    return values;
  }

  function restoreDraft(form, values) {
    for (const field of draftFields(form)) {
      if (!(field.name in values)) continue;
      if (field.type === "radio") {
        field.checked = field.value === values[field.name];
      } else if (field.type === "checkbox" && Array.isArray(values[field.name])) {
        field.checked = values[field.name].includes(field.value);
      } else if (field.type === "checkbox") {
        field.checked = Boolean(values[field.name]);
      } else if (field.multiple && Array.isArray(values[field.name])) {
        for (const option of field.options) option.selected = values[field.name].includes(option.value);
      } else {
        field.value = values[field.name];
      }
      field.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  document.querySelectorAll("form[data-cdd-draft]").forEach((form, index) => {
    const key = draftKey(form, index);
    const saved = storage("get", key);
    if (saved) {
      try {
        restoreDraft(form, JSON.parse(saved));
      } catch (_error) {
        storage("remove", key);
      }
    }

    let timer;
    const save = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(
        () => storage("set", key, JSON.stringify(captureDraft(form))),
        150,
      );
    };
    form.addEventListener("input", save);
    form.addEventListener("change", save);

    const controls = document.createElement("div");
    controls.className = "cdd-draft-controls small text-secondary mt-2";
    controls.innerHTML = '<span>文本草稿会保存在当前设备。</span> <button type="button" class="btn btn-sm btn-outline-secondary ms-1">清除草稿</button>';
    controls.querySelector("button").addEventListener("click", () => {
      storage("remove", key);
      controls.querySelector("span").textContent = "本地草稿已清除。";
    });
    form.appendChild(controls);

    if (!form.matches("[data-cdd-resilient-submit]")) return;
    const completionStatusUrl = form.dataset.cddCompletionStatusUrl;
    const reconcile = async () => {
      if (!completionStatusUrl) return false;
      const operationId = form.querySelector('[name="operation_id"]')?.value;
      if (!operationId) return false;
      const response = await fetch(`${completionStatusUrl}?operation_id=${encodeURIComponent(operationId)}`, {credentials: "same-origin"});
      if (response.redirected && new URL(response.url).pathname.startsWith("/login/")) {
        throw new Error("login-required");
      }
      if (!response.ok) return false;
      const result = await response.json();
      if (result.state !== "completed") return false;
      storage("remove", key);
      window.location.assign(result.redirect_url);
      return true;
    };
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (form.dataset.cddSubmitting === "1") return;
      form.dataset.cddSubmitting = "1";
      const submitter = event.submitter;
      const buttons = [...form.querySelectorAll('button:not([type]), button[type="submit"], input[type="submit"]')];
      const status = form.querySelector("[data-cdd-submit-status]") || document.createElement("div");
      status.dataset.cddSubmitStatus = "";
      status.className = "alert alert-info mt-3";
      status.setAttribute("role", "status");
      if (!status.parentElement) form.appendChild(status);
      status.textContent = "正在提交，请勿重复操作……";
      buttons.forEach((button) => (button.disabled = true));
      try {
        if (await reconcile()) return;
        if (form.id === "drop-form" && window.cddCompressDeliveryImages) {
          status.textContent = "正在压缩照片，请勿离开页面……";
          await window.cddCompressDeliveryImages(form);
        }
        status.textContent = "正在上传并提交，请勿重复操作……";
        const payload = new FormData(form);
        if (submitter?.name) payload.append(submitter.name, submitter.value);
        const response = await fetch(form.action || window.location.href, {
          method: (form.method || "post").toUpperCase(),
          body: payload,
          credentials: "same-origin",
          headers: { "X-CDD-Resilient-Submit": "1" },
        });
        const target = new URL(response.url, window.location.href);
        if (response.redirected && target.pathname.startsWith("/login/")) {
          status.className = "alert alert-danger mt-3";
          status.textContent = "登录已失效；当前表单和已选图片仍保留，请在新页面重新登录后再提交。";
          return;
        }
        if (response.redirected) {
          storage("remove", key);
          window.location.assign(response.url);
          return;
        }
        if (!response.ok && await reconcile()) return;
        const responseText = await response.text();
        const parsed = new DOMParser().parseFromString(responseText, "text/html");
        const errors = [...parsed.querySelectorAll(".errorlist, .alert-danger")]
          .map((node) => node.textContent.trim())
          .filter(Boolean);
        status.className = "alert alert-danger mt-3";
        if (errors.length) status.textContent = errors.join("；");
        else if (response.status === 403) status.textContent = "安全校验已失效；表单和图片仍保留，请刷新页面后重试。";
        else if (response.status >= 500) status.textContent = "服务器处理失败；表单和图片仍保留，请稍后重试或联系管理员查看日志。";
        else status.textContent = "提交未成功；表单和图片仍保留，请检查必填项后重试。";
      } catch (error) {
        status.className = "alert alert-warning mt-3";
        // A proxy timeout can happen after the server committed the idempotent delivery.
        // Reconcile before the user tries a second submission.
        if (error.message !== "login-required") {
          try {
            if (await reconcile()) return;
          } catch (_ignored) {
            // The tunnel may still be unavailable; keep the form intact.
          }
        }
        status.textContent = error.message === "login-required"
          ? "登录已失效；请重新登录，返回此页前不要关闭它。"
          : "网络连接失败，提交结果尚未确认；表单和图片仍保留。恢复网络后点击提交会先核对结果，不会重复配送。";
      } finally {
        delete form.dataset.cddSubmitting;
        buttons.forEach((button) => (button.disabled = false));
      }
    });
  });

  // Non-enhanced POST forms still receive a simple double-click guard.
  document.querySelectorAll('form[method="post"]:not([data-cdd-resilient-submit])').forEach((form) => {
    form.addEventListener("submit", () => {
      form.querySelectorAll('button:not([type]), button[type="submit"], input[type="submit"]').forEach((button) => {
        button.disabled = true;
      });
    });
  });
})();
