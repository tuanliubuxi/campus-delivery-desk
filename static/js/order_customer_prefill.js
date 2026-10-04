// Prefill order-only address snapshots from the selected customer master record.
document.addEventListener("DOMContentLoaded", () => {
  const customer = document.getElementById("id_customer");
  if (!customer) return;
  customer.addEventListener("change", async () => {
    if (!customer.value) return;
    try {
      const response = await fetch(`/recorder/customers/${customer.value}/profile.json`, {
        credentials: "same-origin",
        headers: {Accept: "application/json"},
      });
      if (!response.ok) return;
      const profile = await response.json();
      const building = document.getElementById("id_building");
      const floor = document.getElementById("id_floor");
      const room = document.getElementById("id_room");
      const destination = document.getElementById("id_destination_type");
      if (building) building.value = profile.building_id || "";
      if (floor) floor.value = profile.floor || "";
      if (room) room.value = profile.room || "";
      if (destination && profile.building_id) destination.value = "CAMPUS_BUILDING";
      [building, floor, room, destination].forEach((field) => {
        if (field) field.dispatchEvent(new Event("change", {bubbles: true}));
      });
    } catch (_error) {
      // The form remains editable if this convenience request is interrupted.
    }
  });
});
