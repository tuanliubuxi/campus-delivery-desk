// Add accessible step controls only to server-declared integer fields.
(() => {
  const selector = 'input[data-cdd-integer-stepper][type="number"]';
  const upgrade = (root) => {
    const inputs = root.matches?.(selector) ? [root] : [...(root.querySelectorAll?.(selector) || [])];
    for (const input of inputs) {
      if (input.closest(".cdd-integer-stepper")) continue;
      const wrapper = document.createElement("div");
      wrapper.className = "cdd-integer-stepper";
      input.before(wrapper);
      wrapper.append(input);
      const minimum = input.min === "" ? 0 : Number(input.min);
      const maximum = input.max === "" ? Infinity : Number(input.max);
      for (const [label, delta] of [["减少", -1], ["增加", 1]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `cdd-stepper-button cdd-stepper-button--${delta < 0 ? "minus" : "plus"}`;
        button.textContent = delta < 0 ? "−" : "+";
        button.setAttribute("aria-label", `${label}${input.labels?.[0]?.textContent?.trim() || "数量"}`);
        button.disabled = input.disabled;
        button.addEventListener("click", () => {
          const next = input.value === ""
            ? Math.min(maximum, delta > 0 ? Math.max(minimum, 1) : minimum)
            : Math.min(maximum, Math.max(minimum, Math.trunc(Number(input.value)) + delta));
          input.value = String(next);
          input.dispatchEvent(new Event("input", {bubbles: true}));
          input.dispatchEvent(new Event("change", {bubbles: true}));
        });
        if (delta < 0) wrapper.prepend(button);
        else wrapper.append(button);
      }
    }
  };
  upgrade(document);
  new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE) upgrade(node);
      }
    }
  }).observe(document.body, {childList: true, subtree: true});
})();
