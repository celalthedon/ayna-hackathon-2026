/* CityPilot stress panel: 3x3 speed x headway grid for the selected package. Load after decision_panel.js. */
(function () {
  "use strict";

  const LEVELS = ["low", "default", "high"];
  const WARNING_TEXT = {
    cost_rises_with_speed: "A faster point needs more bus-hours here because vehicle counts round up to whole buses.",
    zero_cost_uses_slack: "The headway cut fits in the rounding slack of the existing fleet, so it adds no bus-hours.",
    headway_exceeds_cycle: "The headway is longer than the round trip, so one bus is enough.",
  };

  function explain(code) {
    const key = Object.keys(WARNING_TEXT).find((k) => code.startsWith(k));
    return key ? `${key}: ${WARNING_TEXT[key]}` : code;
  }

  function stressPanel(root, ctx) {
    const { el, fmt, pkgName } = ctx;
    let result = null, phase = "empty", error = null;

    async function run() {
      if (!ctx.selected) return;
      const profile = (ctx.getAppState() || {}).profile === "B" ? "B" : "P";
      phase = "loading"; error = null; render();
      try {
        result = await ctx.api("/stress", { package_ids: ctx.selected, profile });
        result._profile = profile;
        phase = "done";
      } catch (e) { error = e; phase = "error"; }
      render();
    }

    function cell(p) {
      const t = (ctx.serverState && ctx.serverState.primary_t_min) || "T";
      return el("td", { class: p.overrun > 0 ? "over" : "", title: p.feasible ? "fits the limits" : "over the limits" },
        el("div", {}, p.feasible ? "fits" : `over by ${fmt(p.overrun)} bus-hours`),
        el("div", {}, `${fmt(p.bus_hours)} bus-hours`),
        el("div", {}, `${fmt(p.within_t)} ODs ≤ ${t} min`),
        el("div", {}, `capped ${fmt(p.capped_time_sum, 1)} min`));
    }

    function render() {
      root.replaceChildren();
      root.appendChild(el("h3", {}, "Stress test"));
      const available = !ctx.serverState || ctx.serverState.stress_available;
      root.appendChild(el("div", { class: "row" },
        el("span", {}, "Package: ", el("span", { class: "pkg" }, ctx.selected ? pkgName(ctx.selected) : "none selected")),
        el("button", { class: "primary", onclick: run, disabled: !ctx.selected || !available }, "Run stress test")));
      if (!available) { root.appendChild(ctx.statusLine("empty", "No stress grid for this model.")); return; }
      if (phase === "loading") root.appendChild(ctx.statusLine("loading", "Computing 9 grid points…"));
      if (phase === "error") root.appendChild(ctx.statusLine("error", `Error: ${error.message}`));
      if (!result) {
        if (phase !== "loading") root.appendChild(ctx.statusLine("empty", "No result yet: pick a package and run the stress test."));
        return;
      }
      if (ctx.isOutdated(result) || pkgName(result.package_ids) !== pkgName(ctx.selected)) {
        root.appendChild(ctx.statusLine("outdated", "outdated - recompute"));
      }
      const byKey = Object.fromEntries(result.points.map((p) => [`${p.speed_level}/${p.headway_level}`, p]));
      root.appendChild(el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "speed \\ headway"), LEVELS.map((h) => el("th", {}, `${h} headway`)))),
        el("tbody", {}, LEVELS.map((s) => el("tr", {}, el("th", {}, `${s} speed`),
          LEVELS.map((h) => cell(byKey[`${s}/${h}`])))))));

      const w = result.worst, re = result.reoptimization.recommendation;
      root.appendChild(el("h4", {}, "Worst point"));
      root.appendChild(el("div", {}, `${w.speed_level} speed, ${w.headway_level} headway` +
        (w.overrun > 0 ? ` (over by ${fmt(w.overrun)} bus-hours)` : "")));
      root.appendChild(el("div", {}, "Re-optimised there: ", el("span", { class: "pkg" }, pkgName(re.candidate_ids)),
        ` (${fmt(re.within_t)} ODs, capped ${fmt(re.capped_time_sum, 1)} min, ${fmt(re.bus_hours)} bus-hours)`));
      root.appendChild(el("div", { class: "muted" }, result.reoptimization_reason));

      const codes = [...result.warnings, ...new Set(result.points.flatMap((p) => p.warnings))];
      root.appendChild(el("h4", {}, "Warnings"));
      root.appendChild(codes.length
        ? el("ul", {}, codes.map((c) => el("li", {}, explain(c))))
        : el("div", { class: "muted" }, "None."));
    }

    ctx.on((event) => { if (event === "select") render(); });
    render();
    return { render };
  }

  if (!window.CityPilotDecision) throw new Error("load decision_panel.js before stress_panel.js");
  window.CityPilotDecision.panels.stress = stressPanel;
})();
