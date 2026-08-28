(function () {
  "use strict";

  function dialogById(id) {
    if (!id) {
      return null;
    }
    return document.getElementById(id);
  }

  document.addEventListener("click", function (event) {
    const openButton = event.target.closest("[data-dialog-target]");
    if (openButton) {
      const dialog = dialogById(openButton.getAttribute("data-dialog-target"));
      if (dialog && typeof dialog.showModal === "function") {
        dialog.showModal();
      }
      return;
    }

    const closeButton = event.target.closest("[data-dialog-close]");
    if (closeButton) {
      const dialog = dialogById(closeButton.getAttribute("data-dialog-close"));
      if (dialog && typeof dialog.close === "function") {
        dialog.close();
      }
    }
  });
})();
