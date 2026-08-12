(function () {
  "use strict";

  const graphIds = [
    "source-predicate-sankey-graph",
    "subject-predicate-object-sankey-graph",
  ];
  const linkAlpha = 0.35;
  const linkHighlightAlpha = 0.82;
  const linkDimAlpha = 0.06;
  const nodeDimAlpha = 0.2;

  function withAlpha(color, alpha) {
    if (typeof color !== "string") {
      return color;
    }
    if (color.startsWith("rgba(") || color.startsWith("rgb(")) {
      const rgb = color.replace(/^rgba?\(/, "").replace(/\)$/, "").split(",");
      return `rgba(${rgb[0].trim()}, ${rgb[1].trim()}, ${rgb[2].trim()}, ${alpha})`;
    }
    const match = color.match(/^#([0-9a-fA-F]{6})$/);
    if (!match) {
      return color;
    }
    const hex = match[1];
    const r = parseInt(hex.slice(0, 2), 16);
    const g = parseInt(hex.slice(2, 4), 16);
    const b = parseInt(hex.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function highlightColors(trace, selectedNodeIndex) {
    const sources = asArray(trace.link && trace.link.source);
    const targets = asArray(trace.link && trace.link.target);
    const meta = trace.meta || {};
    const baseLinkColors = asArray(meta.base_link_colors);
    const baseNodeColors = asArray(meta.base_node_colors);
    if (
      sources.length === 0 ||
      sources.length !== targets.length ||
      baseLinkColors.length !== sources.length ||
      baseNodeColors.length === 0
    ) {
      return null;
    }

    const connectedNodes = new Set([selectedNodeIndex]);
    const linkColors = baseLinkColors.map((color, index) => {
      const isConnected =
        sources[index] === selectedNodeIndex || targets[index] === selectedNodeIndex;
      if (isConnected) {
        connectedNodes.add(sources[index]);
        connectedNodes.add(targets[index]);
      }
      return withAlpha(color, isConnected ? linkHighlightAlpha : linkDimAlpha);
    });
    const nodeColors = baseNodeColors.map((color, index) =>
      connectedNodes.has(index) ? color : withAlpha(color, nodeDimAlpha)
    );
    return { linkColors, nodeColors };
  }

  function resetColors(trace) {
    const meta = trace && trace.meta ? trace.meta : {};
    const baseLinkColors = asArray(meta.base_link_colors);
    const baseNodeColors = asArray(meta.base_node_colors);
    if (baseLinkColors.length === 0 || baseNodeColors.length === 0) {
      return null;
    }
    return {
      linkColors: baseLinkColors.map((color) => withAlpha(color, linkAlpha)),
      nodeColors: baseNodeColors.slice(),
    };
  }

  function restyleSankey(plot, colors) {
    if (!plot || !colors || !window.Plotly) {
      return;
    }
    window.Plotly.restyle(
      plot,
      {
        "link.color": [colors.linkColors],
        "node.color": [colors.nodeColors],
      },
      [0]
    );
  }

  function sankeyTrace(plot) {
    return plot && Array.isArray(plot.data) && plot.data.length > 0 ? plot.data[0] : null;
  }

  function findPlot(root) {
    if (!root) {
      return null;
    }
    if (root.classList && root.classList.contains("js-plotly-plot")) {
      return root;
    }
    return root.querySelector(".js-plotly-plot");
  }

  function clickedDomNodeIndex(plot, target) {
    if (!plot || !target || typeof target.closest !== "function") {
      return null;
    }
    const nodeElement = target.closest(".sankey-node");
    if (!nodeElement || !plot.contains(nodeElement)) {
      return null;
    }
    const nodes = Array.from(plot.querySelectorAll(".sankey-node"));
    const index = nodes.indexOf(nodeElement);
    return index >= 0 ? index : null;
  }

  function toggleNodeSelection(root, plot, nodeIndex) {
    if (nodeIndex === null) {
      return;
    }
    const trace = sankeyTrace(plot);
    if (root.__sankeySelectedNodeIndex === nodeIndex) {
      root.__sankeySelectedNodeIndex = null;
      restyleSankey(plot, resetColors(trace));
      return;
    }
    root.__sankeySelectedNodeIndex = nodeIndex;
    restyleSankey(plot, highlightColors(trace, nodeIndex));
  }

  function install(root) {
    const plot = findPlot(root);
    if (!plot) {
      return;
    }
    if (!root.__sankeyDomNodeClickInstalled) {
      root.__sankeyDomNodeClickInstalled = true;
      root.addEventListener("click", function (event) {
        const currentPlot = findPlot(root);
        const nodeIndex = clickedDomNodeIndex(currentPlot, event.target);
        if (nodeIndex !== null) {
          toggleNodeSelection(root, currentPlot, nodeIndex);
        }
      });
    }
  }

  function installAll() {
    graphIds.forEach(function (id) {
      install(document.getElementById(id));
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installAll);
  } else {
    installAll();
  }
  new MutationObserver(installAll).observe(document.body, {
    childList: true,
    subtree: true,
  });
})();
