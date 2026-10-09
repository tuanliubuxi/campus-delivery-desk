(() => {
  const form = document.getElementById("drop-form");
  const trigger = form?.querySelector("[data-cdd-complete-trigger]");
  const dialog = document.getElementById("size-confirm-dialog");
  if (!form || !trigger || !dialog) return;

  const selectedUnknown = () => [...dialog.querySelectorAll("[data-cdd-size-order-id]")].filter((section) => {
    const id = section.dataset.cddSizeOrderId;
    return form.querySelector(`input[name="order_ids"][value="${id}"]`)?.checked;
  });
  trigger.addEventListener("click", () => {
    const pending = selectedUnknown();
    if (pending.length) {
      dialog.querySelectorAll("[data-cdd-size-order-id]").forEach((section) => {
        section.hidden = !pending.includes(section);
      });
      dialog.showModal();
    } else {
      form.requestSubmit();
    }
  });
  dialog.querySelector("[data-cdd-size-confirm]").addEventListener("click", () => {
    const missing = selectedUnknown().find((section) => !section.querySelector("select")?.value);
    const warning = dialog.querySelector("[data-cdd-size-warning]");
    warning.hidden = !missing;
    if (missing) {
      missing.querySelector("select")?.focus();
      return;
    }
    dialog.close();
    form.requestSubmit();
  });
})();
