(function () {
  "use strict";

  const graphIds = [
    "source-predicate-sankey-graph",
    "subject-predicate-object-sankey-graph",
  ];
  const linkHighlightOpacity = "0.95";
  const linkDimOpacity = "0.08";
  const nodeHighlightOpacity = "1";
  const nodeDimOpacity = "0.22";

  function asArray(value) {
    if (Array.isArray(value)) {
      return value;
    }
    if (value && typeof value !== "string" && typeof value.length === "number") {
      return Array.from(value);
    }
    return [];
  }

  function connectedNodeIndexes(trace, selectedNodeIndex) {
    if (!trace || !Number.isInteger(selectedNodeIndex)) {
      return null;
    }
    const sources = asArray(trace.link && trace.link.source);
    const targets = asArray(trace.link && trace.link.target);
    const labels = asArray(trace.node && trace.node.label);
    if (
      sources.length === 0 ||
      sources.length !== targets.length ||
      labels.length === 0
    ) {
      return null;
    }
    if (selectedNodeIndex < 0 || selectedNodeIndex >= labels.length) {
      return null;
    }

    const connectedNodes = new Set([selectedNodeIndex]);
    const connectedLinks = sources.map((source, index) => {
      const isConnected =
        sources[index] === selectedNodeIndex || targets[index] === selectedNodeIndex;
      if (isConnected) {
        connectedNodes.add(sources[index]);
        connectedNodes.add(targets[index]);
      }
      return isConnected;
    });
    return { connectedLinks, connectedNodes };
  }

  function resetDomHighlight(layer) {
    sankeyLinks(layer).forEach((link) => {
      link.style.opacity = "";
      link.style.filter = "";
    });
    sankeyNodes(layer).forEach((node) => {
      node.style.opacity = "";
    });
  }

  function applyDomHighlight(layer, trace, selectedNodeIndex) {
    const connected = connectedNodeIndexes(trace, selectedNodeIndex);
    if (!connected) {
      return false;
    }
    const links = sankeyLinks(layer);
    const nodes = sankeyNodes(layer);
    if (links.length < connected.connectedLinks.length || nodes.length <= selectedNodeIndex) {
      return false;
    }
    links.slice(0, connected.connectedLinks.length).forEach((link, index) => {
      const isConnected = connected.connectedLinks[index];
      link.style.opacity = isConnected ? linkHighlightOpacity : linkDimOpacity;
      link.style.filter = isConnected ? "saturate(1.12)" : "grayscale(0.35)";
    });
    nodes.forEach((node, index) => {
      node.style.opacity = connected.connectedNodes.has(index)
        ? nodeHighlightOpacity
        : nodeDimOpacity;
    });
    return true;
  }

  function sankeyTrace(plot) {
    if (!plot || !Array.isArray(plot.data) || plot.data.length === 0) {
      return null;
    }
    const dataTrace = plot.data[0] || {};
    const fullTrace = Array.isArray(plot._fullData) && plot._fullData.length > 0
      ? plot._fullData[0] || {}
      : {};
    return {
      ...fullTrace,
      ...dataTrace,
      link: {
        ...(fullTrace.link || {}),
        ...(dataTrace.link || {}),
      },
      node: {
        ...(fullTrace.node || {}),
        ...(dataTrace.node || {}),
      },
      meta: dataTrace.meta || fullTrace.meta,
    };
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
    const layer = nodeElement.closest(".sankey") || plot;
    const datumIndex = sankeyDatumNodeIndex(nodeElement);
    if (Number.isInteger(datumIndex)) {
      return { index: datumIndex, layer };
    }
    const nodes = sankeyNodes(layer);
    const index = nodes.indexOf(nodeElement);
    return index >= 0 ? { index, layer } : null;
  }

  function sankeyDatumNodeIndex(nodeElement) {
    const candidates = [
      nodeElement.__data__,
      nodeElement.__data__ && nodeElement.__data__.node,
      nodeElement.__data__ && nodeElement.__data__.point,
      nodeElement.__data__ && nodeElement.__data__.data,
    ];
    for (const candidate of candidates) {
      if (!candidate || typeof candidate !== "object") {
        continue;
      }
      for (const key of ["pointNumber", "index", "i"]) {
        if (Number.isInteger(candidate[key])) {
          return candidate[key];
        }
      }
    }
    return null;
  }

  function sankeyNodes(layer) {
    return Array.from(layer.querySelectorAll(".sankey-node"));
  }

  function sankeyLinks(layer) {
    return Array.from(layer.querySelectorAll(".sankey-link"));
  }

  function traceSignature(trace) {
    if (!trace) {
      return "";
    }
    const labels = asArray(trace.node && trace.node.label);
    const sources = asArray(trace.link && trace.link.source);
    const targets = asArray(trace.link && trace.link.target);
    const values = asArray(trace.link && trace.link.value);
    return [
      labels.join("\u001f"),
      sources.join(","),
      targets.join(","),
      values.length,
    ].join("\u001e");
  }

  function syncTraceState(root, plot) {
    const signature = traceSignature(sankeyTrace(plot));
    if (root.__sankeyTraceSignature !== signature) {
      root.__sankeyTraceSignature = signature;
      root.__sankeySelectedNodeIndex = null;
    }
  }

  function toggleNodeSelection(root, plot, selection) {
    if (selection === null) {
      return;
    }
    syncTraceState(root, plot);
    const trace = sankeyTrace(plot);
    if (root.__sankeySelectedNodeIndex === selection.index) {
      root.__sankeySelectedNodeIndex = null;
      resetDomHighlight(selection.layer);
      return;
    }
    if (applyDomHighlight(selection.layer, trace, selection.index)) {
      root.__sankeySelectedNodeIndex = selection.index;
    }
  }

  function install(root) {
    const plot = findPlot(root);
    if (!plot) {
      return;
    }
    syncTraceState(root, plot);
    if (!root.__sankeyDomNodeClickInstalled) {
      root.__sankeyDomNodeClickInstalled = true;
      root.addEventListener("click", function (event) {
        const currentPlot = findPlot(root);
        const selection = clickedDomNodeIndex(currentPlot, event.target);
        if (selection !== null) {
          toggleNodeSelection(root, currentPlot, selection);
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
