/* flowpilot dashboard — vanilla JS, hash router, SSE live updates. */
(() => {
  "use strict";

  // ------------------------------------------------------------------ icons
  const P = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    layers: '<path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
    activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    puzzle: '<path d="M19.4 13.6a2 2 0 1 0 0-3.2V7a1 1 0 0 0-1-1h-3.4a2 2 0 1 0-3.2 0H8.4a1 1 0 0 0-1 1v3.4a2 2 0 1 0 0 3.2V17a1 1 0 0 0 1 1h3.4a2 2 0 1 1 3.2 0h3.4a1 1 0 0 0 1-1v-3.4Z"/>',
    play: '<path d="M7 4.5v15a1 1 0 0 0 1.5.86l12.5-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5Z"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.64-6.36L21 8"/><path d="M21 3v5h-5"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
    webhook: '<path d="M18 16.98h-5.99c-1.1 0-1.95.94-2.48 1.9A4 4 0 0 1 2 17c.01-.7.2-1.4.57-2"/><path d="m6 17 3.13-5.78c.53-.97.1-2.18-.5-3.1a4 4 0 1 1 6.89-4.06"/><path d="m12 6 3.13 5.73C15.66 12.7 16.9 13 18 13a4 4 0 0 1 0 8"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    rss: '<path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1.5"/>',
    hand: '<path d="M18 11V6a2 2 0 0 0-4 0v1"/><path d="M14 10V4a2 2 0 0 0-4 0v2"/><path d="M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    skip: '<path d="M5 12h14"/>',
    zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    gauge: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    timer: '<path d="M10 2h4"/><path d="M12 14l3-3"/><circle cx="12" cy="14" r="8"/>',
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    code: '<path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/>',
    database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>',
    branch: '<circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/><path d="M6 9v6"/>',
    terminal: '<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/>',
    wand: '<path d="m15 4-1 1"/><path d="M18 3v3"/><path d="M21 6h-3"/><path d="m3 21 9-9"/><path d="M14 7l3 3"/>',
    mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
    archive: '<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
    bookmark: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>',
    pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  };
  const icon = (name, cls = "") =>
    `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || P.zap}</svg>`;
  const TRIGGER_ICON = { cron: "clock", interval: "repeat", webhook: "webhook", file: "file", feed: "rss", manual: "hand" };
  const STEP_ICON = {
    http: "globe", telegram: "send", transform: "wand", condition: "branch", branch: "branch", delay: "timer",
    log: "terminal", shell: "terminal", python: "code", email: "mail", "file.write": "file", "file.read": "file",
    sqlite: "database", state: "bookmark", archive: "archive",
  };

  // ---------------------------------------------------------------- helpers
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const view = () => $("#view");

  function ago(iso) {
    if (!iso) return "never";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 0) return "in " + span(-s);
    if (s < 5) return "just now";
    return span(s) + " ago";
  }
  function until(iso) {
    if (!iso) return "";
    const s = (new Date(iso).getTime() - Date.now()) / 1000;
    return s <= 0 ? "now" : "in " + span(s);
  }
  function span(s) {
    if (s < 60) return Math.round(s) + "s";
    if (s < 3600) return Math.round(s / 60) + "m";
    if (s < 86400) return Math.round(s / 3600) + "h";
    return Math.round(s / 86400) + "d";
  }
  function dur(ms) {
    if (ms == null) return "—";
    if (ms < 1000) return ms + " ms";
    if (ms < 60000) return (ms / 1000).toFixed(ms < 10000 ? 2 : 1) + " s";
    return Math.floor(ms / 60000) + "m " + Math.round((ms % 60000) / 1000) + "s";
  }
  const time = (iso) => (iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
  const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour12: false }) + "." + String(new Date(iso).getMilliseconds()).padStart(3, "0");
  const badge = (status, cls = "") => `<span class="badge ${esc(status)} ${cls}">${esc(status)}</span>`;

  function jsonHtml(value) {
    const text = JSON.stringify(value, null, 2) ?? "null";
    return esc(text).replace(
      /(&quot;(?:\\.|[^&\\]|&(?!quot;))*?&quot;)(\s*:)?|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g,
      (m, str, colon, bool) => {
        if (str) return colon ? `<span class="k">${str}</span>${colon}` : `<span class="s">${str}</span>`;
        if (bool) return `<span class="b">${m}</span>`;
        if (m === "null") return `<span class="z">${m}</span>`;
        return `<span class="n">${m}</span>`;
      });
  }
  function outputHtml(value) {
    if (typeof value === "string") return `<pre class="json text">${esc(value)}</pre>`;
    return `<pre class="json">${jsonHtml(value)}</pre>`;
  }
  function yamlHtml(src) {
    return src.split("\n").map((line) => {
      const e = esc(line);
      const ci = line.search(/(^|\s)#/);
      if (/^\s*#/.test(line)) return `<span class="c">${e}</span>`;
      let body = e, comment = "";
      if (ci > 0 && !/["']/.test(line.slice(0, ci))) {
        body = esc(line.slice(0, ci)); comment = `<span class="c">${esc(line.slice(ci))}</span>`;
      }
      body = body.replace(/^(\s*-?\s*)([\w.\-]+)(:)(?=\s|$)/, '$1<span class="k">$2</span>$3');
      body = body.replace(/(\{\{.*?\}\}|\{%.*?%\})/g, '<span class="t">$1</span>');
      body = body.replace(/(&quot;[^&]*?&quot;)/g, '<span class="s">$1</span>');
      return body + comment;
    }).join("\n");
  }

  // ------------------------------------------------------------------- api
  let token = localStorage.getItem("flowpilot.token") || "";
  async function api(path, opts = {}) {
    const headers = { Accept: "application/json", ...(opts.body ? { "Content-Type": "application/json" } : {}) };
    if (token) headers.Authorization = "Bearer " + token;
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401) { await askToken(); return api(path, opts); }
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) { /* ignore */ }
      throw new Error(detail);
    }
    return res.json();
  }
  function askToken() {
    return new Promise((resolve) => {
      const dlg = $("#token-dialog");
      dlg.addEventListener("close", () => {
        token = $("#token-input").value.trim();
        localStorage.setItem("flowpilot.token", token);
        connectEvents();
        resolve();
      }, { once: true });
      if (!dlg.open) dlg.showModal();
    });
  }
  const withToken = (url) => (token ? url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token) : url);

  function toast(msg, kind = "ok") {
    const el = document.createElement("div");
    el.className = "toast " + kind;
    el.innerHTML = icon(kind === "ok" ? "check" : "x") + `<span>${esc(msg)}</span>`;
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), 3800);
  }

  // ------------------------------------------------------------ live events
  let events = null;
  const listeners = new Set();
  function connectEvents() {
    if (events) events.close();
    const live = $("#live"), text = $("#live-text");
    events = new EventSource(withToken("/api/events"));
    events.onopen = () => { live.className = "live on"; text.textContent = "Live"; };
    events.onerror = () => { live.className = "live off"; text.textContent = "Reconnecting…"; };
    for (const type of ["run.started", "run.finished", "step.started", "step.finished", "workflow.updated"]) {
      events.addEventListener(type, (e) => {
        const data = JSON.parse(e.data);
        listeners.forEach((fn) => fn(data));
      });
    }
  }
  let refreshTimer = null;
  function scheduleRefresh(fn, delay = 400) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(fn, delay);
  }

  // ---------------------------------------------------------------- router
  let cleanup = [];
  const routes = [
    [/^\/?$/, overview, "overview"],
    [/^\/workflows\/?$/, workflowsPage, "workflows"],
    [/^\/workflows\/([^/]+)$/, workflowDetail, "workflows"],
    [/^\/runs\/?$/, runsPage, "runs"],
    [/^\/runs\/([0-9a-f]+)$/, runDetail, "runs"],
    [/^\/steps\/?$/, stepsPage, "steps"],
  ];
  async function route() {
    cleanup.forEach((fn) => fn()); cleanup = [];
    listeners.clear();
    const hash = decodeURIComponent(location.hash.replace(/^#/, "")) || "/";
    const path = hash.split("?")[0];
    for (const [re, fn, nav] of routes) {
      const m = path.match(re);
      if (m) {
        document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === nav));
        $("#top-actions").innerHTML = ""; $("#crumbs").innerHTML = "";
        view().innerHTML = '<div class="skeleton"></div>';
        try { await fn(...m.slice(1)); } catch (err) {
          view().innerHTML = `<div class="card empty">${icon("x")}<div>${esc(err.message)}</div></div>`;
        }
        return;
      }
    }
    location.hash = "#/";
  }
  function setTitle(title, crumbs = "") {
    $("#title").textContent = title;
    $("#crumbs").innerHTML = crumbs;
    document.title = title + " · flowpilot";
  }

  // ------------------------------------------------------------ components
  function spark(recent) {
    const items = (recent || []).slice(0, 20).reverse();
    const pad = Array.from({ length: Math.max(0, 20 - items.length) }, () => "<i></i>").join("");
    return `<div class="spark" title="last ${items.length} runs">${pad}${items.map((r) => `<i class="${esc(r.status)}" title="${esc(r.status)} · ${esc(time(r.started_at))}"></i>`).join("")}</div>`;
  }
  function stepChips(steps) {
    const shown = steps.slice(0, 5).map((s) => `<span class="chip">${icon(STEP_ICON[s.type] || "zap")}${esc(s.type)}</span>`).join("");
    return shown + (steps.length > 5 ? `<span class="chip">+${steps.length - 5}</span>` : "");
  }
  function workflowCard(wf) {
    const t = wf.trigger_type;
    const last = wf.last_run;
    const next = wf.enabled && wf.next_run ? `<span title="${esc(time(wf.next_run))}">next ${esc(until(wf.next_run))}</span>` : "";
    return `
      <article class="card wf ${wf.enabled ? "" : "disabled"}" data-wf="${esc(wf.name)}">
        <div class="wf-top">
          <div class="wf-icon t-${esc(t)}">${icon(TRIGGER_ICON[t] || "zap")}</div>
          <div class="wf-title">
            <a href="#/workflows/${encodeURIComponent(wf.name)}">${esc(wf.name)}</a>
            <div class="wf-desc">${esc(wf.description || "No description")}</div>
          </div>
          ${last ? badge(last.status) : ""}
        </div>
        <div class="chips"><span class="chip mono" title="${esc(wf.trigger_label)}">${icon(TRIGGER_ICON[t] || "zap")}${esc(wf.trigger_label)}</span></div>
        <div class="chips">${stepChips(wf.steps)}</div>
        <div class="wf-meta">${spark(wf.recent)}<div class="wf-when"><span>${last ? "last run " + esc(ago(last.started_at)) : "never run"}</span>${next ? `<span>${next}</span>` : ""}</div></div>
        <div class="wf-actions">
          <label class="switch"><input type="checkbox" data-toggle="${esc(wf.name)}" ${wf.enabled ? "checked" : ""}/><span class="track"></span>${wf.enabled ? "Enabled" : "Disabled"}</label>
          <button class="btn sm" data-run="${esc(wf.name)}">${icon("play")}Run now</button>
        </div>
      </article>`;
  }
  function bindWorkflowActions(root, after) {
    root.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", async (e) => {
      e.preventDefault();
      b.disabled = true;
      try {
        const res = await api(`/api/workflows/${encodeURIComponent(b.dataset.run)}/run`, { method: "POST", body: "{}" });
        toast(`Started ${b.dataset.run}`);
        location.hash = `#/runs/${res.run_id}`;
      } catch (err) { toast(err.message, "err"); b.disabled = false; }
    }));
    root.querySelectorAll("[data-toggle]").forEach((c) => c.addEventListener("change", async () => {
      const action = c.checked ? "enable" : "disable";
      try {
        await api(`/api/workflows/${encodeURIComponent(c.dataset.toggle)}/${action}`, { method: "POST" });
        toast(`${c.dataset.toggle} ${action}d`);
        after && after();
      } catch (err) { toast(err.message, "err"); c.checked = !c.checked; }
    }));
  }
  function runsTable(runs, { showWorkflow = true } = {}) {
    if (!runs.length) return `<div class="empty">${icon("inbox")}<div>No runs yet. Trigger a workflow to see it here.</div></div>`;
    return `<div class="table-wrap"><table>
      <thead><tr><th>Status</th>${showWorkflow ? "<th>Workflow</th>" : ""}<th>Trigger</th><th>Started</th><th>Duration</th><th>Run</th></tr></thead>
      <tbody>${runs.map((r) => `
        <tr data-href="#/runs/${esc(r.id)}">
          <td>${badge(r.status)}</td>
          ${showWorkflow ? `<td><span class="wf-link">${esc(r.workflow)}</span></td>` : ""}
          <td><span class="chip">${icon(TRIGGER_ICON[r.trigger_type] || "zap")}${esc(r.trigger_type)}</span></td>
          <td class="num" title="${esc(time(r.started_at))}">${esc(ago(r.started_at))}</td>
          <td class="num">${esc(dur(r.duration_ms))}</td>
          <td class="mono muted">${esc(r.id.slice(0, 8))}</td>
        </tr>`).join("")}</tbody></table></div>`;
  }
  function bindRows(root) {
    root.querySelectorAll("tr[data-href]").forEach((tr) => tr.addEventListener("click", () => { location.hash = tr.dataset.href; }));
  }
  function ring(rate) {
    const pct = rate == null ? 0 : rate * 100;
    const c = 2 * Math.PI * 22;
    return `<svg class="ring" viewBox="0 0 54 54"><circle cx="27" cy="27" r="22" fill="none" stroke="var(--surface-3)" stroke-width="6"/>
      <circle cx="27" cy="27" r="22" fill="none" stroke="url(#rg)" stroke-width="6" stroke-linecap="round" stroke-dasharray="${(c * pct) / 100} ${c}" transform="rotate(-90 27 27)"/>
      <defs><linearGradient id="rg" x1="0" x2="1"><stop offset="0" stop-color="#8b5cf6"/><stop offset="1" stop-color="#22d3ee"/></linearGradient></defs></svg>`;
  }
  function reloadButton() {
    $("#top-actions").innerHTML = `<button class="btn" id="reload">${icon("refresh")}Reload workflows</button>`;
    $("#reload").addEventListener("click", async () => {
      try {
        const res = await api("/api/reload", { method: "POST" });
        const errs = Object.keys(res.errors || {}).length;
        toast(`Loaded ${res.workflows.length} workflow(s)` + (errs ? `, ${errs} with errors` : ""), errs ? "err" : "ok");
        route();
      } catch (err) { toast(err.message, "err"); }
    });
  }

  // ----------------------------------------------------------------- pages
  async function overview() {
    setTitle("Overview", "Dashboard");
    reloadButton();
    const render = async () => {
      const [stats, wfs, runs] = await Promise.all([api("/api/stats"), api("/api/workflows"), api("/api/runs?limit=8")]);
      const rate = stats.success_rate;
      view().innerHTML = `
        <div class="kpis">
          <div class="card kpi"><div class="label">${icon("layers")}Workflows</div><div class="value">${stats.enabled}<span class="muted" style="font-size:16px"> / ${stats.workflows}</span></div><div class="sub">enabled</div></div>
          <div class="card kpi"><div class="label">${icon("activity")}Runs · 24h</div><div class="value">${stats.total}</div><div class="sub">${stats.failed} failed · ${stats.running} running</div></div>
          <div class="card kpi"><div class="label">${icon("gauge")}Success rate</div><div class="value">${rate == null ? "—" : (rate * 100).toFixed(rate === 1 ? 0 : 1) + "%"}</div><div class="sub">finished runs, 24h</div>${ring(rate)}</div>
          <div class="card kpi"><div class="label">${icon("timer")}Avg duration</div><div class="value">${dur(stats.avg_duration_ms)}</div><div class="sub">per run, 24h</div></div>
        </div>
        <div class="section">
          <div class="section-head"><h2 class="section-title">Workflows</h2><a class="muted small" href="#/workflows">View all →</a></div>
          <div class="wf-grid">${wfs.slice(0, 6).map(workflowCard).join("") || `<div class="card empty">No workflows found.</div>`}</div>
        </div>
        <div class="section card">
          <div class="card-head"><h2>Recent runs</h2><a class="muted small" href="#/runs">All runs →</a></div>
          <div style="margin-top:12px">${runsTable(runs.runs)}</div>
        </div>`;
      bindWorkflowActions(view(), render);
      bindRows(view());
    };
    await render();
    listeners.add((e) => { if (e.type.startsWith("run.") || e.type === "workflow.updated") scheduleRefresh(render); });
  }

  async function workflowsPage() {
    setTitle("Workflows", "Dashboard / Workflows");
    reloadButton();
    let filter = "";
    const render = async () => {
      const wfs = await api("/api/workflows");
      const shown = wfs.filter((w) => !filter || (w.name + " " + w.description + " " + w.trigger_type).toLowerCase().includes(filter));
      const grid = shown.map(workflowCard).join("") || `<div class="card empty">${icon("inbox")}<div>No matching workflows.</div></div>`;
      if (!$("#wf-search")) {
        view().innerHTML = `<div class="section-head" style="margin-top:0"><div class="filters"><input id="wf-search" type="search" placeholder="Search workflows…" /></div><span class="muted small" id="wf-count"></span></div><div class="wf-grid" id="wf-grid"></div>`;
        $("#wf-search").addEventListener("input", (e) => { filter = e.target.value.toLowerCase(); render(); });
      }
      $("#wf-grid").innerHTML = grid;
      $("#wf-count").textContent = `${wfs.filter((w) => w.enabled).length} enabled · ${wfs.length} total`;
      bindWorkflowActions($("#wf-grid"), render);
    };
    await render();
    listeners.add((e) => { if (e.type.startsWith("run.") || e.type === "workflow.updated") scheduleRefresh(render); });
  }

  async function workflowDetail(name) {
    const render = async () => {
      const [wf, runs] = await Promise.all([
        api(`/api/workflows/${encodeURIComponent(name)}`),
        api(`/api/runs?workflow=${encodeURIComponent(name)}&limit=15`),
      ]);
      setTitle(wf.name, `<a href="#/workflows">Workflows</a> / ${esc(wf.name)}`);
      $("#top-actions").innerHTML = `
        <label class="switch"><input type="checkbox" data-toggle="${esc(wf.name)}" ${wf.enabled ? "checked" : ""}/><span class="track"></span>${wf.enabled ? "Enabled" : "Disabled"}</label>
        <button class="btn primary" data-run="${esc(wf.name)}">${icon("play")}Run now</button>`;
      bindWorkflowActions($("#top-actions"), render);
      const nodes = [`<div class="node trigger"><span class="t">trigger · ${esc(wf.trigger_type)}</span><span class="n">${esc(wf.trigger_label)}</span></div>`]
        .concat(wf.steps.map((s) => `<div class="node"><span class="t">${esc(s.type)}</span><span class="n">${esc(s.name)}</span></div>`));
      const stateKeys = Object.keys(wf.state || {});
      view().innerHTML = `
        <div class="card"><div class="card-head"><h2>Pipeline</h2><span class="muted small">${esc(wf.description)}</span></div>
          <div class="pipeline">${nodes.join('<div class="edge"></div>')}</div></div>
        <div class="two-col section">
          <div class="card"><div class="card-head"><h2>Definition</h2><span class="muted small mono">${esc(wf.source || "")}</span></div>
            <div style="margin-top:14px">${wf.definition ? `<pre class="code">${yamlHtml(wf.definition)}</pre>` : '<div class="empty">Defined in Python</div>'}</div></div>
          <div style="display:flex;flex-direction:column;gap:16px">
            <div class="card"><div class="card-head"><h2>Details</h2></div><div class="card-body">
              <div class="chips" style="margin-bottom:12px"><span class="chip">${icon(TRIGGER_ICON[wf.trigger_type])}${esc(wf.trigger_type)}</span>${wf.tags.map((t) => `<span class="chip">#${esc(t)}</span>`).join("")}${wf.webhook_path ? `<span class="chip mono">${esc(wf.webhook_path)}</span>` : ""}</div>
              <div class="wf-meta" style="justify-content:flex-start;gap:18px">${spark(wf.recent)}<span>${wf.next_run && wf.enabled ? "next run " + esc(until(wf.next_run)) : wf.last_run ? "last run " + esc(ago(wf.last_run.started_at)) : "never run"}</span></div>
            </div></div>
            <div class="card"><div class="card-head"><h2>Persistent state</h2>${stateKeys.length ? `<button class="btn sm ghost" id="reset-state">Reset</button>` : ""}</div><div class="card-body">
              ${stateKeys.length ? `<pre class="json">${jsonHtml(wf.state)}</pre>` : '<span class="muted small">No state stored yet.</span>'}</div></div>
          </div>
        </div>
        <div class="section card"><div class="card-head"><h2>Run history</h2><span class="muted small">${runs.total} total</span></div><div style="margin-top:12px">${runsTable(runs.runs, { showWorkflow: false })}</div></div>`;
      bindRows(view());
      const reset = $("#reset-state");
      if (reset) reset.addEventListener("click", async () => {
        await api(`/api/workflows/${encodeURIComponent(name)}/state`, { method: "DELETE" });
        toast("State cleared"); render();
      });
    };
    await render();
    listeners.add((e) => { if (e.workflow === name && (e.type.startsWith("run.") || e.type === "workflow.updated")) scheduleRefresh(render); });
  }

  async function runsPage() {
    setTitle("Runs", "Dashboard / Runs");
    const wfs = await api("/api/workflows");
    const params = new URLSearchParams(location.hash.split("?")[1] || "");
    let wf = params.get("workflow") || "", status = params.get("status") || "";
    view().innerHTML = `
      <div class="section-head" style="margin-top:0">
        <div class="filters">
          <select id="f-wf"><option value="">All workflows</option>${wfs.map((w) => `<option ${w.name === wf ? "selected" : ""}>${esc(w.name)}</option>`).join("")}</select>
          <select id="f-status"><option value="">Any status</option>${["success", "failed", "running", "cancelled"].map((s) => `<option ${s === status ? "selected" : ""}>${s}</option>`).join("")}</select>
        </div><span class="muted small" id="runs-total"></span>
      </div>
      <div class="card" id="runs-card"></div>`;
    const render = async () => {
      const q = new URLSearchParams({ limit: "100" });
      if (wf) q.set("workflow", wf);
      if (status) q.set("status", status);
      const data = await api("/api/runs?" + q);
      $("#runs-card").innerHTML = runsTable(data.runs);
      $("#runs-total").textContent = `${data.total} run(s)`;
      bindRows($("#runs-card"));
    };
    $("#f-wf").addEventListener("change", (e) => { wf = e.target.value; render(); });
    $("#f-status").addEventListener("change", (e) => { status = e.target.value; render(); });
    await render();
    listeners.add((e) => { if (e.type.startsWith("run.")) scheduleRefresh(render); });
  }

  async function runDetail(id) {
    const run = await api(`/api/runs/${id}`);
    setTitle(run.workflow, `<a href="#/runs">Runs</a> / <span class="mono">${esc(id.slice(0, 12))}</span>`);
    $("#top-actions").innerHTML = `<a class="btn" href="#/workflows/${encodeURIComponent(run.workflow)}">${icon("layers")}Workflow</a><button class="btn primary" data-run="${esc(run.workflow)}">${icon("refresh")}Run again</button>`;
    bindWorkflowActions($("#top-actions"));
    view().innerHTML = `
      <div class="card run-head" id="run-head"></div>
      <div class="run-grid">
        <div class="card"><div class="card-head"><h2>Steps</h2><span class="muted small" id="step-count"></span></div><ol class="timeline" id="timeline"></ol></div>
        <div>
          <div class="card" style="overflow:hidden">
            <div class="console-head"><div class="lights"><i></i><i></i><i></i></div><span id="console-status">live log</span></div>
            <div class="console" id="console"></div>
          </div>
          <div class="card section"><div class="card-head"><h2>Trigger payload</h2></div><div class="card-body"><pre class="json">${jsonHtml(run.trigger_payload)}</pre></div></div>
        </div>
      </div>`;

    const head = (r) => {
      $("#run-head").innerHTML = `
        <div>${badge(r.status, "lg")}</div>
        <div class="field"><div class="k">Trigger</div><div class="v">${esc(r.trigger_type)}</div></div>
        <div class="field"><div class="k">Started</div><div class="v">${esc(time(r.started_at))}</div></div>
        <div class="field"><div class="k">Duration</div><div class="v">${esc(r.status === "running" ? "running…" : dur(r.duration_ms))}</div></div>
        <div class="field"><div class="k">Run ID</div><div class="v mono">${esc(r.id)}</div></div>
        ${r.error ? `<div class="field" style="flex-basis:100%"><div class="k">Error</div><div class="v" style="color:var(--fail);font-weight:500">${esc(r.error)}</div></div>` : ""}`;
    };
    const timeline = (steps) => {
      $("#step-count").textContent = `${steps.length} step(s)`;
      const dot = { success: "check", failed: "x", skipped: "skip", running: "refresh" };
      $("#timeline").innerHTML = steps.map((s) => `
        <li class="tl-item ${esc(s.status)}">
          <span class="tl-dot">${icon(dot[s.status] || "skip")}</span>
          <div class="tl-row"><div><span class="tl-name">${esc(s.step_id)}</span> <span class="tl-type">${esc(s.type)}</span></div>
          <span class="muted small">${s.attempts > 1 ? esc(s.attempts) + " attempts · " : ""}${esc(s.status === "running" ? "running…" : dur(s.duration_ms))}</span></div>
          ${s.error ? `<div class="tl-err">${esc(s.error)}</div>` : ""}
          ${s.output != null ? `<details class="out"><summary>Output</summary>${outputHtml(s.output)}</details>` : ""}
        </li>`).join("") || '<li class="empty">Waiting for the first step…</li>';
    };
    head(run); timeline(run.steps);

    const consoleEl = $("#console");
    const seen = new Set();
    const addLog = (log, animate) => {
      if (seen.has(log.id)) return;
      seen.add(log.id);
      const line = document.createElement("div");
      line.className = "log-line" + (animate ? " new" : "");
      line.innerHTML = `<span class="ts">${esc(clock(log.ts))}</span><span class="lvl ${esc(log.level)}">${esc(log.level.toUpperCase())}</span><span class="msg">${log.step_id ? `<span class="step">[${esc(log.step_id)}]</span> ` : ""}${esc(log.message)}</span>`;
      const cursor = consoleEl.querySelector(".cursor");
      consoleEl.insertBefore(line, cursor);
      consoleEl.scrollTop = consoleEl.scrollHeight;
    };
    consoleEl.innerHTML = '<span class="cursor"></span>';
    (run.logs || []).forEach((l) => addLog(l, false));

    const refresh = async () => { const r = await api(`/api/runs/${id}`); head(r); timeline(r.steps); return r; };
    if (run.status === "running") {
      const es = new EventSource(withToken(`/api/runs/${id}/stream`));
      $("#console-status").textContent = "● streaming";
      es.addEventListener("log", (e) => addLog(JSON.parse(e.data).log, true));
      es.addEventListener("step.started", () => scheduleRefresh(refresh, 150));
      es.addEventListener("step.finished", () => scheduleRefresh(refresh, 150));
      es.addEventListener("end", async () => {
        es.close();
        $("#console-status").textContent = "finished";
        consoleEl.querySelector(".cursor")?.remove();
        await refresh();
      });
      cleanup.push(() => es.close());
    } else {
      $("#console-status").textContent = `${run.logs.length} line(s)`;
      consoleEl.querySelector(".cursor")?.remove();
    }
  }

  async function stepsPage() {
    setTitle("Step types", "Dashboard / Step types");
    const types = await api("/api/steps");
    view().innerHTML = `<div class="steps-grid">${types.map((t) => `
      <div class="card step-card">
        <div style="display:flex;justify-content:space-between;align-items:center"><h3>${esc(t.name)}</h3>${t.source !== "builtin" ? `<span class="chip">plugin · ${esc(t.source)}</span>` : `<span class="muted">${icon(STEP_ICON[t.name] || "zap")}</span>`}</div>
        <p>${esc(t.description)}</p>
        <div class="params">${Object.entries(t.params).map(([k, p]) => `<span class="chip mono ${p.required ? "req" : ""}" title="${esc(p.type)}${p.required ? " (required)" : " = " + esc(JSON.stringify(p.default))}">${esc(k)}</span>`).join("")}</div>
      </div>`).join("")}</div>`;
  }

  // ------------------------------------------------------------------ boot
  document.querySelectorAll("[data-icon]").forEach((el) => { el.outerHTML = icon(el.dataset.icon); });
  window.addEventListener("hashchange", route);
  fetch("/api/health").then((r) => r.json()).then((h) => { $("#version").textContent = "v" + h.version; }).catch(() => {});
  connectEvents();
  route();
  setInterval(() => document.querySelectorAll("[data-rel]").forEach((el) => { el.textContent = ago(el.dataset.rel); }), 30000);
})();
