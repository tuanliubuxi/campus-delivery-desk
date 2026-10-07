/* Touch-friendly vector annotation editor shared by delivery and consolidation evidence. */
document.addEventListener("DOMContentLoaded", () => {
  const farInput = document.getElementById("id_far_photo");
  const annotatedInput = document.getElementById("id_annotated_photo")
    || document.getElementById("id_far_annotation");
  const tools = document.getElementById("annotation-tools");
  const canvas = document.getElementById("annotation-canvas");
  const dialog = document.getElementById("annotation-dialog");
  const openButton = document.getElementById("annotation-open");
  if (!farInput || !annotatedInput || !tools || !canvas || !dialog || !openButton) return;
  const context = canvas.getContext("2d");
  const shapeInput = document.getElementById("annotation-shape");
  const colorInput = document.getElementById("annotation-color");
  const widthInput = document.getElementById("annotation-width");
  const status = document.getElementById("annotation-status");
  const actions = [];
  let baseImage = null;
  let draft = null;
  let savedActions = [];
  let savedFile = null;
  let committed = false;

  function restoreSavedFile() {
    const files = new DataTransfer();
    if (savedFile) files.items.add(savedFile);
    annotatedInput.files = files.files;
  }

  openButton.addEventListener("click", () => {
    if (!baseImage) return;
    savedActions = actions.map((action) => ({...action, start: {...action.start}, end: {...action.end}}));
    savedFile = annotatedInput.files[0] || null;
    committed = false;
    dialog.showModal();
    redraw();
  });
  document.getElementById("annotation-cancel").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    if (committed) return;
    actions.splice(0, actions.length, ...savedActions);
    draft = null;
    restoreSavedFile();
    status.textContent = savedFile ? "已保留上次保存的标注。" : "未保存的标记已取消。";
    redraw();
  });

  const pointFromEvent = (event) => {
    const box = canvas.getBoundingClientRect();
    return {x: (event.clientX - box.left) * canvas.width / box.width,
      y: (event.clientY - box.top) * canvas.height / box.height};
  };
  function drawAction(action) {
    const {start, end, shape, color, width} = action;
    context.strokeStyle = color;
    context.lineWidth = width;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.beginPath();
    if (shape === "line") {
      context.moveTo(start.x, start.y);
      context.lineTo(end.x, end.y);
    } else if (shape === "rect") {
      context.rect(start.x, start.y, end.x - start.x, end.y - start.y);
    } else {
      context.ellipse((start.x + end.x) / 2, (start.y + end.y) / 2,
        Math.abs(end.x - start.x) / 2, Math.abs(end.y - start.y) / 2,
        0, 0, Math.PI * 2);
    }
    context.stroke();
  }
  function redraw() {
    if (!baseImage) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(baseImage, 0, 0, canvas.width, canvas.height);
    actions.forEach(drawAction);
    if (draft) drawAction(draft);
  }
  function resetDerivedImage(message = "") {
    actions.splice(0);
    draft = null;
    annotatedInput.value = "";
    status.textContent = message;
  }
  farInput.addEventListener("change", (event) => {
    // Replacing the same image with its compressed upload must not erase a saved annotation.
    if (event.detail?.cddCompressed) return;
    const file = farInput.files[0];
    resetDerivedImage();
    openButton.hidden = true;
    baseImage = null;
    if (!file) return;
    const image = new Image();
    const objectUrl = URL.createObjectURL(file);
    image.onload = () => {
      if (farInput.files[0] !== file) { URL.revokeObjectURL(objectUrl); return; }
      baseImage = image;
      const scale = Math.min(1, 1200 / image.naturalWidth);
      canvas.width = Math.round(image.naturalWidth * scale);
      canvas.height = Math.round(image.naturalHeight * scale);
      redraw();
      openButton.hidden = false;
      status.textContent = "请在图片上按住并拖动，松开后生成标记。";
      URL.revokeObjectURL(objectUrl);
    };
    image.onerror = () => {
      status.textContent = "无法读取远景照片，请重新选择图片。";
      URL.revokeObjectURL(objectUrl);
    };
    image.src = objectUrl;
  });
  canvas.addEventListener("pointerdown", (event) => {
    if (!baseImage || event.button > 0) return;
    event.preventDefault();
    canvas.setPointerCapture(event.pointerId);
    const start = pointFromEvent(event);
    draft = {start, end: start, shape: shapeInput.value, color: colorInput.value,
      width: Number(widthInput.value)};
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!draft || !canvas.hasPointerCapture(event.pointerId)) return;
    draft.end = pointFromEvent(event);
    redraw();
  });
  const finishDrawing = (event) => {
    if (!draft) return;
    const end = pointFromEvent(event);
    draft.end = end;
    if (Math.hypot(end.x - draft.start.x, end.y - draft.start.y) >= 6) actions.push(draft);
    draft = null;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    annotatedInput.value = "";
    status.textContent = actions.length ? "标记已修改，请点击“保存标注”。" : "拖动距离太短，未创建标记。";
    redraw();
  };
  canvas.addEventListener("pointerup", finishDrawing);
  canvas.addEventListener("pointercancel", () => { draft = null; redraw(); });
  document.getElementById("annotation-undo").addEventListener("click", () => {
    actions.pop(); annotatedInput.value = "";
    status.textContent = actions.length ? "已撤销一步，请重新保存标注。" : "所有标记已撤销。";
    redraw();
  });
  document.getElementById("annotation-clear").addEventListener("click", () => {
    resetDerivedImage("标记已清空。原始远景照片仍保留。"); redraw();
  });
  document.getElementById("annotation-save").addEventListener("click", () => {
    if (!actions.length) {
      if (savedFile) {
        annotatedInput.value = "";
        status.textContent = "已移除原有标注，远景原图仍保留。";
        committed = true;
        dialog.close();
      } else {
        status.textContent = "尚未绘制标记；请拖动绘制后再保存。";
      }
      return;
    }
    redraw();
    canvas.toBlob((blob) => {
      if (!dialog.open) return;
      if (!blob) { status.textContent = "浏览器未能生成标注图，请重试。"; return; }
      const files = new DataTransfer();
      files.items.add(new File([blob], "annotated.jpg", {type: "image/jpeg"}));
      annotatedInput.files = files.files;
      status.textContent = "标注图已保存并加入上传列表。";
      committed = true;
      dialog.close();
    }, "image/jpeg", 0.9);
  });
});
