(function () {
  "use strict";

  const graphId = "node-category-contribution-chart";
  let pointerStart = null;
  let resetSequence = 0;

  document.addEventListener("pointerdown", function (event) {
    pointerStart = { x: event.clientX, y: event.clientY };
  });

  document.addEventListener("click", function (event) {
    const root = document.getElementById(graphId);
    if (!root || !root.contains(event.target)) {
      return;
    }
    if (event.target.closest(".barlayer .point, .modebar")) {
      return;
    }
    const bars = root.querySelectorAll(".barlayer .point path");
    for (const bar of bars) {
      const bounds = bar.getBoundingClientRect();
      if (bounds.width > 0 && bounds.height > 0 &&
          event.clientX >= bounds.left && event.clientX <= bounds.right &&
          event.clientY >= bounds.top && event.clientY <= bounds.bottom) {
        return;
      }
    }
    if (pointerStart && Math.hypot(
      event.clientX - pointerStart.x, event.clientY - pointerStart.y
    ) > 5) {
      return;
    }
    if (window.dash_clientside && window.dash_clientside.set_props) {
      resetSequence += 1;
      window.dash_clientside.set_props(graphId, {
        clickData: { reset: true, sequence: resetSequence }
      });
    }
  });
})();
