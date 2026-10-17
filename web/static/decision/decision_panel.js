/* CityPilot decision panels: shared core + decision panel.
 * Mount contract (load decision_panel.js first, then stress_panel.js and co2_panel.js):
 *   const handle = window.CityPilotDecision.mount(element, {
 *     getAppState: () => ({ configHash, profile }),   // required; profile "P" | "B"
 *     onStateChange: (callback) => unsubscribe,       // required; called when the app state changes
 *     apiBase: "/decision",                           // optional
 *   });
 *   handle.unmount();
 * Panels only display backend results; they never compute a metric.
 */
(function () {
  "use strict";

  const CSS = `
  .cpd { --cpd-bg:#fff; --cpd-fg:#1f2328; --cpd-muted:#59636e; --cpd-line:#d1d9e0; --cpd-accent:#0969da;
         --cpd-bad:#cf222e; --cpd-bad-bg:#ffebe9; --cpd-ok:#1a7f37; --cpd-warn-bg:#fff8c5;
         font: 14px/1.45 system-ui, sans-serif; color: var(--cpd-fg); background: var(--cpd-bg); }
  @media (prefers-color-scheme: dark) {
    .cpd { --cpd-bg:#0d1117; --cpd-fg:#e6edf3; --cpd-muted:#9198a1; --cpd-line:#3d444d; --cpd-accent:#4493f8;
           --cpd-bad:#f85149; --cpd-bad-bg:#3c1618; --cpd-ok:#3fb950; --cpd-warn-bg:#3b2e0a; } }
  .cpd section { border: 1px solid var(--cpd-line); border-radius: 8px; padding: 12px 14px; margin: 0 0 12px; }
  .cpd h3 { font-size: 15px; margin: 0 0 8px; }
  .cpd h4 { font-size: 13px; margin: 12px 0 4px; color: var(--cpd-muted); text-transform: uppercase; letter-spacing: .03em; }
  .cpd .row { display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; margin: 4px 0; }
  .cpd label { display: inline-flex; gap: 6px; align-items: center; }
  .cpd input[type=number] { width: 7em; }
  .cpd button { font: inherit; padding: 4px 10px; border: 1px solid var(--cpd-line); border-radius: 6px;
                background: transparent; color: inherit; cursor: pointer; }
  .cpd button.primary { background: var(--cpd-accent); border-color: var(--cpd-accent); color: #fff; }
  .cpd button[aria-pressed=true] { background: var(--cpd-accent); border-color: var(--cpd-accent); color: #fff; }
  .cpd .muted { color: var(--cpd-muted); }
  .cpd .status { padding: 6px 10px; border-radius: 6px; margin: 6px 0; }
  .cpd .status.error { background: var(--cpd-bad-bg); color: var(--cpd-bad); }
  .cpd .status.outdated, .cpd .status.warn { background: var(--cpd-warn-bg); }
  .cpd .pkg { font-weight: 600; }
  .cpd table { border-collapse: collapse; width: 100%; }
  .cpd th, .cpd td { border-bottom: 1px solid var(--cpd-line); padding: 4px 6px; text-align: left; vertical-align: top; }
  .cpd td.num, .cpd th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .cpd td.over { background: var(--cpd-bad-bg); color: var(--cpd-bad); }
  .cpd .headline { font-size: 20px; font-weight: 700; margin: 4px 0; }
  .cpd .tag { display: inline-block; font-size: 12px; padding: 0 6px; border: 1px solid var(--cpd-line); border-radius: 10px; }
  `;

  function injectCss() {
    if (document.getElementById("cpd-css")) return;
    const style = document.createElement("style");
    style.id = "cpd-css";
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") node.className = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      node.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    }
    return node;
  }

  function fmt(value, digits) {
    if (value === null || value === undefined) return "n/a";
    if (typeof value !== "number") return String(value);
    return digits === undefined ? String(value) : value.toFixed(digits);
  }

  function pkgName(ids) {
    return ids && ids.length ? ids.join(" + ") : "no action";
  }

  async function api(apiBase, path, body) {
    const response = await fetch(apiBase + path, body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ")
        : data.detail || response.statusText;
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  /* status line: loading | error | outdated | empty */
  function statusLine(kind, text) {
    return el("div", { class: `status ${kind}`, role: kind === "error" ? "alert" : "status" }, text);
  }

  /* shared context passed to every panel */
  function createContext(options) {
    const listeners = new Set();
    return {
      apiBase: options.apiBase || "/decision",
      getAppState: options.getAppState,
      api: (path, body) => api(options.apiBase || "/decision", path, body),
      el, fmt, pkgName, statusLine,
      selected: null,              // package chosen in the decision panel
      serverState: null,           // GET /decision/state
      select(ids) { this.selected = ids; listeners.forEach((f) => f("select", ids)); },
      emit(event, payload) { listeners.forEach((f) => f(event, payload)); },
      on(f) { listeners.add(f); return () => listeners.delete(f); },
      isOutdated(result) {
        if (!result) return false;
        const app = options.getAppState() || {};
        return (app.configHash && app.configHash !== result.config_hash) ||
               (result._profile && app.profile && app.profile !== result._profile);
      },
    };
  }

  /* --- decision panel --- */
  function decisionPanel(root, ctx) {
    const app = ctx.getAppState() || {};
    const form = { B_h: 24, K: 2, N_a: 3, profile: app.profile === "B" ? "B" : "P" };
    let result = null, compare = null, phase = "empty", error = null;

    function number(name, min, max, step, unit) {
      const input = el("input", { type: "range", min, max, step, value: form[name],
        oninput: (e) => { form[name] = Number(e.target.value); out.textContent = `${form[name]} ${unit}`; } });
      const out = el("output", {}, `${form[name]} ${unit}`);
      return el("label", {}, `${name}`, input, out);
    }

    async function run(path, body, assign) {
      phase = "loading"; error = null; render();
      try {
        const data = await ctx.api(path, body);
        data._profile = form.profile;
        assign(data);
        phase = "done";
      } catch (e) {
        error = e; phase = "error";
      }
      render();
    }

    function optimizeNow() {
      compare = null;
      run("/optimize", { ...form }, (d) => { result = d; ctx.select(d.recommendation.candidate_ids); });
    }

    function compareNow() {
      run("/compare_ayna", { profile: form.profile }, (d) => { compare = d; result = d.optimizer;
        result.config_hash = d.config_hash; result._profile = form.profile; ctx.select(d.optimizer.recommendation.candidate_ids); });
    }

    function packageRow(p, extra) {
      return el("tr", {},
        el("td", { class: "pkg" }, ctx.pkgName(p.candidate_ids)),
        el("td", { class: "num" }, ctx.fmt(p.within_t)),
        el("td", { class: "num" }, ctx.fmt(p.capped_time_sum, 1)),
        el("td", { class: "num" }, ctx.fmt(p.bus_hours)),
        el("td", { class: "num" }, ctx.fmt(p.new_km, 2)),
        el("td", { class: "num" }, ctx.fmt(p.actions)),
        el("td", {}, extra || ""),
        el("td", {}, el("button", { onclick: () => ctx.select(p.candidate_ids), title: "Use in stress and CO2 panels" }, "use")));
    }

    function packageTable(rows) {
      const t = (ctx.serverState && ctx.serverState.primary_t_min) || "T";
      return el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "package"), el("th", { class: "num" }, `ODs ≤ ${t} min`),
          el("th", { class: "num" }, "capped time (min)"), el("th", { class: "num" }, "bus-hours"),
          el("th", { class: "num" }, "new km"), el("th", { class: "num" }, "actions"), el("th", {}, "note"), el("th", {}, ""))),
        el("tbody", {}, rows));
    }

    let limitsLoaded = false;

    function render() {
      const s = ctx.serverState;
      if (s && !limitsLoaded) {  // start the controls at the configured limits
        limitsLoaded = true;
        form.B_h = Math.min(70, s.limits.B_h_bus_hours);
        form.K = Math.min(3, s.limits.K_new_infra_km);
        form.N_a = Math.min(4, Math.max(1, s.limits.N_a_actions));
      }
      root.replaceChildren();
      root.appendChild(el("h3", {}, "Intervention packages"));
      const committed = s && s.objective[form.profile];
      const objective = committed ? (committed.value ? `${committed.value} (committed)` : committed.status) : "…";
      root.appendChild(el("div", { class: "muted" }, `Objective in use (profile ${form.profile}): ${objective}`));
      root.appendChild(el("div", { class: "row" },
        number("B_h", 0, 70, 0.5, "bus-hours"), number("K", 0, 3, 0.05, "km"),
        el("label", {}, "N_a", el("select", { onchange: (e) => { form.N_a = Number(e.target.value); } },
          [1, 2, 3, 4].map((n) => el("option", { value: n, selected: n === form.N_a }, String(n))))),
        el("span", { role: "group", "aria-label": "profile" }, "profile ",
          ["P", "B"].map((p) => el("button", { "aria-pressed": form.profile === p ? "true" : "false",
            onclick: () => { form.profile = p; render(); } }, p))),
        el("button", { class: "primary", onclick: optimizeNow }, "Optimise"),
        el("button", { onclick: compareNow }, "Compare with AYNA")));

      if (phase === "loading") root.appendChild(ctx.statusLine("loading", "Computing…"));
      if (phase === "error") root.appendChild(ctx.statusLine("error",
        error.status === 409 ? `Cannot compute: ${error.message}` : `Error: ${error.message}`));
      if (phase === "empty" && !result) root.appendChild(ctx.statusLine("empty", "No result yet: set the limits and press Optimise."));
      if (!result) return;
      if (ctx.isOutdated(result)) root.appendChild(ctx.statusLine("outdated", "outdated - recompute"));

      if (compare) {
        root.appendChild(el("h4", {}, "AYNA reference vs optimiser"));
        root.appendChild(el("div", { class: "headline" }, compare.verdict));
        root.appendChild(el("div", { class: "muted" },
          `Limits used: B_h = reference bus-hours (${ctx.fmt(compare.limits.B_h_bus_hours)}), N_a = ${compare.limits.N_a_actions}`));
        root.appendChild(packageTable([packageRow(compare.reference, "AYNA reference"),
          packageRow(compare.optimizer.recommendation, "optimiser")]));
      }

      const label = result.label === "approximate" ? `approximate: ${result.approximate_reason}` : "exact";
      root.appendChild(el("h4", {}, "Recommendation ", el("span", { class: "tag" }, label)));
      const rec = result.recommendation;
      if (!rec.candidate_ids.length) {
        root.appendChild(ctx.statusLine("warn", "No action package fits these limits better than doing nothing."));
      }
      root.appendChild(packageTable([packageRow(rec, `from ${result.recommendation_source}`)]));

      root.appendChild(el("h4", {}, "Alternatives"));
      root.appendChild(result.alternatives.length
        ? packageTable(result.alternatives.map((a) => packageRow(a, a.reason)))
        : el("div", { class: "muted" }, result.label === "approximate" ? "Not available in approximate mode." : "None."));

      root.appendChild(el("h4", {}, "Baselines (same candidates, limits and objective)"));
      root.appendChild(packageTable(Object.values(result.baselines).map((b) => packageRow(b.package, b.label))));

      if (result.not_ranked.length) {
        root.appendChild(el("h4", {}, "Not ranked"));
        root.appendChild(packageTable(result.not_ranked.map((p) => packageRow(p, p.reason))));
      }
      root.appendChild(el("div", { class: "muted" },
        `Feasible packages: ${ctx.fmt(result.feasible_count)} of ${result.enumerated_count} enumerated · config ${result.config_hash}`));
    }

    render();
    return { render };
  }

  const panels = { decision: decisionPanel };

  function mount(element, options) {
    if (!options || typeof options.getAppState !== "function" || typeof options.onStateChange !== "function") {
      throw new Error("CityPilotDecision.mount needs getAppState() and onStateChange(callback)");
    }
    injectCss();
    const ctx = createContext(options);
    const container = el("div", { class: "cpd" });
    element.replaceChildren(container);
    const instances = Object.entries(panels).map(([name, factory]) => {
      const section = el("section", { "data-panel": name });
      container.appendChild(section);
      return factory(section, ctx);
    });
    const renderAll = () => instances.forEach((p) => p.render());
    ctx.api("/state").then((s) => { ctx.serverState = s; renderAll(); })
      .catch((e) => container.prepend(statusLine("error", `Decision API unavailable: ${e.message}`)));
    const unsubscribe = options.onStateChange(renderAll);
    return { unmount() { if (typeof unsubscribe === "function") unsubscribe(); element.replaceChildren(); } };
  }

  window.CityPilotDecision = { mount, panels };
})();
