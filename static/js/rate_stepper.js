// Wage rates are hundredth fractions, not integer quantities or 0–100 inputs.
(() => {
  const selector = 'input[data-cdd-rate-stepper][type="number"]';
  function upgrade(root) {
    const inputs = root.matches?.(selector) ? [root] : [...(root.querySelectorAll?.(selector) || [])];
    for (const input of inputs) {
      if (input.closest(".cdd-rate-stepper")) continue;
      const wrapper = document.createElement("div");
      wrapper.className = "cdd-rate-stepper";
      input.before(wrapper);
      wrapper.append(input);
      const buttons = [];
      for (const [label, delta] of [["减少计薪比例", -1], ["增加计薪比例", 1]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `cdd-stepper-button cdd-stepper-button--${delta < 0 ? "minus" : "plus"}`;
        button.textContent = delta < 0 ? "−" : "+";
        button.setAttribute("aria-label", label);
        button.addEventListener("click", () => {
          const hundredths = input.value === "" ? 0 : Math.round(Number(input.value) * 100);
          const next = Math.max(0, Math.min(100, hundredths + delta));
          input.value = (next / 100).toFixed(2);
          input.dispatchEvent(new Event("input", {bubbles: true}));
          input.dispatchEvent(new Event("change", {bubbles: true}));
        });
        if (delta < 0) wrapper.prepend(button);
        else wrapper.append(button);
        buttons.push(button);
      }
      const mode = input.form?.querySelector('[name="rate_mode"]');
      function sync() {
        const inherited = mode?.value === "default";
        input.disabled = Boolean(inherited);
        wrapper.hidden = Boolean(inherited);
        buttons.forEach((button) => { button.disabled = Boolean(inherited); });
      }
      mode?.addEventListener("change", sync);
      sync();
    }
  }
  upgrade(document);
  new MutationObserver((records) => {
    for (const record of records) for (const node of record.addedNodes) {
      if (node.nodeType === Node.ELEMENT_NODE) upgrade(node);
    }
  }).observe(document.body, {childList: true, subtree: true});
})();
