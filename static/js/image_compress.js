// Compress mobile evidence before upload; originals never leave the current form.
(() => {
  const PROFILES = {
    STANDARD: {limit: 1600, quality: 0.82},
    CLEAR: {limit: 2400, quality: 0.91},
    EXTRA_CLEAR: {limit: 3200, quality: 0.95},
  };
  async function compress(file, profile) {
    if (!file.type.startsWith("image/")) return file;
    const bitmap = await createImageBitmap(file);
    const ratio = Math.min(1, profile.limit / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * ratio);
    canvas.height = Math.round(bitmap.height * ratio);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/webp", profile.quality));
    bitmap.close();
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], `${file.name.replace(/\.[^.]+$/, "")}.webp`, {type: "image/webp", lastModified: file.lastModified});
  }
  // Called by the single resilient-submit handler before it creates FormData.
  // A separate async submit listener previously let the original and compressed
  // uploads race, causing duplicate requests and misleading network errors.
  window.cddCompressDeliveryImages = async (form) => {
    if (form.dataset.cddImagesCompressed === "1") return;
    const profile = PROFILES[form.dataset.cddImageProfile] || PROFILES.STANDARD;
    const inputs = [...form.querySelectorAll('input[type="file"]')].filter((input) => input.files?.length);
    for (const input of inputs) {
      const transfer = new DataTransfer();
      for (const file of input.files) {
        try {
          transfer.items.add(await compress(file, profile));
        } catch (_error) {
          transfer.items.add(file);
        }
      }
      input.files = transfer.files;
      input.dispatchEvent(new CustomEvent("change", {bubbles: true, detail: {cddCompressed: true}}));
    }
    form.dataset.cddImagesCompressed = "1";
  };
})();
