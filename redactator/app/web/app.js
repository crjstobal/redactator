// Redactator UI. Talks to Python through window.pywebview.api (see app/main.py).

const $ = (id) => document.getElementById(id);
const state = {
  files: [],          // summaries from Python
  current: 0,         // selected file
  plans: new Map(),   // file index -> plan
  page: 0,
  drawing: false,
  busy: false,
  hot: null,
  reveal: false,
};
const imageCache = new Map(); // "file:page" -> data URL
let api = null;

const plan = () => state.plans.get(state.current);

// ---------- settings (remembered between sessions) ----------
function loadSettings() {
  try { return JSON.parse(localStorage.getItem("redactator.settings") || "null"); } catch { return null; }
}
function saveSettings() {
  try { localStorage.setItem("redactator.settings", JSON.stringify(readSettings())); } catch {}
}
function readSettings() {
  return {
    hide: [...document.querySelectorAll("#cats input:checked")].map((i) => i.value),
    also: $("also").value,
    keep: $("keep").value,
  };
}

function renderCategories(categories) {
  const saved = loadSettings();
  const box = $("cats");
  box.innerHTML = "";
  for (const c of categories) {
    const label = Object.assign(document.createElement("label"), { className: "cat" });
    const input = Object.assign(document.createElement("input"), { type: "checkbox", value: c.id });
    input.checked = saved ? saved.hide.includes(c.id) : c.default;
    input.onchange = saveSettings;
    label.append(input, Object.assign(document.createElement("span"), { textContent: c.title }));
    box.append(label);
  }
  if (saved) {
    $("also").value = saved.also || "";
    $("keep").value = saved.keep || "";
  }
}
$("also").addEventListener("input", saveSettings);
$("keep").addEventListener("input", saveSettings);

// ---------- Python -> JS callbacks ----------
window.onProgress = (msg) => setStatus(msg, "busy");
window.onError = (msg) => { state.busy = false; setStatus(msg, "error"); syncButtons(); };

window.onFiles = (files) => {
  const before = state.files.length;
  state.files = files;
  if (files.length > before && !state.busy) {
    // new files were added: forget results, settings may change before the next run
    state.plans.clear();
    imageCache.clear();
    state.current = before < files.length ? before : 0;
    showDropFor(files[state.current]);
  }
  renderFiles();
  syncButtons();
};

window.onPlan = async (p) => {
  state.plans.set(p.file, p);
  if (p.file === state.current) {
    state.page = firstPageWithBoxes(p);
    state.reveal = true;
    await showPlan();
  }
};

window.onDone = (files) => {
  state.busy = false;
  state.files = files;
  renderFiles();
  syncButtons();
  const found = files.reduce((n, f) => n + f.found, 0);
  const failed = files.filter((f) => f.status === "error");
  if (failed.length) {
    setStatus(`${failed.map((f) => f.name).join(", ")} could not be read: ${failed[0].error}`, "error");
  } else if (files.length > 1) {
    setStatus(`Checked ${files.length} files, ${found} things to hide. Untick anything that should stay visible.`);
  } else {
    const p = plan();
    const how = p && p.model ? ` with ${prettyModel(p.model)}` : "";
    setStatus(found ? `Done in ${p.seconds}s${how}. Untick anything that should stay visible.` : "Nothing to hide found. Draw a box to hide something by hand.");
  }
};

window.onExported = (paths) => {
  state.busy = false;
  syncButtons();
  setStatus("Exported. The original files were not changed.");
  const label = paths.length === 1 ? `Saved ${paths[0].split(/[\\/]/).pop()}` : `Saved ${paths.length} redacted files`;
  toast(label, "Show in folder", () => api.reveal(paths[0]));
};

// ---------- helpers ----------
function prettyModel(m) {
  return m.replace(/^gemma(\d)/i, "Gemma $1").replace(":", " ").replace(/\be(\d)b\b/i, "E$1B");
}

function setStatus(text, kind = "") {
  const el = $("status");
  el.textContent = text || "";
  el.className = "status " + kind;
}

function syncButtons() {
  const n = state.files.length;
  $("findBtn").disabled = !n || state.busy;
  $("findBtn").textContent = n > 1 ? `Check ${n} files` : "Find private data";
  const ready = state.files.filter((f) => f.status === "done").length;
  $("exportBtn").disabled = !ready || state.busy;
  $("exportBtn").textContent = ready > 1 ? `Export ${ready} redacted files` : "Export redacted file";
  document.querySelectorAll("#cats input").forEach((i) => (i.disabled = state.busy));
}

function toast(text, action, onAction) {
  const el = $("toast");
  el.innerHTML = "";
  el.append(Object.assign(document.createElement("span"), { textContent: text }));
  if (action) {
    const b = Object.assign(document.createElement("button"), { className: "link", textContent: action });
    b.onclick = onAction;
    el.append(b);
  }
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), 8000);
}

function boxesFor(finding, page) {
  return [...(finding.boxes[String(page)] || []), ...(finding.boxes["-1"] || [])];
}

function firstPageWithBoxes(p) {
  for (const pg of p.pages) {
    if (p.findings.some((f) => boxesFor(f, pg.index).length)) return pg.index;
  }
  return 0;
}

function fmtTime(t) {
  const m = Math.floor(t / 60);
  const s = (t % 60).toFixed(1).padStart(4, "0");
  return `${m}:${s}`;
}

// ---------- files ----------
const STATE_TEXT = { waiting: "", reading: "Reading", error: "Could not read" };

function renderFiles() {
  const nav = $("files");
  nav.hidden = !state.files.length;
  nav.innerHTML = "";
  state.files.forEach((f, i) => {
    const tab = Object.assign(document.createElement("button"), { className: "tab", type: "button" });
    tab.setAttribute("aria-current", String(i === state.current));
    tab.title = f.path;
    const status = f.status === "done" ? (f.found ? `${f.found} found` : "Nothing found") : STATE_TEXT[f.status];
    tab.append(
      Object.assign(document.createElement("span"), { className: "name", textContent: f.name }),
      Object.assign(document.createElement("span"), { className: `state ${f.status}`, textContent: status }),
    );
    if (!state.busy) {
      const x = Object.assign(document.createElement("span"), { className: "x", textContent: "×", title: "Remove from the list", role: "button" });
      x.setAttribute("aria-label", `Remove ${f.name}`);
      x.onclick = async (e) => {
        e.stopPropagation();
        const files = await api.remove_file(i);
        // indices shift after a removal
        const plans = new Map();
        for (const [k, v] of state.plans) if (k !== i) plans.set(k > i ? k - 1 : k, { ...v, file: k > i ? k - 1 : k });
        state.plans = plans;
        imageCache.clear();
        state.files = files;
        state.current = Math.min(state.current, Math.max(0, files.length - 1));
        renderFiles();
        syncButtons();
        files.length ? select(state.current) : showDropFor(null);
      };
      tab.append(x);
    }
    tab.onclick = () => select(i);
    nav.append(tab);
  });
  const add = Object.assign(document.createElement("button"), { className: "btn btn-ghost add", type: "button", textContent: "Add files" });
  add.onclick = () => api.choose_files();
  add.disabled = state.busy;
  nav.append(add);
}

async function select(i) {
  state.current = i;
  renderFiles();
  toggleDraw(false);
  const p = state.plans.get(i);
  if (p) {
    state.page = firstPageWithBoxes(p);
    await showPlan();
  } else {
    showDropFor(state.files[i]);
  }
}

function clearReview() {
  $("findings").innerHTML = "";
  $("foundTitle").textContent = "Review";
  $("allToggle").hidden = true;
  $("emptyNote").hidden = false;
}

function showDropFor(file) {
  $("viewer").hidden = true;
  clearReview();
  $("drop").hidden = false;
  if (!file) {
    $("dropTitle").textContent = "Drop photos, PDFs or videos";
    $("dropText").textContent = "I'll find the private bits and black them out. Nothing leaves this computer.";
    $("chooseBtn").textContent = "Choose files";
    return;
  }
  const n = state.files.length;
  $("dropTitle").textContent = n > 1 ? `${n} files ready` : `Got ${file.name}`;
  $("dropText").textContent = file.status === "error"
    ? `This file could not be read: ${file.error}`
    : "Pick what to hide on the left, then press the yellow button. You can drop more files at any time.";
  $("chooseBtn").textContent = "Add more files";
}

async function showPlan() {
  $("drop").hidden = true;
  $("viewer").hidden = false;
  renderFindings();
  setupPager();
  await renderPage();
}

// ---------- findings list ----------
const SOURCE = { gemma: "found by Gemma", "pii model": "found by the personal data model", rules: "matched a pattern", you: "from your list", faces: "face detector", manual: "drawn by you" };

function renderFindings() {
  const p = plan();
  const list = $("findings");
  list.innerHTML = "";
  $("emptyNote").hidden = true;
  const n = p.findings.length;
  $("foundTitle").textContent = n ? `Found ${n} thing${n === 1 ? "" : "s"} to hide` : "Nothing found";
  $("allToggle").hidden = !n;
  $("allToggle").textContent = p.findings.every((f) => !f.enabled) ? "Hide all" : "Show all";

  let group = null;
  for (const f of p.findings) {
    const label = f.source === "manual" ? "Drawn by hand" : f.label;
    if (label !== group) {
      group = label;
      list.append(Object.assign(document.createElement("li"), { className: "group", textContent: label }));
    }
    const li = document.createElement("li");
    li.className = "item" + (f.enabled ? "" : " off");
    li.dataset.id = f.id;
    li.title = SOURCE[f.source] || "";

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = f.enabled;
    cb.setAttribute("aria-label", `Hide ${f.text || label}`);
    cb.onchange = () => setEnabled(f, cb.checked);
    cb.onclick = (e) => e.stopPropagation();

    const t = Object.assign(document.createElement("span"), { className: "t", textContent: f.text || label });
    const right = document.createElement("span");
    if (f.source === "manual") {
      const x = Object.assign(document.createElement("button"), { className: "x", textContent: "×", title: "Remove box" });
      x.setAttribute("aria-label", "Remove this box");
      x.onclick = async (e) => { e.stopPropagation(); applyPlan(await api.remove_manual(state.current, f.id)); };
      right.append(x);
    } else {
      right.className = "n";
      right.textContent = f.count > 1 ? `×${f.count}` : "";
    }
    li.append(cb, t, right);
    li.onclick = () => jumpTo(f);
    li.onmouseenter = () => highlight(f.id);
    li.onmouseleave = () => highlight(null);
    list.append(li);
  }
}

async function setEnabled(f, on) {
  f.enabled = on;
  await api.toggle(state.current, f.id, on);
  renderFindings();
  drawBoxes();
}

$("allToggle").onclick = async () => {
  const p = plan();
  const turnOn = p.findings.every((f) => !f.enabled);
  for (const f of p.findings) {
    f.enabled = turnOn;
    await api.toggle(state.current, f.id, turnOn);
  }
  renderFindings();
  drawBoxes();
};

function jumpTo(f) {
  const pages = Object.keys(f.boxes).map(Number).filter((p) => p >= 0).sort((a, b) => a - b);
  const next = pages.find((p) => p > state.page) ?? pages[0];
  if (next !== undefined && next !== state.page) goTo(next);
  highlight(f.id);
}

function highlight(id) {
  state.hot = id;
  document.querySelectorAll(".item").forEach((el) => el.classList.toggle("hot", el.dataset.id === id));
  document.querySelectorAll(".box").forEach((el) => el.classList.toggle("hot", el.dataset.id === id));
}

function applyPlan(p) {
  state.plans.set(p.file, p);
  renderFindings();
  drawBoxes();
}

// ---------- preview ----------
function setupPager() {
  const n = plan().pages.length;
  $("nav").hidden = n < 2;
  $("scrub").max = String(n - 1);
  $("scrub").value = String(state.page);
}

function updateWhere() {
  const p = plan();
  const pg = p.pages[state.page];
  $("where").textContent = p.kind === "video" ? fmtTime(pg.time || 0) : `Page ${state.page + 1} of ${p.pages.length}`;
  $("scrub").value = String(state.page);
}

async function goTo(i) {
  const n = plan().pages.length;
  state.page = Math.max(0, Math.min(n - 1, i));
  await renderPage();
}

async function renderPage() {
  updateWhere();
  const file = state.current;
  const i = state.page;
  const key = `${file}:${i}`;
  let src = imageCache.get(key);
  if (!src) {
    src = await api.page_image(file, i);
    imageCache.set(key, src);
  }
  if (i !== state.page || file !== state.current) return; // user moved on while loading
  const img = $("pageImg");
  if (img.src !== src) {
    img.src = src;
    await img.decode().catch(() => {});
  }
  drawBoxes();
}

function drawBoxes() {
  const layer = $("boxes");
  layer.innerHTML = "";
  const p = plan();
  if (!p) return;
  const page = p.pages[state.page];
  const sx = 100 / page.width;
  const sy = 100 / page.height;
  let k = 0;
  for (const f of p.findings) {
    for (const [x0, y0, x1, y1] of boxesFor(f, page.index)) {
      const d = document.createElement("div");
      d.className = "box" + (f.enabled ? "" : " off") + (state.hot === f.id ? " hot" : "");
      d.dataset.id = f.id;
      Object.assign(d.style, {
        left: `${x0 * sx}%`, top: `${y0 * sy}%`,
        width: `${(x1 - x0) * sx}%`, height: `${(y1 - y0) * sy}%`,
      });
      d.style.setProperty("--d", `${Math.min(k++ * 35, 900)}ms`);
      layer.append(d);
    }
  }
  // the marker-stroke reveal plays once, right after a fresh analysis
  layer.classList.toggle("reveal", state.reveal);
  state.reveal = false;
}

$("scrub").oninput = (e) => goTo(Number(e.target.value));
$("prevBtn").onclick = () => goTo(state.page - 1);
$("nextBtn").onclick = () => goTo(state.page + 1);
document.addEventListener("keydown", (e) => {
  if (!plan() || ["TEXTAREA", "INPUT"].includes(e.target.tagName)) return;
  if (e.key === "ArrowLeft") goTo(state.page - 1);
  if (e.key === "ArrowRight") goTo(state.page + 1);
  if (e.key === "Escape" && state.drawing) toggleDraw(false);
});

// ---------- drawing boxes by hand ----------
function toggleDraw(on) {
  state.drawing = on;
  $("drawBtn").setAttribute("aria-pressed", String(on));
  $("boxes").classList.toggle("drawing", on);
  if (on) setStatus(plan().kind === "video" ? "Drag over the area to hide. On videos it covers that spot for the whole clip." : "Drag over the area to hide.");
}
$("drawBtn").onclick = () => toggleDraw(!state.drawing);

$("boxes").addEventListener("pointerdown", (e) => {
  if (!state.drawing) return;
  const layer = $("boxes");
  const r = layer.getBoundingClientRect();
  const page = plan().pages[state.page];
  const start = { x: e.clientX - r.left, y: e.clientY - r.top };
  const ghost = Object.assign(document.createElement("div"), { className: "box ghost" });
  layer.append(ghost);
  layer.setPointerCapture(e.pointerId);
  const rect = (ev) => {
    const x = Math.max(0, Math.min(r.width, ev.clientX - r.left));
    const y = Math.max(0, Math.min(r.height, ev.clientY - r.top));
    return [Math.min(start.x, x), Math.min(start.y, y), Math.max(start.x, x), Math.max(start.y, y)];
  };
  const move = (ev) => {
    const [x0, y0, x1, y1] = rect(ev);
    Object.assign(ghost.style, { left: `${x0}px`, top: `${y0}px`, width: `${x1 - x0}px`, height: `${y1 - y0}px` });
  };
  const up = async (ev) => {
    layer.removeEventListener("pointermove", move);
    layer.removeEventListener("pointerup", up);
    const [x0, y0, x1, y1] = rect(ev);
    ghost.remove();
    if (x1 - x0 < 4 || y1 - y0 < 4) return;
    const kx = page.width / r.width;
    const ky = page.height / r.height;
    applyPlan(await api.add_box(state.current, state.page, [x0 * kx, y0 * ky, x1 * kx, y1 * ky]));
  };
  layer.addEventListener("pointermove", move);
  layer.addEventListener("pointerup", up);
});

// ---------- actions ----------
$("findBtn").onclick = () => {
  if (!state.files.length) return;
  const settings = readSettings();
  if (!settings.hide.length && !settings.also.trim()) {
    setStatus("Tick at least one kind of data, or type something under Also hide.", "error");
    return;
  }
  state.busy = true;
  state.plans.clear();
  imageCache.clear();
  toggleDraw(false);
  showDropFor(state.files[state.current]);
  renderFiles();
  syncButtons();
  setStatus("Starting", "busy");
  api.analyse(settings);
};

$("exportBtn").onclick = async () => {
  state.busy = true;
  syncButtons();
  setStatus("Choose where to save", "busy");
  const started = await api.export();
  if (!started) {
    state.busy = false;
    setStatus("");
    syncButtons();
  }
};

$("chooseBtn").onclick = () => api.choose_files();

// visual feedback while files are dragged over the window (the drop itself is handled in Python)
let dragDepth = 0;
document.addEventListener("dragenter", () => { dragDepth++; $("drop").classList.add("over"); });
document.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("drop").classList.remove("over"); } });
document.addEventListener("drop", () => { dragDepth = 0; $("drop").classList.remove("over"); });

async function start() {
  const s = await api.status();
  renderCategories(s.categories);
  $("engine").innerHTML = s.ready
    ? `<span class="dot"></span><b>${prettyModel(s.model)}</b> and a personal data model run on this computer. Files never leave it.`
    : `<span class="dot off"></span><b>${prettyModel(s.model)} is not installed.</b> Names and addresses will rely on the small personal data model only. Install <b>Ollama</b> and run <code>ollama pull ${s.model}</code>.`;
  syncButtons();
}

window.addEventListener("pywebviewready", () => {
  api = window.pywebview.api;
  start();
});
