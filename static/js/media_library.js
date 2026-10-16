// Use one reason dialog for bulk and single-file deletion without losing the selection.
document.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-cdd-media-delete]");
  if (!trigger) return;
  const form = document.getElementById("media-delete-form");
  const dialog = document.getElementById("media-delete-reason");
  const confirm = dialog.querySelector("[data-cdd-media-delete-confirm]");
  if (trigger.dataset.cddMediaDelete === "bulk") {
    const selected = form.querySelectorAll('input[name="media_ids"]:checked').length;
    if (!selected) {
      window.alert("请先选择至少一个媒体文件。");
      return;
    }
    confirm.removeAttribute("formaction");
    dialog.querySelector("[data-cdd-media-delete-summary]").textContent =
      `将删除选中的 ${selected} 个文件；业务记录会保留。`;
  } else {
    confirm.setAttribute("formaction", trigger.dataset.cddMediaDeleteUrl);
    dialog.querySelector("[data-cdd-media-delete-summary]").textContent =
      `将删除媒体 ${trigger.dataset.cddMediaDeleteLabel}；业务记录会保留。`;
  }
  dialog.querySelector('input[name="reason"]').value = "";
  dialog.showModal();
});
