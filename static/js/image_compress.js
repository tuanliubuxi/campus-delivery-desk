// Compress mobile evidence before upload; originals never leave the current form.
(() => {
  const LIMIT = 1920;
  const QUALITY = 0.82;
  async function compress(file) {
    if (!file.type.startsWith("image/")) return file;
    const bitmap = await createImageBitmap(file);
    const ratio = Math.min(1, LIMIT / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * ratio);
    canvas.height = Math.round(bitmap.height * ratio);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/webp", QUALITY));
    bitmap.close();
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], `${file.name.replace(/\.[^.]+$/, "")}.webp`, {type: "image/webp", lastModified: file.lastModified});
  }
  document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("drop-form");
    if (!form) return;
    form.addEventListener("submit", async (event) => {
      if (form.dataset.cddImagesCompressed === "1") return;
      event.preventDefault();
      const inputs = [...form.querySelectorAll('input[type="file"]')].filter((input) => input.files?.length);
      if (!inputs.length) { form.dataset.cddImagesCompressed = "1"; form.requestSubmit(event.submitter); return; }
      try {
        for (const input of inputs) {
          const transfer = new DataTransfer();
          for (const file of input.files) transfer.items.add(await compress(file));
          input.files = transfer.files;
          input.dispatchEvent(new Event("change", {bubbles: true}));
        }
      } finally {
        form.dataset.cddImagesCompressed = "1";
        form.requestSubmit(event.submitter);
      }
    }, true);
  });
})();
