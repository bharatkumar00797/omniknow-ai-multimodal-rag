"use strict";
// Dashboard for the OmniKnow API. All server data is rendered with textContent only.
(function () {
  const $ = (id) => document.getElementById(id);
  const TABS = ["ask", "docs", "evals"];
  const CITE_RE = /\[([a-z0-9][a-z0-9-]*#\d+)\]/g;
  const state = { config: null, tab: "ask", question: "" };

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function headers() {
    const h = { "Content-Type": "application/json" };
    const key = $("apikey").value.trim();
    if (key) h["X-API-Key"] = key;
    return h;
  }

  async function api(path, options) {
    const res = await fetch(path, Object.assign({ headers: headers() }, options || {}));
    const ctype = res.headers.get("content-type") || "";
    const body = ctype.includes("json") ? await res.json() : await res.text();
    if (!res.ok) {
      let detail = body && body.detail !== undefined ? body.detail : body;
      if (Array.isArray(detail)) detail = detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
      throw new Error(res.status + ": " + (typeof detail === "string" ? detail : JSON.stringify(detail)));
    }
    return body;
  }

  function principal() { return $("principal").value; }

  function modality(kind) { return el("span", "mod mod-" + kind, kind); }

  // ------------------------------------------------------------ deep links
  function readHash() {
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    const tab = params.get("tab");
    return {
      q: (params.get("q") || "").slice(0, 1000),
      as: params.get("as") || "",
      tab: TABS.includes(tab) ? tab : "ask",
    };
  }

  function writeHash() {
    const params = new URLSearchParams();
    if (state.question) params.set("q", state.question);
    params.set("as", principal());
    params.set("tab", state.tab);
    history.replaceState(null, "", "#" + params.toString());
  }

  function showTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".tabs button").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
    TABS.forEach((t) => { $("tab-" + t).hidden = t !== tab; });
    $("result").hidden = tab !== "ask" || !$("answer").textContent;
    if (tab === "docs") loadDocuments();
    writeHash();
  }

  // ------------------------------------------------------------------ init
  async function init() {
    try {
      state.config = await api("/api/config");
    } catch (err) { $("status").textContent = err.message; return; }
    const cfg = state.config;
    $("mode").textContent = cfg.access_mode + " | " + cfg.provider + " | v" + cfg.version;
    $("banner").hidden = !cfg.simulated;
    $("key-wrap").hidden = !cfg.auth_required;
    $("apikey").value = sessionStorage.getItem("omniknow-key") || "";

    const select = $("principal");
    select.replaceChildren();
    cfg.principals.forEach((name) => {
      const opt = el("option", null, name);
      opt.value = name;
      select.appendChild(opt);
    });
    const hash = readHash();
    select.value = cfg.principals.includes(hash.as) ? hash.as : cfg.default_principal;

    const chips = $("examples");
    chips.replaceChildren();
    cfg.examples.forEach((ex) => {
      const chip = el("button", "chip", ex.label + " · " + ex.principal);
      chip.type = "button";
      chip.title = ex.question;
      chip.addEventListener("click", () => {
        $("question").value = ex.question;
        $("principal").value = ex.principal;
        onPrincipal();
        ask();
      });
      chips.appendChild(chip);
    });

    if (cfg.auth_required && !$("apikey").value) {
      $("status").textContent = "Enter an API key to continue.";
    }
    await refreshGroups();
    showTab(hash.tab);
    if (hash.q) {
      $("question").value = hash.q;
      ask();
    }
  }

  async function refreshGroups() {
    try {
      const data = await api("/api/principals");
      const me = data.principals.find((p) => p.name === principal());
      $("groups").textContent = me
        ? "groups: " + me.groups.join(", ") + " · " + me.visible_documents + " documents visible"
        : "";
    } catch (err) { $("groups").textContent = err.message; }
  }

  function onPrincipal() {
    refreshGroups();
    if (state.tab === "docs") loadDocuments();
    writeHash();
  }

  // ------------------------------------------------------------------- ask
  async function ask() {
    const question = $("question").value.trim();
    if (!question) { $("status").textContent = "Type a question first."; return; }
    state.question = question;
    if (state.tab !== "ask") showTab("ask");
    writeHash();
    $("ask").disabled = true;
    $("status").textContent = "Retrieving and verifying...";
    try {
      const data = await api("/api/ask", {
        method: "POST",
        body: JSON.stringify({ question: question, principal: principal() }),
      });
      renderAnswer(data);
      $("status").textContent = data.simulated ? "Simulated demo answer (mock provider)." : "";
    } catch (err) {
      $("status").textContent = err.message;
    } finally {
      $("ask").disabled = false;
    }
  }

  function focusSource(chunkId) {
    document.querySelectorAll("#sources .card").forEach((card) => {
      const match = card.dataset.chunk === chunkId;
      card.classList.toggle("active", match);
      if (match) card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }

  function renderAnswer(data) {
    const a = data.answer;
    $("result").hidden = false;
    $("confidence").textContent = "confidence: " + a.confidence;
    $("confidence").className = "badge conf-" + a.confidence;
    $("grounded").textContent = a.grounded ? "grounded" : "abstained";
    $("grounded").className = "badge " + (a.grounded ? "yes" : "no");
    $("provider").textContent = "as " + a.principal + " · " + a.provider + (data.simulated ? " · simulated" : "");

    // Answer text with clickable [doc#n] citation markers (text nodes + buttons, no HTML parsing).
    const answer = $("answer");
    answer.replaceChildren();
    const cited = new Set(data.sources.map((s) => s.chunk_id));
    let last = 0;
    for (const m of a.answer.matchAll(CITE_RE)) {
      answer.appendChild(document.createTextNode(a.answer.slice(last, m.index)));
      if (cited.has(m[1])) {
        const btn = el("button", "cite", m[1]);
        btn.type = "button";
        btn.addEventListener("click", () => focusSource(m[1]));
        answer.appendChild(btn);
      } else {
        answer.appendChild(document.createTextNode(m[0]));
      }
      last = m.index + m[0].length;
    }
    answer.appendChild(document.createTextNode(a.answer.slice(last)));

    const subs = $("subqueries");
    subs.replaceChildren();
    a.sub_queries.forEach((q) => subs.appendChild(el("li", null, q)));
    $("subqueries-wrap").hidden = a.sub_queries.length < 2;

    const sources = $("sources");
    sources.replaceChildren();
    if (!data.sources.length) sources.appendChild(el("p", "hint", "No sources cited."));
    data.sources.forEach((s) => {
      const card = el("div", "card");
      card.dataset.chunk = s.chunk_id;
      const title = el("div", "title");
      title.appendChild(modality(s.modality));
      title.appendChild(document.createTextNode(s.title));
      card.appendChild(title);
      card.appendChild(el("div", "loc", s.chunk_id + " · " + s.locator));
      card.appendChild(el("pre", null, s.text));
      sources.appendChild(card);
    });

    const flags = $("flags");
    flags.replaceChildren();
    if (!a.security_flags.length) flags.appendChild(el("p", "hint", "No injection patterns in retrieved text."));
    a.security_flags.forEach((f) => {
      const card = el("div", "card flag");
      card.appendChild(el("div", "title", "QUARANTINED · " + f.kind));
      card.appendChild(el("div", "loc", f.chunk_id));
      card.appendChild(el("pre", null, f.excerpt));
      flags.appendChild(card);
    });
    if (a.dropped_citations.length) {
      flags.appendChild(el("p", "hint", "Dropped citations: " + a.dropped_citations.join(", ")));
    }

    const trace = $("trace");
    trace.replaceChildren();
    a.trace.forEach((t) => {
      const li = el("li");
      li.appendChild(el("code", null, t.step));
      li.appendChild(document.createTextNode(" " + t.detail));
      trace.appendChild(li);
    });
  }

  // ------------------------------------------------------------- documents
  async function loadDocuments() {
    const body = $("docs");
    try {
      const data = await api("/api/documents?as=" + encodeURIComponent(principal()));
      body.replaceChildren();
      $("docs-summary").textContent = data.principal + " (" + data.groups.join(", ") + ") can see "
        + data.documents.length + " of " + data.total_documents + " documents. "
        + "Everything else is filtered out before retrieval.";
      data.documents.forEach((d) => {
        const tr = el("tr");
        const name = el("td");
        name.appendChild(el("div", "title", d.title));
        name.appendChild(el("div", "small", d.id));
        tr.appendChild(name);
        const mod = el("td");
        mod.appendChild(modality(d.modality));
        tr.appendChild(mod);
        tr.appendChild(el("td", null, d.acl.join(", ")));
        tr.appendChild(el("td", null, d.chunks));
        tr.appendChild(el("td", "small", d.tags.join(", ")));
        body.appendChild(tr);
      });
    } catch (err) { $("docs-summary").textContent = err.message; }
  }

  // ----------------------------------------------------------------- evals
  function pct(x) { return Math.round(x * 100) + "%"; }

  async function runEvals() {
    $("run-evals").disabled = true;
    $("eval-status").textContent = "Running eval suite...";
    try {
      const data = await api("/api/evals");
      const r = data.report;
      $("eval-status").textContent = (r.passed ? "EVAL PASS" : "EVAL FAIL")
        + " · " + data.corpus + " · provider " + data.provider;
      const metrics = $("eval-metrics");
      metrics.replaceChildren();
      [
        ["Retrieval hit-rate", pct(r.retrieval_hit_rate)],
        ["Citation accuracy", pct(r.citation_accuracy)],
        ["Answer accuracy", pct(r.answer_accuracy)],
        ["Abstain accuracy", pct(r.abstain_accuracy)],
        ["ACL leaks", r.acl_leaks],
      ].forEach(([label, value]) => {
        const box = el("div", "metric");
        box.appendChild(el("strong", null, value));
        box.appendChild(el("span", "small", label));
        metrics.appendChild(box);
      });
      const body = $("eval-cases");
      body.replaceChildren();
      r.cases.forEach((c) => {
        const tr = el("tr");
        tr.appendChild(el("td", null, c.id));
        tr.appendChild(el("td", c.passed ? "yes" : "no", c.passed ? "PASS" : "FAIL"));
        tr.appendChild(el("td", null, c.retrieval_hit ? "hit" : "miss"));
        tr.appendChild(el("td", null, pct(c.citation_accuracy)));
        tr.appendChild(el("td", null, c.abstain_ok ? "ok" : "wrong"));
        tr.appendChild(el("td", null, c.acl_leaks));
        tr.appendChild(el("td", "small", c.answer));
        body.appendChild(tr);
      });
    } catch (err) {
      $("eval-status").textContent = err.message;
    } finally {
      $("run-evals").disabled = false;
    }
  }

  // ---------------------------------------------------------------- wiring
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.addEventListener("click", () => showTab(b.dataset.tab));
  });
  $("principal").addEventListener("change", onPrincipal);
  $("ask").addEventListener("click", ask);
  $("question").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) ask();
  });
  $("run-evals").addEventListener("click", runEvals);
  $("apikey").addEventListener("change", () => {
    sessionStorage.setItem("omniknow-key", $("apikey").value.trim());
    refreshGroups();
  });
  init();
})();
