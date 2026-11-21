"use strict";

const state = { catalog: null, case: null, timeline: [], result: null };
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SERIES = ["--series-1", "--series-2", "--series-3", "--series-4"];
const partyColor = (i) => `var(${SERIES[i % SERIES.length]})`;
const fmt = (v, d = 2) => (v === null || v === undefined ? "—" : Number(v).toFixed(d));
const pretty = (s) => String(s ?? "").replace(/_/g, " ");

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || body));
  return body;
}

function show(step) {
  for (const id of ["submit", "review", "report"]) {
    if (id === step || (id === "review" && step === "report")) $("#" + id).hidden = false;
  }
  document.querySelectorAll(".step").forEach((a) => a.classList.toggle("active", a.dataset.step === step));
  $("#" + step).scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ------------------------------------------------------------------ init */
async function init() {
  state.catalog = await api("/api/catalog");
  const jur = $("#jur-select");
  jur.innerHTML = `<option value="">Detect from evidence</option>` +
    state.catalog.jurisdictions.map((j) => `<option value="${j.code}">${esc(j.name)}</option>`).join("");

  const samples = await api("/api/samples");
  $("#samples").innerHTML = samples.map((s, i) =>
    `<button class="sample" data-i="${i}"><b>${esc(s.title)}</b><span>${esc(s.case.scene.jurisdiction)} · ${esc(pretty(s.case.scene.collision_type))} · ${s.case.parties.length} parties</span></button>`).join("");
  $("#samples").addEventListener("click", (e) => {
    const b = e.target.closest(".sample");
    if (!b) return;
    loadCase(structuredClone(samples[+b.dataset.i].case), []);
  });

  const health = await api("/api/health");
  if (!health.extraction_available) {
    $("#extract-status").textContent = "Automatic extraction is off: add ANTHROPIC_API_KEY and FCH_MODEL to the .env file and restart the server. Samples and manual entry still work.";
  }
  $("#extract-form").addEventListener("submit", onExtract);
  $("#blank-btn").addEventListener("click", () => loadCase(blankCase(), []));
  $("#assess-btn").addEventListener("click", onAssess);
  $("#export-btn").addEventListener("click", () => download(`${state.case.id || "case"}.json`, JSON.stringify(state.case, null, 2)));
}

function blankCase() {
  return {
    id: "case-" + Date.now(), title: "New accident case", description: "",
    scene: { jurisdiction: $("#jur-select").value || "TX", location: "", date: "", road_surface: "unknown", lighting: "unknown", collision_type: "unknown", traffic_control: "" },
    parties: [newParty("A"), newParty("B")], actions: [], evidence: [], conflicts: [],
  };
}
const newParty = (id) => ({ id, label: `Driver ${id}`, vehicle: "", speed_mph: null, speed_limit_mph: null, distance_to_conflict_ft: null, had_right_of_way: null, visibility: "unknown", evasive_action_taken: null, notes: "" });
const newAction = () => ({ id: "act" + Date.now(), party_id: state.case.parties[0]?.id || "A", code: "FAILURE_TO_YIELD", description: "", evidence_ids: [], evidence_confidence: 0.8, magnitude: null, causation: { initiated_chain: null, but_for: null, mechanism_link: null }, contribution: { created_danger: null, reduced_reaction_time: null, affected_trajectory: null, increased_probability: null, increased_severity: null } });
const newEvidence = () => ({ id: "e" + (state.case.evidence.length + 1), kind: "other", source: "", summary: "", reliability: 0.7 });

function normalizeCase(c) {
  const blank = { parties: [], actions: [], evidence: [], conflicts: [] };
  for (const k of Object.keys(blank)) c[k] = c[k] || [];
  c.parties = c.parties.map((p) => ({ ...newParty(p.id), ...p }));
  c.actions = c.actions.map((a) => {
    const d = newAction();
    return { ...d, ...a, causation: { ...d.causation, ...(a.causation || {}) }, contribution: { ...d.contribution, ...(a.contribution || {}) } };
  });
  c.conflicts = c.conflicts.map((k) => ({ evidence_ids: [], party_ids: [], ...k }));
  return c;
}

function loadCase(c, timeline) {
  state.case = c;
  normalizeCase(c);
  state.timeline = timeline || [];
  renderEditor();
  show("review");
}

async function onExtract(e) {
  e.preventDefault();
  const btn = $("#extract-btn"), status = $("#extract-status");
  btn.disabled = true;
  status.textContent = "Reading the evidence… this can take a minute.";
  try {
    const out = await api("/api/extract", { method: "POST", body: new FormData(e.target) });
    out.case.id = "case-" + Date.now();
    status.textContent = "Facts extracted. Review them below.";
    loadCase(out.case, out.timeline);
  } catch (err) {
    status.textContent = "Extraction failed: " + err.message;
  } finally {
    btn.disabled = false;
  }
}

/* ------------------------------------------------------------------ editor */
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null) n.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) n.append(k.nodeType ? k : document.createTextNode(k));
  return n;
}

/** Bound input. kind: text|textarea|number|unit|select|tri|ids */
function field(obj, key, label, kind = "text", opts = {}) {
  let input;
  const v = obj[key];
  if (kind === "textarea") {
    input = el("textarea", { rows: opts.rows || 2 });
    input.value = v ?? "";
  } else if (kind === "select" || kind === "tri") {
    const options = kind === "tri" ? [["", "Unknown"], ["true", "Yes"], ["false", "No"]] : opts.options;
    input = el("select", {}, options.map(([val, text]) => el("option", { value: val }, text)));
    input.value = kind === "tri" ? (v === null || v === undefined ? "" : String(v)) : (v ?? "");
  } else {
    input = el("input", { type: kind === "number" || kind === "unit" ? "number" : "text", step: kind === "unit" ? "0.05" : "any", min: kind === "unit" ? 0 : undefined, max: kind === "unit" ? 1 : undefined, placeholder: opts.placeholder || (kind === "number" || kind === "unit" ? "unknown" : "") });
    input.value = kind === "ids" ? (v || []).join(", ") : (v ?? "");
  }
  input.addEventListener("change", () => {
    const raw = input.value;
    if (kind === "number" || kind === "unit") obj[key] = raw === "" ? null : Number(raw);
    else if (kind === "tri") obj[key] = raw === "" ? null : raw === "true";
    else if (kind === "ids") obj[key] = raw.split(",").map((s) => s.trim()).filter(Boolean);
    else obj[key] = raw;
    if (opts.rerender) renderEditor();
  });
  return el("label", { class: opts.wide ? "wide" : "" }, label, input);
}

function section(title, addLabel, onAdd, body) {
  return el("div", { class: "ed-section" },
    el("div", { class: "ed-head" }, el("h3", {}, title), addLabel ? el("button", { class: "ghost", type: "button", onclick: onAdd }, addLabel) : null),
    body);
}

function removeBtn(list, item) {
  return el("button", { class: "danger", type: "button", onclick: () => { list.splice(list.indexOf(item), 1); renderEditor(); } }, "Remove");
}

function renderEditor() {
  const c = state.case, root = $("#editor");
  root.innerHTML = "";
  const opts = (arr) => arr.map((x) => [x, pretty(x)]);
  const jurOpts = state.catalog.jurisdictions.map((j) => [j.code, j.name]);
  const vioOpts = state.catalog.violations.map((v) => [v.code, v.title]);
  const partyOpts = c.parties.map((p) => [p.id, p.label]);

  root.append(section("Case & scene", null, null, el("div", { class: "fields" },
    field(c, "title", "Title", "text", { wide: true }),
    field(c.scene, "jurisdiction", "Jurisdiction", "select", { options: jurOpts }),
    field(c.scene, "collision_type", "Collision type", "select", { options: opts(["unknown", "angle", "rear_end", "head_on", "sideswipe", "left_turn", "single_vehicle", "pedestrian"]) }),
    field(c.scene, "road_surface", "Road surface", "select", { options: opts(["unknown", "dry", "wet", "snow", "ice"]) }),
    field(c.scene, "lighting", "Lighting", "select", { options: opts(["unknown", "daylight", "dusk", "dark_lit", "dark_unlit"]) }),
    field(c.scene, "location", "Location"),
    field(c.scene, "date", "Date"),
    field(c.scene, "traffic_control", "Traffic control"),
    field(c, "description", "Description", "textarea", { wide: true, rows: 3 }),
  )));

  root.append(section("Parties", "+ Add party", () => { c.parties.push(newParty(String.fromCharCode(65 + c.parties.length))); renderEditor(); },
    el("div", { class: "cards" }, c.parties.map((p, i) => el("div", { class: "card" },
      el("div", { class: "card-head" }, el("span", { class: "chip", style: `color:${partyColor(i)}` }, `● ${p.id}`), c.parties.length > 1 ? removeBtn(c.parties, p) : null),
      el("div", { class: "fields" },
        field(p, "label", "Label", "text", { rerender: true }),
        field(p, "vehicle", "Vehicle"),
        field(p, "speed_mph", "Speed (mph)", "number"),
        field(p, "speed_limit_mph", "Speed limit (mph)", "number"),
        field(p, "distance_to_conflict_ft", "Distance to conflict (ft)", "number"),
        field(p, "had_right_of_way", "Had right of way", "tri"),
        field(p, "visibility", "Visibility", "select", { options: opts(["unknown", "good", "reduced", "poor"]) }),
        field(p, "evasive_action_taken", "Evasive action taken", "tri"),
      ))))));

  root.append(section("Actions & potential violations", "+ Add action", () => { c.actions.push(newAction()); renderEditor(); },
    el("div", { class: "cards" }, c.actions.length ? c.actions.map((a) => el("div", { class: "card" },
      el("div", { class: "card-head" }, el("span", { class: "chip" }, a.id), removeBtn(c.actions, a)),
      el("div", { class: "fields" },
        field(a, "party_id", "Party", "select", { options: partyOpts }),
        field(a, "code", "Violation / act", "select", { options: vioOpts }),
        field(a, "evidence_ids", "Evidence IDs", "ids", { placeholder: "e1, e2" }),
        field(a, "evidence_confidence", "Evidence confidence (0–1)", "unit"),
        field(a, "magnitude", "Magnitude (mph over / s distracted)", "number"),
        field(a.causation, "initiated_chain", "Initiated the chain of events", "tri"),
        field(a.causation, "but_for", "But-for probability (0–1)", "unit"),
        field(a.causation, "mechanism_link", "Mechanism link (0–1)", "unit"),
        field(a.contribution, "increased_severity", "Increased severity (0–1)", "unit"),
        field(a, "description", "Description", "textarea", { wide: true }),
      ))) : el("p", { class: "muted small" }, "No actions recorded yet."))));

  root.append(section("Evidence", "+ Add evidence", () => { c.evidence.push(newEvidence()); renderEditor(); },
    el("div", { class: "cards" }, c.evidence.length ? c.evidence.map((e) => el("div", { class: "card" },
      el("div", { class: "card-head" }, el("span", { class: "chip" }, e.id), removeBtn(c.evidence, e)),
      el("div", { class: "fields" },
        field(e, "id", "ID", "text", { rerender: true }),
        field(e, "kind", "Kind", "select", { options: opts(["photo", "video", "dashcam", "police_report", "witness", "driver_statement", "telemetry", "diagram", "other"]) }),
        field(e, "source", "Source"),
        field(e, "reliability", "Reliability (0–1)", "unit"),
        field(e, "summary", "Summary", "textarea", { wide: true }),
      ))) : el("p", { class: "muted small" }, "No evidence recorded."))));

  root.append(section("Conflicting evidence", "+ Add conflict", () => { c.conflicts.push({ description: "", evidence_ids: [], party_ids: [] }); renderEditor(); },
    el("div", { class: "cards" }, c.conflicts.length ? c.conflicts.map((k) => el("div", { class: "card" },
      el("div", { class: "card-head" }, el("span", { class: "chip" }, "conflict"), removeBtn(c.conflicts, k)),
      el("div", { class: "fields" },
        field(k, "description", "Description", "textarea", { wide: true }),
        field(k, "evidence_ids", "Evidence IDs", "ids"),
        field(k, "party_ids", "Party IDs", "ids"),
      ))) : el("p", { class: "muted small" }, "No conflicts recorded."))));
}

/* ------------------------------------------------------------------ assess */
async function onAssess() {
  const btn = $("#assess-btn"), status = $("#assess-status");
  btn.disabled = true;
  status.textContent = "Scoring…";
  try {
    state.result = await api("/api/assess", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case: state.case, timeline: state.timeline }),
    });
    status.textContent = "";
    renderReport(state.result.report);
    show("report");
  } catch (err) {
    status.textContent = "Assessment failed: " + err.message;
  } finally {
    btn.disabled = false;
  }
}

/* ------------------------------------------------------------------ charts */
const tip = () => $("#tooltip");
function bindTips(root) {
  root.querySelectorAll("[data-tip]").forEach((n) => {
    n.addEventListener("mousemove", (e) => {
      const t = tip();
      t.innerHTML = n.dataset.tip;
      t.hidden = false;
      const x = Math.min(e.clientX + 14, window.innerWidth - t.offsetWidth - 8);
      t.style.left = x + "px";
      t.style.top = e.clientY + 14 + "px";
    });
    n.addEventListener("mouseleave", () => { tip().hidden = true; });
  });
}

/** One 100% stacked bar per measure, segmented by party. */
function stackedChart(scores) {
  const measures = [["fault_pct", "Estimated fault"], ["causal_pct", "Causal contribution"], ["severity_pct", "Severity responsibility"]];
  const W = 720, labelW = 170, barH = 26, gap = 22, top = 8;
  const plotW = W - labelW - 8;
  const H = top + measures.length * (barH + gap);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Fault distribution by party for three measures">`;
  measures.forEach(([key, name], r) => {
    const y = top + r * (barH + gap);
    svg += `<text x="0" y="${y + barH / 2 + 4}" class="${r === 0 ? "lbl" : ""}">${name}</text>`;
    let x = labelW;
    const total = scores.reduce((s, p) => s + p[key], 0) || 1;
    scores.forEach((p, i) => {
      const w = (p[key] / total) * plotW;
      if (w <= 0) return;
      const segW = Math.max(0, w - 2); // 2px surface gap between segments
      const tipHtml = `<b>${esc(p.party)}</b><br>${name}: ${p[key].toFixed(1)}%`;
      svg += `<rect x="${x}" y="${y}" width="${segW}" height="${barH}" rx="4" fill="${partyColor(i)}" data-tip="${esc(tipHtml)}"></rect>`;
      if (segW > 44) svg += `<text x="${x + 8}" y="${y + barH / 2 + 4}" style="fill:#fff;font-weight:600" pointer-events="none">${p[key].toFixed(0)}%</text>`;
      x += w;
    });
  });
  return svg + "</svg>";
}

/** Point estimate with 80% interval per party, on a 0–100 axis. */
function intervalChart(scores) {
  const W = 720, labelW = 170, rowH = 34, top = 6, axisH = 22;
  const plotW = W - labelW - 16;
  const H = top + scores.length * rowH + axisH;
  const X = (v) => labelW + (v / 100) * plotW;
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Estimated fault with 80% uncertainty interval">`;
  for (const t of [0, 25, 50, 75, 100]) {
    svg += `<line x1="${X(t)}" x2="${X(t)}" y1="${top}" y2="${H - axisH}" stroke="var(--grid)" stroke-width="1"/>`;
    svg += `<text x="${X(t)}" y="${H - 6}" text-anchor="middle">${t}%</text>`;
  }
  scores.forEach((p, i) => {
    const cy = top + i * rowH + rowH / 2;
    const [lo, hi] = p.interval;
    const tipHtml = `<b>${esc(p.party)}</b><br>Estimate ${p.fault_pct.toFixed(1)}%<br>80% interval ${lo}–${hi}%`;
    svg += `<text x="0" y="${cy + 4}" class="lbl">${esc(p.party)}</text>`;
    svg += `<g data-tip="${esc(tipHtml)}"><rect x="${labelW}" y="${cy - rowH / 2}" width="${plotW}" height="${rowH}" fill="transparent"/>`;
    svg += `<line x1="${X(lo)}" x2="${X(hi)}" y1="${cy}" y2="${cy}" stroke="${partyColor(i)}" stroke-width="2" stroke-linecap="round"/>`;
    svg += `<line x1="${X(lo)}" x2="${X(lo)}" y1="${cy - 6}" y2="${cy + 6}" stroke="${partyColor(i)}" stroke-width="2"/>`;
    svg += `<line x1="${X(hi)}" x2="${X(hi)}" y1="${cy - 6}" y2="${cy + 6}" stroke="${partyColor(i)}" stroke-width="2"/>`;
    svg += `<circle cx="${X(p.fault_pct)}" cy="${cy}" r="6" fill="${partyColor(i)}" stroke="var(--surface)" stroke-width="2"/></g>`;
  });
  return svg + "</svg>";
}

/* ------------------------------------------------------------------ report */
function renderReport(r) {
  const determined = r.status === "DETERMINED";
  const partyIdx = Object.fromEntries(r.scores.map((s, i) => [s.party, i]));
  const legend = `<div class="legend">${r.scores.map((s, i) => `<span><i class="swatch" style="background:${partyColor(i)}"></i>${esc(s.party)}</span>`).join("")}</div>`;
  const tag = (a) => a.causal === null ? `<span class="tag undet">causation undetermined</span>` : a.causal ? `<span class="tag causal">causal</span>` : `<span class="tag noncausal">not causal</span>`;
  const list = (items, empty = "None.") => items && items.length ? `<ul class="plain">${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="muted small">${empty}</p>`;
  const sec = (n, title, html) => `<div class="rsec"><h3>${n}. ${title}</h3>${html}</div>`;
  const levelTable = (rows, cols = ["Party", "Action", "Value", "Basis"]) => `<div class="table-wrap"><table><thead><tr>${cols.map((c, i) => `<th class="${i === 2 ? "num" : ""}">${c}</th>`).join("")}</tr></thead><tbody>${rows.map((x) =>
    `<tr><td>${esc(x.party)}</td><td>${esc(x.action ?? "")}${x.implicit ? ' <span class="chip">implicit</span>' : ""}</td><td class="num">${fmt(x.value)}</td><td class="small">${esc(pretty(x.source))}${x.note ? " — " + esc(x.note) : ""}</td></tr>`).join("")}</tbody></table></div>`;

  const o = r.overview;
  const html = `
  <div class="report-head">
    <div>
      <h2>Accident Assessment Report</h2>
      <p class="muted" style="margin:4px 0 0">${esc(r.title)}</p>
    </div>
    <div class="no-print actions-row" style="margin:0">
      <button type="button" onclick="window.print()">Print / save PDF</button>
      <button type="button" id="dl-report">Download JSON</button>
    </div>
  </div>
  <div class="banner ${determined ? "ok" : "warn"}">
    <span class="icon" aria-hidden="true">${determined ? "✓" : "⚠"}</span>
    <div><b>${determined ? "Fault estimated" : "Insufficient evidence — no percentages assigned"}</b> · confidence ${esc(r.confidence)}
      <p class="small">${esc(r.explanation.summary)}</p></div>
  </div>

  ${determined ? `
  <div class="hero">${r.scores.map((s, i) => `
    <div class="tile">
      <div class="who"><i class="swatch" style="background:${partyColor(i)}"></i>${esc(s.party)}</div>
      <div class="big">${s.fault_pct.toFixed(0)}%</div>
      <div class="range">80% interval ${s.interval[0]}–${s.interval[1]}%</div>
      <div class="legal">${esc(s.legal_outcome)}</div>
    </div>`).join("")}
  </div>
  <div class="chart"><h4>Fault distribution</h4>${legend}${stackedChart(r.scores)}</div>
  <div class="chart"><h4>Estimated fault with 80% uncertainty interval</h4>${intervalChart(r.scores)}</div>` : ""}
  <p class="disclaimer">${esc(r.disclaimer)}</p>

  ${sec(1, "Accident overview", `<p>${esc(o.description) || '<span class="muted">No description.</span>'}</p>
    <div class="table-wrap"><table><tbody>
      <tr><th>Location</th><td>${esc(o.location) || "—"}</td><th>Date</th><td>${esc(o.date) || "—"}</td></tr>
      <tr><th>Collision type</th><td>${esc(pretty(o.collision_type))}</td><th>Road surface</th><td>${esc(o.road_surface)}</td></tr>
      <tr><th>Lighting</th><td>${esc(pretty(o.lighting))}</td><th>Traffic control</th><td>${esc(o.traffic_control) || "—"}</td></tr>
    </tbody></table></div>`)}

  ${sec(2, "Parties involved", `<div class="table-wrap"><table><thead><tr><th>Party</th><th>Vehicle</th><th class="num">Speed</th><th class="num">Limit</th><th class="num">Dist. to conflict</th><th>Right of way</th><th>Evasive action</th></tr></thead><tbody>
    ${r.parties.map((p) => `<tr><td><i class="swatch" style="display:inline-block;background:${partyColor(partyIdx[p.label] ?? 0)}"></i> ${esc(p.label)}</td><td>${esc(p.vehicle) || "—"}</td><td class="num">${p.speed_mph ?? "—"}</td><td class="num">${p.speed_limit_mph ?? "—"}</td><td class="num">${p.distance_to_conflict_ft != null ? p.distance_to_conflict_ft + " ft" : "—"}</td><td>${p.had_right_of_way == null ? "unknown" : p.had_right_of_way ? "yes" : "no"}</td><td>${p.evasive_action_taken == null ? "unknown" : p.evasive_action_taken ? "yes" : "no"}</td></tr>`).join("")}
    </tbody></table></div>`)}

  ${sec(3, "Accident timeline", r.timeline.length ? `<ol>${r.timeline.map((t) => `<li>${esc(t)}</li>`).join("")}</ol>` : `<p class="muted small">No timeline available.</p>`)}

  ${sec(4, "Evidence collected", `<div class="table-wrap"><table><thead><tr><th>ID</th><th>Kind</th><th>Source</th><th>Summary</th><th class="num">Reliability</th></tr></thead><tbody>
    ${r.evidence.map((e) => `<tr><td class="mono">${esc(e.id)}</td><td>${esc(pretty(e.kind))}</td><td>${esc(e.source)}</td><td>${esc(e.summary)}</td><td class="num">${fmt(e.reliability)}</td></tr>`).join("")}
    </tbody></table></div>`)}

  ${sec(5, "Identified traffic violations", `<div class="table-wrap"><table><thead><tr><th>Party</th><th>Violation</th><th>Statute</th><th>Evidence</th><th class="num">Confidence</th><th>Causal?</th></tr></thead><tbody>
    ${r.violations.map((v) => `<tr><td>${esc(v.party)}</td><td>${esc(v.title)}</td><td class="small">${esc(v.statute)}</td><td class="mono">${esc(v.evidence_ids.join(", ")) || "—"}</td><td class="num">${fmt(v.evidence_confidence)}</td><td>${tag(v)}</td></tr>`).join("")}
    </tbody></table></div>`)}

  ${sec(6, "Causation analysis (Level 1)", levelTable(r.analysis.causation))}
  ${sec(7, "Violation severity analysis (Level 2)", levelTable(r.analysis.severity))}
  ${sec(8, "Accident contribution analysis (Level 3)", `<h4>Likelihood contribution (enters fault)</h4>${levelTable(r.analysis.contribution)}<h4 style="margin-top:12px">Severity contribution (consequences only)</h4>${levelTable(r.analysis.severity_contribution)}`)}
  ${sec(9, "Avoidability analysis (Level 4)", levelTable(r.analysis.avoidability.map((x) => ({ ...x, action: "Opportunity to avoid" }))))}
  ${sec(10, "Shared responsibility analysis (Level 5)", list(r.analysis.shared))}

  ${sec(11, "Individual fault contribution scores", r.actions.map((a) => `
    <div class="action-card">
      <b>${esc(a.title)}</b> <span class="muted small">· ${esc(r.scores.find((s) => s.party_id === a.party_id)?.party || a.party_id)}</span>
      ${tag(a)}${a.implicit ? '<span class="tag">implicit</span>' : ""}${a.score > 0 && !a.counted ? '<span class="tag">merged</span>' : ""}
      <span class="muted small" style="float:right">score ${fmt(a.score, 3)}</span>
      <ul>${a.explanation.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    </div>`).join(""))}

  ${sec(12, "Final estimated fault percentages", `<div class="table-wrap"><table><thead><tr><th>Party</th><th class="num">Raw score R</th><th class="num">Estimated fault</th><th class="num">80% interval</th><th class="num">Causal contribution</th><th class="num">Severity responsibility</th><th>Under ${esc(r.laws.jurisdiction.name)} law</th></tr></thead><tbody>
    ${r.scores.map((s) => `<tr><td>${esc(s.party)}</td><td class="num">${fmt(s.raw_score, 3)}</td><td class="num"><b>${determined ? s.fault_pct.toFixed(1) + "%" : "—"}</b></td><td class="num">${determined ? s.interval[0] + "–" + s.interval[1] + "%" : "—"}</td><td class="num">${determined ? s.causal_pct.toFixed(1) + "%" : "—"}</td><td class="num">${determined ? s.severity_pct.toFixed(1) + "%" : "—"}</td><td class="small">${esc(s.legal_outcome) || "—"}</td></tr>`).join("")}
    </tbody></table></div>
    <p class="small muted">Estimated fault weighs causation, contribution and culpability. Causal contribution ignores culpability. Severity responsibility attributes the impact's harm, including excess energy from e.g. speed.</p>`)}

  ${sec(13, "Confidence and uncertainty", `
    <p>Overall confidence: <b>${esc(r.confidence)}</b>${r.status_reasons.length ? " — " + esc(r.status_reasons.join(" ")) : ""}</p>
    <div class="levels">
      <div><h4>Uncertainties</h4>${list(r.uncertainties)}</div>
      <div><h4>Missing information</h4>${list(r.missing_information)}</div>
      <div><h4>Conflicting evidence</h4>${list(r.conflicts)}</div>
    </div>`)}

  ${sec(14, "Relevant traffic laws", `
    <p><b>${esc(r.laws.jurisdiction.name)}</b> — ${esc(r.laws.jurisdiction.rule_text)} <span class="muted small">(${esc(r.laws.jurisdiction.authority)})</span></p>
    ${list(r.laws.statutes.map(([t, s]) => `${t}: ${s}`))}
    <p class="small muted">Citations are for orientation and must be verified against current law.</p>`)}

  ${sec(15, "Explanation of the final determination", `<p>${esc(r.explanation.summary)}</p><h4>Calculation</h4>${list(r.explanation.steps)}`)}
  `;
  $("#report-body").innerHTML = html;
  $("#dl-report").addEventListener("click", () => download("assessment-report.json", JSON.stringify(state.result, null, 2)));
  bindTips($("#report-body"));
}

function download(name, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

init().catch((e) => { $("#extract-status").textContent = "Failed to load: " + e.message; });
