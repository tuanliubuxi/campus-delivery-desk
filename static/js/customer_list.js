document.addEventListener("DOMContentLoaded", () => {
  const dialog = document.getElementById("customer-create-order");
  const business = document.getElementById("customer-order-business");
  const confirm = dialog?.querySelector("[data-customer-create-confirm]");
  if (!dialog || !business || !confirm) return;
  let customerId = "";
  document.querySelectorAll("[data-customer-order-id]").forEach((button) => {
    button.addEventListener("click", () => {
      customerId = button.dataset.customerOrderId;
      dialog.querySelector("[data-customer-create-name]").textContent = button.dataset.customerOrderName;
      business.value = "";
      confirm.disabled = true;
    });
  });
  business.addEventListener("change", () => { confirm.disabled = !business.value; });
  confirm.addEventListener("click", () => {
    if (!customerId || !business.value) return;
    const target = new URL(business.value, window.location.origin);
    target.searchParams.set("customer", customerId);
    // A new card action starts a fresh draft, while reloads of this URL keep that draft.
    target.searchParams.set("entry", String(Date.now()));
    window.location.assign(target.toString());
  });
});
