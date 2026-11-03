/* ppt2kb web UI - plain JavaScript, no build step, no external resources. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ i18n
  let lang = (function () { try { return localStorage.getItem("ppt2kb.lang") || "en"; } catch (e) { return "en"; } })();
  function t(key, vars) {
    let s = (window.I18N[lang] && window.I18N[lang][key]) || window.I18N.en[key] || key;
    if (vars) Object.keys(vars).forEach(k => { s = s.replace(new RegExp("\\{" + k + "\\}", "g"), String(vars[k])); });
    return s;
  }
  function applyLang(root) {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "he" ? "rtl" : "ltr";
    (root || document).querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.getAttribute("data-i18n")); });
    document.getElementById("lang-toggle").textContent = lang === "he" ? "English" : "עברית";
    if (document.getElementById("theme-toggle")) applyTheme(currentTheme());  // refresh the toggle's label in the new language
  }
  document.getElementById("lang-toggle").addEventListener("click", () => {
    lang = lang === "he" ? "en" : "he";
    try { localStorage.setItem("ppt2kb.lang", lang); } catch (e) { /* ignore */ }
    applyLang();
    route();
  });

  // ------------------------------------------------------------------ theme
  // The choice is kept per browser (localStorage) and applied before the first paint by /static/theme.js
  // (loaded in <head>), so there is no flash; without a choice the system preference is followed. No backend involvement.
  function currentTheme() { return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light"; }
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const b = document.getElementById("theme-toggle");
    const dark = theme === "dark";
    b.setAttribute("aria-pressed", dark ? "true" : "false");
    const label = t(dark ? "theme.toLight" : "theme.toDark");
    b.title = label; b.setAttribute("aria-label", label);
    try { localStorage.setItem("ppt2kb.theme", theme); } catch (e) { /* ignore */ }
  }
  document.getElementById("theme-toggle").addEventListener("click", () => applyTheme(currentTheme() === "dark" ? "light" : "dark"));

  // ------------------------------------------------------------------ utils
  const $ = (sel, root) => (root || document).querySelector(sel);
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(k => { if (k === "text") e.textContent = attrs[k]; else if (k === "html") e.innerHTML = attrs[k]; else e.setAttribute(k, attrs[k]); });
    (children || []).forEach(c => e.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
    return e;
  }
  let toastTimer;
  function toast(msg, isErr) {
    const tt = document.getElementById("toast");
    tt.textContent = msg; tt.hidden = false; tt.className = "toast" + (isErr ? " err" : "");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { tt.hidden = true; }, isErr ? 7000 : 3000);
  }
  async function api(method, url, body, isForm) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      if (isForm) opts.body = body; else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    }
    const r = await fetch(url, opts);
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (!r.ok) {
      const msg = (data && (data.detail || data.error)) || (r.status + " " + r.statusText);
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  }
  function fmtDate(iso) { try { return new Date(iso).toLocaleString(lang === "he" ? "he-IL" : "en-GB"); } catch (e) { return iso; } }
  function statusPill(status) {
    const cls = { ready: "ok", published: "ok", partial: "warn", interrupted: "warn", failed: "err", publish_failed: "err", converting: "info", describing: "info", publishing: "info", uploaded: "" }[status] || "";
    return el("span", { class: "pill " + cls, text: t("status." + status) });
  }
  function useTemplate(id) { return document.getElementById(id).content.cloneNode(true); }

  // ----------------------------------------------------------------- health
  async function refreshHealth() {
    try {
      const h = await api("GET", "/api/health");
      const e = document.getElementById("health");
      e.textContent = "v" + h.version + (h.libreoffice ? "" : " · LibreOffice?");
      e.className = "pill " + (h.status === "ok" ? "ok" : "warn");
    } catch (e) { document.getElementById("health").className = "pill err"; }
  }

  // ----------------------------------------------------------------- router
  let pollTimer = null;
  function stopPolling() { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; } }
  function route() {
    stopPolling();
    const hash = location.hash || "#/jobs";
    document.querySelectorAll(".topbar nav a").forEach(a => a.classList.toggle("active", hash.startsWith(a.getAttribute("href"))));
    const view = document.getElementById("view");
    view.innerHTML = "";
    let m;
    if (hash === "#/upload") renderUpload(view);
    else if ((m = hash.match(/^#\/jobs\/([0-9a-f]{32})$/))) renderJob(view, m[1]);
    else if (hash === "#/settings") renderSettings(view);
    else renderJobs(view);
  }
  window.addEventListener("hashchange", route);

  // ------------------------------------------------------------------- jobs
  async function renderJobs(view) {
    view.appendChild(useTemplate("tpl-jobs"));
    applyLang(view);
    const tbody = $("#jobs-table tbody", view);
    try {
      const data = await api("GET", "/api/jobs");
      $("#jobs-empty", view).hidden = data.jobs.length > 0;
      data.jobs.forEach(j => {
        const tr = el("tr");
        tr.appendChild(el("td", {}, [el("a", { href: "#/jobs/" + j.id, text: j.title || j.display_name }), el("div", { class: "muted", text: j.display_name })]));
        tr.appendChild(el("td", {}, [statusPill(j.status)]));
        tr.appendChild(el("td", { text: j.slide_count ? (j.counts.done + "/" + j.slide_count) : "–" }));
        tr.appendChild(el("td", { text: fmtDate(j.created_at) }));
        const art = j.servicenow && j.servicenow.number ? el("a", { href: (j.servicenow.links || {}).form || "#", target: "_blank", rel: "noopener", text: j.servicenow.number }) : el("span", { class: "muted", text: "–" });
        tr.appendChild(el("td", {}, [art]));
        tr.appendChild(el("td", {}, [el("a", { class: "btn btn-small", href: "#/jobs/" + j.id, text: t("jobs.open") })]));
        tbody.appendChild(tr);
      });
      if (data.jobs.some(j => ["converting", "describing", "publishing", "uploaded"].includes(j.status))) pollTimer = setTimeout(route, 4000);
    } catch (e) { toast(t("common.error", { msg: e.message }), true); }
  }

  // ----------------------------------------------------------------- upload
  async function renderUpload(view) {
    view.appendChild(useTemplate("tpl-upload"));
    applyLang(view);
    try {
      const cfg = await api("GET", "/api/config");
      $("#upload-limits", view).textContent = t("upload.limits", { mb: cfg.max_upload_mb, slides: cfg.max_slides });
      const def = $('#upload-mode input[value="' + (cfg.image_attachment_mode || "embedded_full") + '"]', view);
      if (def) def.checked = true;
    } catch (e) { /* ignore */ }
    const dz = $("#dropzone", view), input = $("#file", view), nameEl = $("#file-name", view);
    input.addEventListener("change", () => { nameEl.textContent = input.files[0] ? input.files[0].name + " (" + Math.round(input.files[0].size / 1024 / 1024 * 10) / 10 + " MB)" : ""; });
    ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("over"); }));
    dz.addEventListener("drop", e => { if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; input.dispatchEvent(new Event("change")); } });
    $("#upload-form", view).addEventListener("submit", e => {
      e.preventDefault();
      if (!input.files[0]) return;
      const fd = new FormData();
      fd.append("file", input.files[0]);
      fd.append("title", $("#title", view).value);
      const modeIn = $('#upload-mode input[name="image_mode"]:checked', view);
      fd.append("image_mode", modeIn ? modeIn.value : "embedded_full");
      const btn = $("#upload-btn", view), prog = $("#upload-progress", view);
      btn.disabled = true; prog.hidden = false; prog.value = 0;
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/jobs");
      xhr.upload.onprogress = ev => { if (ev.lengthComputable) prog.value = Math.round(ev.loaded / ev.total * 100); };
      xhr.onload = () => {
        btn.disabled = false;
        if (xhr.status >= 200 && xhr.status < 300) {
          const job = JSON.parse(xhr.responseText);
          toast(t("upload.done"));
          location.hash = "#/jobs/" + job.id;
        } else {
          let msg = xhr.statusText;
          try { msg = JSON.parse(xhr.responseText).detail || msg; } catch (err) { /* ignore */ }
          toast(t("common.error", { msg }), true); prog.hidden = true;
        }
      };
      xhr.onerror = () => { btn.disabled = false; prog.hidden = true; toast(t("common.error", { msg: "network" }), true); };
      xhr.send(fd);
    });
  }

  // -------------------------------------------------------------------- job
  const slideNodes = new Map();
  async function renderJob(view, jobId) {
    slideNodes.clear();
    view.appendChild(useTemplate("tpl-job"));
    applyLang(view);
    const state = { job: null, kbLoaded: false };

    $("#btn-export-json", view).href = "/api/jobs/" + jobId + "/export.json";
    $("#btn-export-html", view).href = "/api/jobs/" + jobId + "/export.html";

    const titleEl = $("#job-title", view);
    titleEl.addEventListener("blur", async () => {
      const v = titleEl.textContent.trim();
      if (state.job && v && v !== state.job.title) {
        try { await api("PATCH", "/api/jobs/" + jobId, { title: v }); toast(t("job.titleSaved")); state.job.title = v; } catch (e) { toast(t("common.error", { msg: e.message }), true); }
      }
    });
    titleEl.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); titleEl.blur(); } });

    $("#btn-resume", view).addEventListener("click", async () => { try { await api("POST", "/api/jobs/" + jobId + "/resume"); load(); } catch (e) { toast(t("common.error", { msg: e.message }), true); } });
    $("#btn-retry-failed", view).addEventListener("click", async () => { try { await api("POST", "/api/jobs/" + jobId + "/retry", { slides: [] }); load(); } catch (e) { toast(t("common.error", { msg: e.message }), true); } });
    $("#btn-cancel", view).addEventListener("click", async () => { try { await api("POST", "/api/jobs/" + jobId + "/cancel"); } catch (e) { toast(t("common.error", { msg: e.message }), true); } });
    $("#btn-delete", view).addEventListener("click", async () => {
      if (!confirm(t("job.confirmDelete"))) return;
      try { await api("DELETE", "/api/jobs/" + jobId); location.hash = "#/jobs"; } catch (e) { toast(t("common.error", { msg: e.message }), true); }
    });
    $("#btn-preview", view).addEventListener("click", () => showPreview(jobId));
    $("#filter-failed", view).addEventListener("change", () => renderSlides(view, state.job));
    $("#filter-review", view).addEventListener("change", () => renderSlides(view, state.job));
    $("#show-original", view).addEventListener("change", () => renderSlides(view, state.job));
    const modeSel = $("#job-image-mode", view);
    modeSel.addEventListener("change", async () => {
      const prev = state.job ? state.job.image_mode : "";
      const published = !!(state.job && state.job.servicenow && state.job.servicenow.sys_id);
      if (published && !confirm(t("job.confirmModeChange"))) { modeSel.value = prev; return; }
      try {
        await api("PATCH", "/api/jobs/" + jobId, { image_mode: modeSel.value });
        toast(t("job.modeSaved"));
        if (modeSel.value !== "full_slide" && state.job && state.job.images_total === 0 && state.job.slide_count && state.job.source_kind === "pptx") {
          try { await api("POST", "/api/jobs/" + jobId + "/images/extract"); } catch (e) { /* reported on publish */ }
        }
        load();
      } catch (e) { modeSel.value = prev; toast(t("common.error", { msg: e.message }), true); }
    });

    const kbSelect = $("#kb-select", view);
    async function loadKbs() {
      kbSelect.innerHTML = ""; kbSelect.appendChild(el("option", { value: "", text: t("common.loading") }));
      try {
        const data = await api("GET", "/api/servicenow/knowledge-bases");
        kbSelect.innerHTML = "";
        kbSelect.appendChild(el("option", { value: "", text: "—" }));
        data.knowledge_bases.forEach(kb => kbSelect.appendChild(el("option", { value: kb.sys_id, text: kb.title })));
        kbSelect.value = (state.job && state.job.kb_sys_id) || data.default || "";
        state.kbLoaded = true;
      } catch (e) { kbSelect.innerHTML = ""; kbSelect.appendChild(el("option", { value: "", text: t("publish.loadKb") })); toast(t("common.error", { msg: e.message }), true); }
    }
    $("#btn-load-kb", view).addEventListener("click", loadKbs);
    $("#btn-publish", view).addEventListener("click", async () => {
      if (!state.job) return;
      if (state.job.counts.needs_review) { toast(t("publish.needReview"), true); return; }
      if (state.job.counts.done !== state.job.slide_count || !state.job.slide_count) { toast(t("publish.needAll"), true); return; }
      if (!kbSelect.value) { toast(t("publish.kb"), true); return; }
      if (modeSel.value === "embedded" && state.job.images_selected === 0 && !confirm(t("publish.confirmNoImages"))) return;
      const changed = !!(state.job.servicenow && state.job.servicenow.mode_changed);
      if (!confirm(t(changed ? "publish.confirmRepublish" : "publish.confirm"))) return;
      try {
        await api("POST", "/api/jobs/" + jobId + "/publish", { kb_sys_id: kbSelect.value, attach_pptx: $("#attach-pptx", view).checked, image_mode: modeSel.value });
        load();
      } catch (e) { toast(t("common.error", { msg: e.message }), true); }
    });

    async function load() {
      try {
        const job = await api("GET", "/api/jobs/" + jobId);
        state.job = job;
        if (document.activeElement !== titleEl) titleEl.textContent = job.title || job.display_name;
        $("#job-meta", view).textContent = job.display_name + " · " + fmtDate(job.created_at) + (job.model ? " · " + job.model : "") + (job.macro_enabled ? " · ⚠ macro-enabled file" : "");
        $("#job-status-label", view).textContent = t("status." + job.status);
        $("#job-error", view).textContent = job.error ? " — " + job.error : "";
        const review = job.counts.needs_review || 0;
        $("#c-done", view).textContent = job.counts.done; $("#c-pending", view).textContent = job.counts.pending + job.counts.processing; $("#c-failed", view).textContent = job.counts.failed;
        $("#c-review", view).textContent = review; $("#c-review-pill", view).hidden = !review;
        const imgPill = $("#c-images", view);
        imgPill.hidden = !job.slide_count || job.source_kind === "ppt";
        imgPill.textContent = (job.image_mode || "embedded") === "embedded"
          ? t("job.imagesCount", { sel: job.images_selected || 0, total: job.images_total || 0 })
          : t("job.imagesAttached", { total: job.images_total || 0 });
        $("#job-progress", view).value = job.slide_count ? Math.round((job.counts.done + review) / job.slide_count * 100) : (job.status === "converting" ? 5 : 0);
        const running = ["converting", "describing", "publishing", "uploaded"].includes(job.status) || job.active;
        const resumable = job.counts.pending + job.counts.processing + job.counts.failed > 0 || ["uploaded", "interrupted"].includes(job.status);
        $("#btn-resume", view).hidden = !(["interrupted", "failed", "partial", "uploaded"].includes(job.status) && !job.active && resumable);
        $("#btn-retry-failed", view).hidden = !(job.counts.failed > 0 && !job.active);
        $("#btn-cancel", view).hidden = !(job.active && ["converting", "describing"].includes(job.status));
        $("#btn-publish", view).disabled = running || review > 0 || job.counts.done !== job.slide_count || !job.slide_count;
        $("#publish-review-note", view).hidden = !review;
        const mode = job.image_mode || "embedded";
        if (document.activeElement !== modeSel) modeSel.value = mode;
        $("#job-mode-pill", view).textContent = t("mode.title") + ": " + t("mode." + mode);
        const modeChanged = !!(job.servicenow && job.servicenow.mode_changed);
        $("#publish-mode-changed", view).hidden = !modeChanged;
        $("#btn-publish", view).textContent = t(modeChanged ? "publish.republish" : (job.servicenow && job.servicenow.number ? "publish.update" : "publish.create"));
        const imgNote = $("#publish-images-note", view);
        const vars = { sel: job.images_selected || 0, total: job.images_total || 0, n: job.slide_count || 0 };
        imgNote.textContent = mode === "embedded" ? t("publish.imagesEmbedded", vars) : mode === "embedded_full" ? t("publish.imagesEmbeddedFull", vars) : t("publish.imagesFull", vars);
        if (!state.kbLoaded && job.kb_sys_id && !kbSelect.value) { kbSelect.innerHTML = ""; kbSelect.appendChild(el("option", { value: job.kb_sys_id, text: job.kb_sys_id })); }
        renderPublishResult(view, job);
        renderSlides(view, job);
        if (running) pollTimer = setTimeout(load, job.status === "publishing" ? 1500 : 2500);
      } catch (e) { toast(t("common.error", { msg: e.message }), true); }
    }
    currentReload = () => { stopPolling(); load(); };
    load();
  }

  function renderPublishResult(view, job) {
    const box = $("#publish-result", view);
    const sn = job.servicenow || {};
    box.hidden = false; box.className = "result";
    box.innerHTML = "";
    if (job.status === "publishing") {
      const p = sn.progress || {};
      box.textContent = t("publish.inProgress", { stage: p.stage || "", done: p.done || 0, total: p.total || 0 });
    } else if (job.status === "published" && sn.number) {
      box.appendChild(el("strong", { text: t("publish.success", { number: sn.number }) }));
      box.appendChild(el("span", { text: " · sys_id " + sn.sys_id + " · " }));
      if (sn.links) {
        box.appendChild(el("a", { href: sn.links.form, target: "_blank", rel: "noopener", text: t("publish.open") }));
        box.appendChild(el("span", { text: " · " }));
        box.appendChild(el("a", { href: sn.links.view, target: "_blank", rel: "noopener", text: t("publish.view") }));
      }
    } else if (job.status === "publish_failed") {
      box.className = "result err";
      box.textContent = t("publish.failed", { error: sn.error || "?" });
      if (sn.number) box.appendChild(el("div", { text: t("publish.alreadyPublished", { number: sn.number }) }));
    } else if (sn.number) {
      box.textContent = t("publish.alreadyPublished", { number: sn.number });
    } else {
      box.hidden = true;
    }
  }

  function renderSlides(view, job) {
    if (!job) return;
    const container = $("#slides", view);
    const onlyFailed = $("#filter-failed", view).checked, onlyReview = $("#filter-review", view).checked, showOriginal = $("#show-original", view).checked;
    const seen = new Set();
    job.slides.forEach(s => {
      seen.add(s.number);
      let node = slideNodes.get(s.number);
      if (!node) {
        node = useTemplate("tpl-slide").firstElementChild;
        applyLang(node);
        slideNodes.set(s.number, node);
        wireSlide(node, job.id, s.number, () => currentReload());
        container.appendChild(node);
      }
      node.hidden = (onlyFailed && s.status !== "failed") || (onlyReview && s.status !== "needs_review");
      updateSlide(node, s, showOriginal, job);
    });
  }
  // re-load hook used by slide actions (set by renderJob)
  let currentReload = function () {};

  function wireSlide(node, jobId, number, reload) {
    const ta = $(".slide-content", node), titleIn = $(".slide-title", node);
    const markDirty = () => node.classList.add("dirty");
    ta.addEventListener("input", markDirty); titleIn.addEventListener("input", markDirty);
    async function save() {
      const r = await api("PATCH", "/api/jobs/" + jobId + "/slides/" + number, { edited_content: ta.value, title: titleIn.value });
      node.classList.remove("dirty"); node.dataset.edited = r.edited_content !== null ? "1" : "";
      return r;
    }
    $(".btn-save", node).addEventListener("click", async () => {
      try { await save(); toast(t("slide.saved")); } catch (e) { toast(t("common.error", { msg: e.message }), true); }
    });
    $(".btn-accept", node).addEventListener("click", async () => {
      if (!confirm(t("slide.confirmAccept"))) return;
      try {
        if (node.classList.contains("dirty")) await save();
        await api("POST", "/api/jobs/" + jobId + "/slides/" + number + "/accept");
        toast(t("slide.accepted")); reload();
      } catch (e) { toast(t("common.error", { msg: e.message }), true); }
    });
    $(".btn-section", node).addEventListener("click", () => showPreview(jobId, number));
    $(".thumbs", node).addEventListener("change", async e => {
      const cb = e.target;
      if (!cb.classList.contains("thumb-select")) return;
      cb.disabled = true;
      try {
        const r = await api("PATCH", "/api/jobs/" + jobId + "/slides/" + number + "/images/" + cb.dataset.idx, { selected: cb.checked });
        cb.closest(".thumb").classList.toggle("excluded", !r.selected);
        toast(r.selected ? t("slide.imageIncluded") : t("slide.imageExcluded"));
        reload();
      } catch (err) { cb.checked = !cb.checked; toast(t("common.error", { msg: err.message }), true); }
      cb.disabled = false;
    });
    $(".btn-reset", node).addEventListener("click", async () => {
      try {
        const r = await api("PATCH", "/api/jobs/" + jobId + "/slides/" + number, { reset: true });
        ta.value = r.content; node.classList.remove("dirty"); node.dataset.edited = "";
      } catch (e) { toast(t("common.error", { msg: e.message }), true); }
    });
    $(".btn-retry", node).addEventListener("click", async () => {
      try { await api("POST", "/api/jobs/" + jobId + "/retry", { slides: [number] }); toast(t("slide.retry")); location.hash = location.hash; route(); } catch (e) { toast(t("common.error", { msg: e.message }), true); }
    });
  }

  function updateSlide(node, s, showOriginal, job) {
    node.classList.toggle("failed", s.status === "failed");
    node.classList.toggle("review", s.status === "needs_review");
    $(".slide-no", node).textContent = "#" + s.number;
    const st = $(".slide-status", node);
    st.textContent = t("slideStatus." + s.status) + (s.edited_content !== null && s.edited_content !== undefined ? " · " + t("slide.edited") : "") + (s.reviewed ? " · " + t("slide.reviewed") : "");
    st.className = "slide-status pill " + ({ done: "ok", failed: "err", processing: "info", pending: "warn", needs_review: "review" }[s.status] || "");
    const img = $(".slide-image img", node);
    if (img.getAttribute("src") !== s.image_url) { img.src = s.image_url; img.alt = "Slide " + s.number; }
    $(".btn-accept", node).hidden = s.status !== "needs_review";
    // quality issues from validation (reviewer information)
    const q = $(".slide-quality", node), issues = s.quality || [];
    q.hidden = !issues.length;
    q.innerHTML = "";
    if (issues.length) {
      q.appendChild(el("strong", { text: s.status === "needs_review" ? t("slide.qualityBlocked") : t("slide.qualityWarn") }));
      const ul = el("ul");
      issues.forEach(code => ul.appendChild(el("li", { text: t("issue." + code) })));
      q.appendChild(ul);
      const unc = s.description && s.description.uncertainties;
      if (unc) q.appendChild(el("div", { class: "muted", text: t("slide.uncertainties") + " " + unc }));
    }
    renderThumbs(node, s, job);
    if (!node.classList.contains("dirty")) {
      $(".slide-title", node).value = s.title || "";
      const ta = $(".slide-content", node);
      ta.value = s.edited_content !== null && s.edited_content !== undefined ? s.edited_content : (s.content || "");
    }
    const orig = $(".slide-original", node);
    orig.hidden = !showOriginal || !(s.original_text || s.notes_text);
    $("pre", orig).textContent = (s.original_text || "") + (s.notes_text ? "\n\n[notes]\n" + s.notes_text : "");
    const stru = $(".slide-structured", node);
    stru.hidden = !s.description;
    if (s.description) $("pre", stru).textContent = JSON.stringify(s.description, null, 2);
    const err = $(".slide-error", node);
    err.hidden = !s.error; err.textContent = s.error || "";
    $(".slide-info", node).textContent = t("slide.attempts", { n: s.attempts }) + (s.render_error ? " · render: " + s.render_error : "");
    $(".btn-retry", node).disabled = s.status === "processing";
  }

  function renderThumbs(node, s, job) {
    const box = $(".slide-images", node), thumbs = $(".thumbs", node);
    const images = s.images || [];
    const mode = job ? (job.image_mode || "embedded") : "embedded";
    box.hidden = mode === "full_slide" || (job && job.source_kind === "ppt");
    if (box.hidden) return;
    $(".slide-images-title", node).textContent = t(mode === "embedded" ? "slide.embedded" : "slide.embeddedAttachOnly");
    const selected = images.filter(i => i.selected).length;
    const selectable = mode === "embedded";
    $(".slide-images-count", node).textContent = images.length ? (selectable ? t("slide.imagesCount", { sel: selected, total: images.length }) : t("slide.imagesAttachedAll", { total: images.length })) : "";
    $(".slide-images-empty", node).hidden = images.length > 0;
    const key = JSON.stringify([mode, images.map(i => [i.idx, i.selected, i.file_name, i.attachment_sys_id])]);
    if (thumbs.dataset.key === key) return;  // unchanged - keep the DOM (and any checkbox the user is clicking)
    thumbs.dataset.key = key;
    thumbs.innerHTML = "";
    images.forEach(im => {
      const card = el("div", { class: "thumb" + (im.selected || !selectable ? "" : " excluded") + (im.flagged ? " flagged" : "") });
      if (im.url) card.appendChild(el("img", { src: im.url, loading: "lazy", alt: (im.shape_name || "image") + " " + im.idx }));
      else card.appendChild(el("div", { class: "thumb-missing", text: t("slide.imageUnsupported", { fmt: im.original_format || "?" }) }));
      const cb = el("input", { type: "checkbox", class: "thumb-select", "data-idx": im.idx });
      cb.checked = !!im.selected;
      if (!im.supported || !im.url) cb.disabled = true;
      const label = el("label", { class: "check" }, [cb, el("span", { text: t("slide.includeImage") })]);
      if (mode !== "embedded") label.hidden = true;  // in the other modes every embedded image is attached; nothing to choose
      card.appendChild(label);
      const meta = [];
      meta.push((im.original_format || "").toUpperCase() + (im.width && im.height ? " " + im.width + "×" + im.height : ""));
      if (im.cropped) meta.push(t("img.cropped"));
      if (im.rotation) meta.push(t("img.rotated", { deg: im.rotation }));
      if (im.in_group) meta.push(t("img.group"));
      if (im.reuse_count > 1) meta.push(t("img.reused", { n: im.reuse_count }));
      if (im.source_kind === "background") meta.push(t("img.background"));
      card.appendChild(el("div", { class: "muted thumb-meta", text: meta.join(" · ") }));
      if (im.file_name) card.appendChild(el("div", { class: "thumb-name", dir: "ltr", text: im.file_name + (im.attachment_sys_id ? " ✔" : "") }));
      const reasons = (im.reasons || []).map(r => {
        const m = /^([a-z_]+):\s*(.*)$/.exec(r);  // "code: English text" from the classifier
        if (!m) return r;
        const key = "reason." + m[1];
        const tr = t(key);
        return tr === key ? m[2] : tr;
      });
      if (reasons.length) card.appendChild(el("div", { class: "muted thumb-reasons", text: (selectable ? (im.auto_selected ? t("img.autoIncluded") : t("img.autoExcluded")) + ": " : "") + reasons.join(", ") }));
      if (im.flagged) card.appendChild(el("div", { class: "err thumb-flag", text: t("img.flagged") }));
      if (im.note) card.appendChild(el("div", { class: "muted", text: im.note }));
      thumbs.appendChild(card);
    });
  }

  async function showPreview(jobId, slideNumber) {
    let dlg = document.getElementById("preview-dialog");
    if (!dlg) {
      dlg = el("dialog", { id: "preview-dialog" });
      const head = el("header", {}, [el("strong", { class: "dlg-title" }), el("button", { class: "btn btn-small", text: "✕" })]);
      head.lastChild.addEventListener("click", () => dlg.close());
      dlg.appendChild(head);
      dlg.appendChild(el("div", { class: "dialog-body" }));
      document.body.appendChild(dlg);
    }
    $(".dlg-title", dlg).textContent = slideNumber ? t("slide.sectionPreview", { n: slideNumber }) : t("job.preview");
    const body = $(".dialog-body", dlg);
    body.textContent = t("common.loading");
    dlg.showModal();
    try {
      const r = await fetch("/api/jobs/" + jobId + "/preview.html" + (slideNumber ? "?slide=" + slideNumber : ""));
      const html = await r.text();
      // The preview is server-generated from escaped text only (no scripts); render it as-is.
      body.innerHTML = html;
    } catch (e) { body.textContent = e.message; }
  }

  // --------------------------------------------------------------- settings
  async function renderSettings(view) {
    view.appendChild(useTemplate("tpl-settings"));
    applyLang(view);
    let cfg;
    try { cfg = await api("GET", "/api/config"); } catch (e) { toast(t("common.error", { msg: e.message }), true); return; }
    function fill(form) {
      Array.from(form.elements).forEach(inp => {
        if (!inp.name || !(inp.name in cfg)) return;
        if (inp.type === "checkbox") inp.checked = !!cfg[inp.name]; else inp.value = cfg[inp.name] === null || cfg[inp.name] === undefined ? "" : cfg[inp.name];
      });
      form.querySelectorAll(".secret-state").forEach(s => {
        const st = cfg.secrets[s.dataset.secret];
        s.textContent = st && st.set ? t("settings.secretSet", { source: st.source }) : t("settings.secretUnset");
      });
    }
    const forms = [$("#qwen-form", view), $("#proc-form", view), $("#sn-form", view)];
    forms.forEach(fill);
    forms.forEach(form => form.addEventListener("submit", async e => {
      e.preventDefault();
      const values = {};
      Array.from(form.elements).forEach(inp => {
        if (!inp.name) return;
        if (inp.type === "checkbox") values[inp.name] = inp.checked;
        else if (inp.type === "password") { if (inp.value) values[inp.name] = inp.value; }
        else values[inp.name] = inp.value;
      });
      try {
        const r = await api("PUT", "/api/config", { values });
        cfg = r.config; fill(form);
        form.querySelectorAll("input[type=password]").forEach(i => { i.value = ""; });
        if (r.rejected.length) toast(t("settings.rejected", { keys: r.rejected.join(", ") }), true); else toast(t("settings.saved"));
      } catch (err) { toast(t("common.error", { msg: err.message }), true); }
    }));
    async function test(url, out) {
      out.textContent = t("common.loading");
      try { const r = await api("POST", url); out.textContent = (r.ok ? "✔ " : "✖ ") + (r.detail || "") + (r.models && r.models.length ? " · " + r.models.slice(0, 5).join(", ") : ""); out.className = r.ok ? "muted" : "err"; }
      catch (e) { out.textContent = "✖ " + e.message; out.className = "err"; }
    }
    $("#test-qwen", view).addEventListener("click", () => test("/api/config/test/qwen", $("#qwen-test-result", view)));
    $("#test-sn", view).addEventListener("click", () => test("/api/config/test/servicenow", $("#sn-test-result", view)));
    const dl = $("#security-info", view);
    [["sec.tls", cfg.tls_verify ? t("common.yes") : t("common.no") + " ⚠"], ["sec.ca", cfg.ca_bundle || "(system)"], ["sec.hosts", (cfg.allowed_outbound_hosts || []).join(", ") || "–"], ["sec.locked", cfg.locked_hosts ? t("common.yes") : t("common.no")]]
      .forEach(([k, v]) => { dl.appendChild(el("dt", { text: t(k) })); dl.appendChild(el("dd", { text: v })); });
  }

  // ------------------------------------------------------------------- init
  applyLang();
  refreshHealth();
  setInterval(refreshHealth, 30000);
  route();
})();
