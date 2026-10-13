// Conditional order inputs stay readable while server-side forms enforce the same rules.
(() => {
  const destination = document.getElementById("id_destination_type");
  if (!destination) return;
  const upstairs = document.getElementById("id_requires_upstairs");
  const pickupArea = document.getElementById("id_pickup_area");
  const pickupGate = document.getElementById("id_pickup_gate");
  const field = (name) => document.querySelector(`[data-cdd-order-field="${name}"]`);
  const visible = (name, show) => {
    const wrapper = field(name);
    if (wrapper) wrapper.hidden = !show;
  };
  const upstairsSelected = () => upstairs?.type === "hidden"
    ? ["true", "1", "on"].includes(upstairs.value.toLowerCase())
    : Boolean(upstairs?.checked);

  function refresh() {
    const offCampus = destination.value === "OFF_CAMPUS_ADDRESS";
    const needsUpstairs = upstairsSelected();
    visible("building", !offCampus);
    visible("floor", !offCampus || needsUpstairs);
    visible("room", !offCampus || needsUpstairs);
    visible("off_campus_address", offCampus);
    visible("confirm_off_campus_upstairs", offCampus && needsUpstairs);
    visible("outside_pickup_location", pickupArea?.value === "OUTSIDE");
    visible("other_pickup_location", pickupGate?.value === "OTHER");
    visible("upstairs_small_medium_count", needsUpstairs && !offCampus);
    visible("upstairs_large_oversize_count", needsUpstairs && !offCampus);
  }
  for (const input of [destination, upstairs, pickupArea, pickupGate]) {
    input?.addEventListener("change", refresh);
  }
  refresh();
  window.addEventListener("pageshow", refresh);
})();
