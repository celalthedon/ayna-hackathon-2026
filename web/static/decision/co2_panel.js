/* CityPilot CO2 panel: break-even first, then inputs and assumptions. Load after decision_panel.js. */
(function () {
  "use strict";

  function co2Panel(root, ctx) {
    const { el, fmt, pkgName } = ctx;
    const inputs = { car_trip_km: "", avoided_car_trips: "", bus_kg_per_vkm: "", car_kg_per_pkm: "" };
    let result = null, phase = "empty", error = null;

    async function run() {
      if (!ctx.selected) return;
      const body = { package_ids: ctx.selected, profile: (ctx.getAppState() || {}).profile === "B" ? "B" : "P" };
      for (const [k, v] of Object.entries(inputs)) if (v !== "") body[k] = Number(v);
      phase = "loading"; error = null; render();
      try {
        result = await ctx.api("/co2", body);
        phase = "done";
      } catch (e) { error = e; phase = "error"; }
      render();
    }

    function field(name, label, placeholder) {
      return el("label", {}, label, el("input", { type: "number", min: 0, step: "any", value: inputs[name], placeholder,
        oninput: (e) => { inputs[name] = e.target.value; } }));
    }

    function coverageText() {
      const cov = result.car_distance_coverage;
      return cov && cov.missing > 0
        ? `${cov.missing} of ${cov.restored} restored journeys have no modelled car distance; enter a car trip length`
        : null;
    }

    function reasons() {
      const by = (result.car_distance_coverage || {}).by_reason || {};
      return Object.entries(by).map(([r, n]) => `${n} ${r}`).join(", ");
    }

    function tripInput() {
      return el("div", { class: "row" },
        el("label", {}, "car trip km", el("input", { type: "number", min: 0, step: "any", value: inputs.car_trip_km,
          "aria-label": "car trip km", oninput: (e) => { inputs.car_trip_km = e.target.value; } })),
        el("button", { class: "primary", onclick: run, disabled: !ctx.selected }, "Compute break-even"));
    }

    function headline() {
      const missing = coverageText();
      if (result.status === "needs_car_trip_km") {
        return el("div", {},
          el("div", { class: "headline" }, missing || "Enter a car trip length to get the break-even"),
          tripInput(),
          el("div", { class: "muted" }, `Reference only: ${fmt(result.reference_car_trip_km)} km, ${result.reference_car_trip_km_label}. ` +
            (missing ? `No modelled car distance: ${reasons()}.` : `Car distance of the restored ODs: ${result.car_trip_km_source}.`)));
      }
      const user = result.car_trip_km_status !== "modelled";
      return el("div", {},
        el("div", { class: "headline" }, `Break-even: ${fmt(result.break_even_trips)} avoided car trips`),
        el("div", { class: "muted" }, `over the same ${fmt(result.period_hours)} h window, at ${fmt(result.car_trip_km, 2)} km per car trip ` +
          `(${user ? "your input" : result.car_trip_km_source})`),
        user && missing ? el("div", { class: "muted" }, `${result.car_distance_coverage.missing} of ` +
          `${result.car_distance_coverage.restored} restored journeys have no modelled car distance (${reasons()}).`) : null);
    }

    function render() {
      const s = ctx.serverState;
      root.replaceChildren();
      root.appendChild(el("h3", {}, "CO2"));
      if (s && !s.co2_available) { root.appendChild(ctx.statusLine("empty", "CO2 needs a service catalog; not available for this model.")); return; }
      const d = (s && s.co2_defaults) || {};
      root.appendChild(el("div", { class: "row" },
        el("span", {}, "Package: ", el("span", { class: "pkg" }, ctx.selected ? pkgName(ctx.selected) : "none selected")),
        el("button", { class: "primary", onclick: run, disabled: !ctx.selected }, "Compute CO2")));
      if (phase === "loading") root.appendChild(ctx.statusLine("loading", "Computing…"));
      if (phase === "error") root.appendChild(ctx.statusLine("error", `Error: ${error.message}`));
      if (result) {
        if (ctx.isOutdated(result)) root.appendChild(ctx.statusLine("outdated", "outdated - recompute"));
        root.appendChild(headline());
        const u = result.units;
        root.appendChild(el("table", {}, el("tbody", {},
          el("tr", {}, el("td", {}, "added bus distance"), el("td", { class: "num" }, `${fmt(result.bus_vkm, 1)} ${u.bus_vkm}`)),
          el("tr", {}, el("td", {}, "added bus CO2"), el("td", { class: "num" }, `${fmt(result.bus_kg, 1)} ${u.bus_kg}`)),
          el("tr", {}, el("td", {}, "car CO2 per trip"), el("td", { class: "num" }, `${fmt(result.per_trip_car_kg, 4)} ${u.per_trip_car_kg}`)),
          result.net_kg === null ? null : el("tr", {}, el("td", {}, "net saving with your avoided trips"),
            el("td", { class: "num" }, `${result.net_kg >= 0 ? "" : "−"}${fmt(Math.abs(result.net_kg), 1)} ${u.net_kg}`)))));
        root.appendChild(el("div", { class: "muted" }, "Per action: " +
          Object.entries(result.per_action_vkm).map(([a, v]) => `${a} ${fmt(v, 1)} ${u.bus_vkm}`).join(", ")));
      } else if (phase !== "loading") {
        root.appendChild(ctx.statusLine("empty", "No result yet: pick a package and press Compute CO2."));
      }
      root.appendChild(el("h4", {}, "Inputs"));
      root.appendChild(el("div", { class: "row" },
        field("car_trip_km", "car trip km", "from OD table"),
        field("avoided_car_trips", "avoided car trips", "optional"),
        field("bus_kg_per_vkm", "bus kg/vkm", d.bus_kg_per_vkm),
        field("car_kg_per_pkm", "car kg/pkm", d.car_kg_per_pkm)));
      root.appendChild(el("div", { class: "muted" }, d.statuses
        ? `Defaults: bus ${d.bus_kg_per_vkm} (${d.statuses.bus_kg_per_vkm}), car ${d.car_kg_per_pkm} (${d.statuses.car_kg_per_pkm}).`
        : ""));
      if (result) root.appendChild(el("ul", { class: "muted" }, result.notes.map((n) => el("li", {}, n))));
    }

    ctx.on((event) => { if (event === "select") render(); });
    render();
    return { render };
  }

  if (!window.CityPilotDecision) throw new Error("load decision_panel.js before co2_panel.js");
  window.CityPilotDecision.panels.co2 = co2Panel;
})();
