(function () {
  "use strict";

  function dialogById(id) {
    if (!id) {
      return null;
    }
    return document.getElementById(id);
  }

  function returnToParent(dialog) {
    const backButton = dialog && dialog.querySelector("[data-dialog-back]");
    if (!backButton) {
      return false;
    }
    backButton.click();
    return true;
  }

  document.addEventListener("click", function (event) {
    const openButton = event.target.closest("[data-dialog-target]");
    if (openButton) {
      const dialog = dialogById(openButton.getAttribute("data-dialog-target"));
      if (dialog && !dialog.open && typeof dialog.showModal === "function") {
        dialog.showModal();
      }
      const card = dialog && dialog.querySelector(".comparison-dialog-card");
      if (card) {
        card.scrollTop = 0;
      }
      return;
    }

    const closeButton = event.target.closest("[data-dialog-close]");
    if (closeButton) {
      const dialog = dialogById(closeButton.getAttribute("data-dialog-close"));
      if (dialog && !returnToParent(dialog) && typeof dialog.close === "function") {
        dialog.close();
      }
    }
  });

  document.addEventListener("cancel", function (event) {
    if (event.target.id === "schema-changes-dialog" && returnToParent(event.target)) {
      event.preventDefault();
    }
  }, true);
})();
