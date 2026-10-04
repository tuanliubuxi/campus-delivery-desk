// Show selected evidence files and let the courier remove an accidental selection.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-file-list-for]").forEach((list) => {
    const input = document.getElementById(list.dataset.fileListFor);
    if (!input) return;

    const render = () => {
      list.replaceChildren();
      [...input.files].forEach((file, index) => {
        const item = document.createElement("li");
        item.className = "cdd-file-item";
        const name = document.createElement("span");
        name.className = "cdd-file-name";
        name.textContent = file.name;
        name.title = file.name;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn btn-sm btn-outline-danger";
        remove.setAttribute("aria-label", `删除 ${file.name}`);
        remove.textContent = "×";
        remove.addEventListener("click", () => {
          const transfer = new DataTransfer();
          [...input.files].forEach((candidate, candidateIndex) => {
            if (candidateIndex !== index) transfer.items.add(candidate);
          });
          input.files = transfer.files;
          input.dispatchEvent(new Event("change", {bubbles: true}));
        });
        item.append(name, remove);
        list.append(item);
      });
    };
    input.addEventListener("change", render);
    render();
  });
});
