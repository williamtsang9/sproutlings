/* Sproutlings frontend — vanilla JS, no build step. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
};

const state = {
  meta: null,
  children: [],
  selectedChild: null,
  mode: "worksheet",      // "worksheet" | "test"
  currentPacket: null,
};

/* ---------------- bootstrap ---------------- */
async function init() {
  state.meta = await api("/api/meta");
  $("#model-chip").textContent = `local model: ${state.meta.model}`;
  fillSelect($("#sel-grade"), state.meta.grades);
  fillSelect($("#sel-field"), state.meta.fields);
  fillSelect($("#sel-level"), state.meta.levels);
  fillSelect($("#add-grade"), state.meta.grades);
  $("#field-checks").innerHTML = state.meta.fields.map((f) =>
    `<label><input type="checkbox" value="${f}" checked> ${f}</label>`
  ).join("");
  await refreshChildren();
  wireEvents();
}

function fillSelect(sel, values) {
  sel.innerHTML = values.map((v) => `<option>${v}</option>`).join("");
}

/* ---------------- children ---------------- */
async function refreshChildren() {
  state.children = await api("/api/children");
  const list = $("#child-list");
  if (!state.children.length) {
    list.innerHTML = `<p class="empty">No profiles yet — add your first
      sproutling below.</p>`;
    return;
  }
  list.innerHTML = "";
  for (const c of state.children) {
    const btn = document.createElement("button");
    btn.className = "child-card" +
      (state.selectedChild?.id === c.id ? " selected" : "");
    btn.innerHTML = `
      <div class="child-name"><span>${escapeHtml(c.name)}</span>
        <span class="sprout-meter" data-meter></span></div>
      <div class="child-meta">age ${c.age} · grade ${c.default_grade}</div>`;
    btn.addEventListener("click", () => selectChild(c));
    list.appendChild(btn);
    paintMeter(btn.querySelector("[data-meter]"), c.id);
  }
}

/* sprout meter: 🌰 seed → 🌱 sprout → 🌿 sapling → 🌳 tree,
   lighting up one stage per 5 completed packets */
async function paintMeter(el, childId) {
  try {
    const stats = await api(`/api/children/${childId}/stats`);
    const done = stats.fields.reduce((n, f) => n + (f.completed || 0), 0);
    const stages = ["🌰", "🌱", "🌿", "🌳"];
    const lit = Math.min(stages.length, 1 + Math.floor(done / 5));
    el.innerHTML = stages.map((s, i) =>
      `<span class="${i < lit ? "lit" : "unlit"}" title="${done} completed">${s}</span>`
    ).join("");
  } catch (_) { /* non-fatal */ }
}

async function selectChild(c) {
  state.selectedChild = c;
  $("#sel-grade").value = c.default_grade;
  $("#btn-generate").disabled = false;
  updateGenerateLabel();
  await Promise.all([refreshChildren(), refreshHistory(), refreshStats()]);
}

$("#add-child").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    const child = await api("/api/children", {
      method: "POST",
      body: JSON.stringify({
        name: fd.get("name"),
        age: Number(fd.get("age")),
        default_grade: fd.get("default_grade"),
      }),
    });
    e.target.reset();
    await selectChild(child);
  } catch (err) { setStatus(err.message, true); }
});

/* ---------------- stats + history ---------------- */
async function refreshStats() {
  if (!state.selectedChild) return;
  const s = await api(`/api/children/${state.selectedChild.id}/stats`);
  const scoreByField = Object.fromEntries(
    s.recent_scores.map((r) => [r.field, r.avg_score]));
  $("#stats").innerHTML = s.fields.map((f) => {
    const sc = scoreByField[f.field];
    const scoreTxt = sc != null ? ` · avg ${(sc * 100).toFixed(0)}%` : "";
    const weak = sc != null && sc < 0.6 ? " weak" : "";
    return `<span class="stat-pill${weak}">${f.field}:
      <b>${f.generated}</b> generated, <b>${f.completed || 0}</b>
      completed${scoreTxt}</span>`;
  }).join("") || `<span class="empty">No packets yet.</span>`;
}

async function refreshHistory() {
  if (!state.selectedChild) return;
  const rows = await api(`/api/children/${state.selectedChild.id}/packets`);
  const tbody = $("#history tbody");
  $("#history-empty").classList.toggle("hidden", rows.length > 0);
  tbody.innerHTML = rows.map((p) => `
    <tr>
      <td>${p.id}</td><td>${p.kind}</td><td>${p.field ?? "multi"}</td>
      <td>${p.grade}</td><td>${p.level}</td>
      <td><span class="status-chip ${p.status}">${p.status.replace("_", " ")}</span></td>
      <td><button class="btn" data-open="${p.id}">Open</button></td>
    </tr>`).join("");
  tbody.querySelectorAll("[data-open]").forEach((b) =>
    b.addEventListener("click", () => openPacket(Number(b.dataset.open))));
}

/* ---------------- generation ---------------- */
function wireEvents() {
  document.querySelectorAll(".gen-tab").forEach((t) =>
    t.addEventListener("click", () => {
      document.querySelectorAll(".gen-tab").forEach((x) =>
        x.classList.toggle("active", x === t));
      state.mode = t.dataset.mode;
      $("#field-single-wrap").classList.toggle("hidden", state.mode === "test");
      $("#field-multi-wrap").classList.toggle("hidden", state.mode !== "test");
      $("#qcount-wrap").classList.toggle("hidden", state.mode !== "test");
      updateGenerateLabel();
    }));
  $("#btn-generate").addEventListener("click", generate);
  $("#btn-close-viewer").addEventListener("click", closeViewer);
  $("#btn-print").addEventListener("click", () => window.print());
  $("#chk-answers").addEventListener("change", renderPacket);
  $("#btn-approve").addEventListener("click", () => setStatus2("approved"));
  $("#btn-complete").addEventListener("click", () => setStatus2("completed"));
  $("#btn-score").addEventListener("click", openScoreDialog);
  $("#score-form").addEventListener("submit", submitScore);
}

function updateGenerateLabel() {
  const b = $("#btn-generate");
  if (!state.selectedChild) { b.textContent = "Select a child to begin"; return; }
  b.textContent = state.mode === "test"
    ? `Generate test packet for ${state.selectedChild.name}`
    : `Generate worksheet packet for ${state.selectedChild.name}`;
}

async function generate() {
  const c = state.selectedChild;
  if (!c) return;
  const btn = $("#btn-generate");
  btn.disabled = true;
  setStatus(state.mode === "test"
    ? "Building test… weighting questions toward weaker fields."
    : "Generating… mathematics is instant; language fields run on your local model.");
  try {
    let packet;
    if (state.mode === "worksheet") {
      packet = await api("/api/worksheets", {
        method: "POST",
        body: JSON.stringify({
          child_id: c.id, field: $("#sel-field").value,
          grade: $("#sel-grade").value, level: $("#sel-level").value,
        }),
      });
    } else {
      const fields = [...document.querySelectorAll("#field-checks input:checked")]
        .map((i) => i.value);
      packet = await api("/api/tests", {
        method: "POST",
        body: JSON.stringify({
          child_id: c.id, fields,
          grade: $("#sel-grade").value, level: $("#sel-level").value,
          total_questions: Number($("#sel-qcount").value),
        }),
      });
    }
    setStatus("Done — opening packet.");
    await Promise.all([refreshHistory(), refreshStats(), refreshChildren()]);
    showPacket(packet);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    btn.disabled = false;
  }
}

function setStatus(msg, isError = false) {
  const el = $("#gen-status");
  el.textContent = msg;
  el.classList.toggle("error", isError);
}

/* ---------------- viewer ---------------- */
async function openPacket(id) {
  showPacket(await api(`/api/packets/${id}`));
}

function showPacket(packet) {
  state.currentPacket = packet;
  $("#viewer").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  renderPacket();
}

function closeViewer() {
  $("#viewer").classList.add("hidden");
  document.body.style.overflow = "";
  state.currentPacket = null;
}

function renderPacket() {
  const p = state.currentPacket;
  if (!p) return;
  const showAnswers = $("#chk-answers").checked;
  const chip = $("#viewer-status-chip");
  chip.className = `status-chip ${p.status}`;
  chip.textContent = p.status.replace("_", " ");
  $("#btn-score").style.display = p.kind === "test" ? "" : "none";
  $("#btn-approve").style.display = p.status === "needs_review" ? "" : "none";

  const pages = $("#viewer-pages");
  pages.innerHTML = "";
  if (p.status === "needs_review") {
    pages.insertAdjacentHTML("beforeend", `<div class="review-banner">
      This packet was drafted by the local model — review it before
      printing, then click <b>Approve</b>. Mathematics packets skip this
      step because their answers are computed, not generated.</div>`);
  }
  for (const sheet of p.content.sheets) {
    const probs = sheet.problems.map((pr, i) => `
      <div class="problem">
        <span class="num">${i + 1}.</span>
        <span class="prompt">${escapeHtml(pr.prompt)}</span>
        ${showAnswers
          ? `<div class="answer">${escapeHtml(pr.answer)}</div>`
          : (pr.work_space ? `<div class="work-space"></div>` : "")}
      </div>`).join("");
    pages.insertAdjacentHTML("beforeend", `
      <div class="page">
        <div class="page-head">
          <h2>${escapeHtml(sheet.title)}</h2>
          <div class="name-date">Name ____________ &nbsp; Date ________</div>
        </div>
        <p class="instructions">${escapeHtml(sheet.instructions)}</p>
        ${probs}
      </div>`);
  }
}

async function setStatus2(status) {
  const p = state.currentPacket;
  if (!p) return;
  state.currentPacket = await api(`/api/packets/${p.id}/status`, {
    method: "PATCH", body: JSON.stringify({ status }),
  });
  renderPacket();
  await Promise.all([refreshHistory(), refreshStats(), refreshChildren()]);
}

/* ---------------- test scoring ---------------- */
function openScoreDialog() {
  const p = state.currentPacket;
  if (!p || p.kind !== "test") return;
  const rows = $("#score-rows");
  rows.innerHTML = "";
  for (const sheet of p.content.sheets) {
    const field = sheet.title.match(/Test — (\w+)/)?.[1] ?? sheet.topic;
    const total = sheet.problems.length;
    rows.insertAdjacentHTML("beforeend", `
      <div class="score-row" data-field="${field}">
        <span>${field}</span>
        <input type="number" min="0" max="${total}" value="0" data-correct>
        <span>/</span>
        <input type="number" value="${total}" data-total readonly>
      </div>`);
  }
  $("#score-dialog").showModal();
}

async function submitScore(e) {
  if (e.submitter?.value !== "save") return;
  e.preventDefault();
  const per_field = {};
  document.querySelectorAll(".score-row").forEach((r) => {
    per_field[r.dataset.field] = [
      Number(r.querySelector("[data-correct]").value),
      Number(r.querySelector("[data-total]").value),
    ];
  });
  try {
    await api(`/api/packets/${state.currentPacket.id}/score`, {
      method: "POST", body: JSON.stringify({ per_field }),
    });
    $("#score-dialog").close();
    state.currentPacket = await api(`/api/packets/${state.currentPacket.id}`);
    renderPacket();
    await Promise.all([refreshHistory(), refreshStats(), refreshChildren()]);
  } catch (err) {
    alert(err.message);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

init().catch((e) => setStatus(`Startup failed: ${e.message}`, true));
