/* Minimal far-photo annotation tool: click to circle, clear, then export a derived JPEG. */
document.addEventListener("DOMContentLoaded", () => {
  const farInput = document.getElementById("id_far_photo");
  // Delivery and consolidation forms use different field names but the same derived-image flow.
  const annotatedInput = document.getElementById("id_annotated_photo")
    || document.getElementById("id_far_annotation");
  const tools = document.getElementById("annotation-tools");
  const canvas = document.getElementById("annotation-canvas");
  if (!farInput || !annotatedInput || !tools || !canvas) return;
  const context = canvas.getContext("2d");
  let baseImage = null;

  function drawBase() {
    if (!baseImage) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(baseImage, 0, 0, canvas.width, canvas.height);
  }

  farInput.addEventListener("change", () => {
    const file = farInput.files[0];
    if (!file) { tools.hidden = true; return; }
    const image = new Image();
    image.onload = () => {
      baseImage = image;
      const scale = Math.min(1, 900 / image.naturalWidth);
      canvas.width = Math.round(image.naturalWidth * scale);
      canvas.height = Math.round(image.naturalHeight * scale);
      drawBase();
      tools.hidden = false;
      URL.revokeObjectURL(image.src);
    };
    image.src = URL.createObjectURL(file);
  });

  canvas.addEventListener("click", (event) => {
    const box = canvas.getBoundingClientRect();
    const x = (event.clientX - box.left) * canvas.width / box.width;
    const y = (event.clientY - box.top) * canvas.height / box.height;
    context.strokeStyle = "#ff1f1f";
    context.lineWidth = Math.max(4, canvas.width / 180);
    context.beginPath();
    context.arc(x, y, Math.max(25, canvas.width / 14), 0, Math.PI * 2);
    context.stroke();
  });
  document.getElementById("annotation-clear").addEventListener("click", drawBase);
  document.getElementById("annotation-save").addEventListener("click", () => {
    canvas.toBlob((blob) => {
      const files = new DataTransfer();
      files.items.add(new File([blob], "annotated.jpg", {type: "image/jpeg"}));
      annotatedInput.files = files.files;
    }, "image/jpeg", 0.9);
  });
});
