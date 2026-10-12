// Keep optional count fields out of the way until an eligible order needs upstairs service.
(() => {
  const checkbox = document.getElementById("id_requires_upstairs");
  if (!checkbox) return;
  const fields = document.querySelectorAll("[data-cdd-upstairs-count]");
  if (!fields.length) return;
  const refresh = () => fields.forEach((field) => { field.hidden = !checkbox.checked; });
  checkbox.addEventListener("change", refresh);
  refresh();
})();
