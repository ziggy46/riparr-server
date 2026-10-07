/* Riparr web UI. A client of the same public API everything else uses. */

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const api = {
  async call(method, path, body) {
    const r = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    if (r.status === 401) { showGate(); throw new Error("Not signed in"); }
    const data = r.headers.get("content-type")?.includes("json") ? await r.json() : null;
    if (!r.ok) throw new Error(data?.detail || `Request failed (${r.status})`);
    return data;
  },
  get:  (p)    => api.call("GET", p),
  post: (p, b) => api.call("POST", p, b),
  put:  (p, b) => api.call("PUT", p, b),
  del:  (p)    => api.call("DELETE", p),
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* The host is a polite live region (index.html), so confirmations are read out. An
   error is an alert and stays until it is dismissed: three seconds is not long enough
   to read one, let alone act on it. */
function toast(msg, kind = "", opts = {}) {
  const host = $("#toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  const text = document.createElement("span");
  text.textContent = msg;
  el.append(text);
  const close = () => { el.style.opacity = "0"; setTimeout(() => el.remove(), 250); };
  // The countdown stops while a pointer or keyboard focus is on the toast: an Undo
  // that runs out while you're reaching for it isn't an undo.
  let left = opts.ms || 3200, started = 0, timer = null;
  const expire = () => { close(); if (opts.onTimeout) opts.onTimeout(); };
  const run = () => { started = Date.now(); timer = setTimeout(expire, left); };
  const hold = () => { if (timer) { clearTimeout(timer); timer = null; left -= Date.now() - started; } };
  const resume = () => { if (!timer && !el.matches(":hover, :focus-within")) run(); };
  if (opts.action) {
    const a = document.createElement("button");
    a.className = "toast-act";
    a.type = "button";
    a.textContent = opts.action.label;
    a.onclick = () => { clearTimeout(timer); timer = null; opts.action.run(); close(); };
    el.append(a);
  }
  if (kind === "bad") {
    el.setAttribute("role", "alert");
    const x = document.createElement("button");
    x.className = "toast-x";
    x.type = "button";
    x.setAttribute("aria-label", "Dismiss");
    x.textContent = "\u00d7";
    x.onclick = close;
    el.append(x);
    // Three errors on screen is plenty; the oldest goes first.
    const errs = $$(".toast.bad", host);
    if (errs.length >= 3) errs[0].remove();
  } else {
    el.addEventListener("mouseenter", hold);
    el.addEventListener("focusin", hold);
    el.addEventListener("mouseleave", resume);
    el.addEventListener("focusout", () => setTimeout(resume, 0));
    run();
  }
  host.append(el);
}

const state = { status: null, settings: null };

/* ── formatting: the user should never see a gigabyte ───── */
/* ── the current beta key ───────────────────────────────── */
/* Fetched from the forum GuinpinSoft publishes it on, so the user can paste it in one
   click and can see when it lapses instead of finding out mid-rip. Every failure ends
   at "here is the link", which is exactly where they were before this existed. */
async function offerBetaKey(intoSel, inputSel, opts = {}) {
  const into = $(intoSel);
  if (!into) return;
  into.innerHTML = `<span class="muted">Looking up the current beta key…</span>`;
  let r;
  try { r = await api.get("/api/makemkv/beta-key" + (opts.refresh ? "?refresh=true" : "")); }
  catch (e) { r = { error: e.message }; }

  if (!r.key) {
    into.innerHTML = `<span class="muted">${esc(r.error || "Couldn't fetch the beta key.")}
      </span> <a href="${esc(r.source || "https://forum.makemkv.com/forum/viewtopic.php?t=1053")}"
      target="_blank" rel="noopener">Open the forum post</a>`;
    return;
  }
  into.innerHTML = `
    <div class="keyoffer">
      <div class="grow">
        <div class="keyval mono">${esc(r.key)}</div>
        <div class="muted">Current beta key${
          r.expires ? ` · valid until <b>${esc(r.expires)}</b>` : ""}
          · <a href="${esc(r.source)}" target="_blank" rel="noopener">source</a></div>
      </div>
      <button class="btn primary" id="mk-usekey">Use this key</button>
    </div>`;
  $("#mk-usekey").onclick = () => {
    const el = $(inputSel);
    if (!el) return;
    el.value = r.key;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    toast("Beta key filled in" + (r.expires ? ` — valid until ${r.expires}` : ""), "ok");
  };
}

function capacityPhrase(st) {
  // The server decides the wording, because the meaning depends on D11's rip mode and
  // on how many of each kind of disc actually fit. Re-deriving it here is how the
  // interface ended up saying "1 more disc" without ever saying which kind — a number
  // that silently meant Blu-ray and was wrong eightfold for a DVD.
  if (!st) return "";
  if (st.phrase) {
    const m = st.phrase.match(/^Room for (\d+) (.*)$/);
    return m ? `Room for <b>${m[1]}</b> ${esc(m[2])}` : esc(st.phrase);
  }
  if (st.mode === "stream") return `<b>Streaming</b> — discs are never refused for space`;
  if (st.mode === "full") return `<b>Not enough room</b> for another disc`;
  return `<b>Not enough room</b> to rip safely`;
}
/* ── formatting for the System tables ─────────────────────
   Prowlarr's wording, because these tables are read the same way: a relative time for
   anything within a few days, an absolute one past that. */
function since(ts) {
  if (!ts) return "—";
  const d = ts - Date.now() / 1000;
  const fut = d > 0, s = Math.abs(d);
  if (s < 45) return fut ? "in a moment" : "just now";
  const n = (v, u) => `${Math.round(v)} ${u}${Math.round(v) === 1 ? "" : "s"}`;
  const t = s < 3600 ? n(s / 60, "minute")
          : s < 86400 ? n(s / 3600, "hour")
          : n(s / 86400, "day");
  return fut ? `in ${t}` : `${t} ago`;
}

function hms(sec) {
  if (sec == null) return "—";
  const s = Math.max(0, Math.round(sec));
  const p = (n) => String(n).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
}

function interval(sec) {
  if (!sec) return "—";
  if (sec % 86400 === 0) return `${sec / 86400} day${sec === 86400 ? "" : "s"}`;
  if (sec % 3600 === 0) return `${sec / 3600} hour${sec === 3600 ? "" : "s"}`;
  return `${Math.round(sec / 60)} minutes`;
}

/* Today gets a clock time, yesterday gets a word, anything older gets a date -- the
   same three-way split the *arrs use, and the reason their tables stay scannable. */
function stamp(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000), now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = (day(now) - day(d)) / 86400000;
  if (diff === 0) return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
                          .replace(" ", "").toLowerCase();
  if (diff === 1) return "Yesterday";
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function filesize(b) {
  if (b == null) return "—";
  if (b < 1024) return `${b} B`;
  const u = ["KiB", "MiB", "GiB", "TiB"];
  let v = b / 1024, i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${u[i]}`;
}

function uptime(sec) {
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}
function ago(ts) {
  if (!ts) return "never";
  const s = Date.now() / 1000 - ts;
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} hours ago`;
  return `${Math.round(s / 86400)} days ago`;
}

/* ════════════════════ sign in ════════════════════ */
function showGate(sub) {
  $("#shell").classList.add("hidden");
  $("#wizard").classList.add("hidden");
  $("#gate").classList.remove("hidden");
  $("#gate-waiting")?.classList.add("hidden");
  $("#login-form")?.classList.remove("hidden");
  if (sub) $("#gate-sub").textContent = sub;
}

$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  $("#gate-err").textContent = "";
  try {
    await api.post("/api/auth/login", {
      username: $("#gate-user").value, password: $("#gate-pass").value,
    });
    await boot();
  } catch (err) { $("#gate-err").textContent = err.message; }
};

/* ════════════════════ finding a share ════════════════════
   One flow, used by the setup wizard and by Settings → Library → Add a share: scan the
   network (or type a server), pick it, list its shares -- with credentials if it wants
   them -- pick one, and prove it with a test write before saving. Everything is looked
   up inside `root`, so two copies can't trip over each other's elements.

   opts.onSaved(share)  called once a share has been tested and saved
   opts.askName         offer the optional "Name" field (Settings, where there may be
                        several shares to tell apart)
   opts.onCancel        show a Cancel button that calls this */
function shareFinder(root, opts = {}) {
  const q = (sel) => root.querySelector(sel);
  const qa = (sel) => [...root.querySelectorAll(sel)];
  const data = { host: "", user: "", pass: "", share: "", path: "", name: "" };

  root.innerHTML = `
    <div class="section"><h2>Network shares<span class="grow"></span>
      <button class="btn sf-scan">Scan again</button></h2>
      <div class="body sf-hosts"><div class="result busy"><span class="spin"></span>Looking for shares…</div></div>
      <div class="manual-row">
        <input class="sf-subnet" placeholder="network to scan — e.g. 192.168.1.0/24">
        <button class="btn sf-subnet-go">Scan this network</button>
      </div>
      <p class="help" style="margin-bottom:12px">Riparr scans its own network unless you
        say otherwise. In Docker that is usually Docker's internal network rather than
        your LAN, so put your LAN here. It's remembered once it finds something.</p>
      <div class="manual-row">
        <input class="sf-manual" placeholder="server name or IP — e.g. 192.168.1.20">
        <button class="btn sf-manual-go">Use this server</button>
      </div>
      <p class="help">Discovery only finds servers that advertise themselves. Type one
        in if yours doesn't, or if it's on another subnet.</p>
      ${opts.onCancel ? `<div class="btn-row"><button class="btn sf-cancel">Cancel</button></div>` : ""}
    </div>
    <div class="sf-detail"></div>`;

  const enter = (input, button) => input.onkeydown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); button.click(); }
  };
  q(".sf-scan").onclick = () => scan();
  q(".sf-subnet-go").onclick = () => scan(q(".sf-subnet").value.trim());
  enter(q(".sf-subnet"), q(".sf-subnet-go"));
  q(".sf-manual-go").onclick = () => pickHost(q(".sf-manual").value.trim());
  enter(q(".sf-manual"), q(".sf-manual-go"));
  if (opts.onCancel) q(".sf-cancel").onclick = opts.onCancel;

  async function scan(subnets = "") {
    const box = q(".sf-hosts");
    box.innerHTML = `<div class="result busy"><span class="spin"></span>Looking for shares${
      subnets ? ` on ${esc(subnets)}` : ""}…</div>`;
    let r;
    try { r = await api.post("/api/shares/discover", { subnets }); }
    catch (e) {
      box.innerHTML = `<div class="result bad">${esc(e.message)}</div>`;
      return;
    }
    const hosts = r.hosts || [];
    const field = q(".sf-subnet");
    if (field && !field.value) field.value = r.subnets || "";
    if (!hosts.length) {
      box.innerHTML = `<div class="result">Nothing found on ${esc(r.subnets || "this network")}.
        If that isn't your LAN, put your LAN below and scan again — or type the server
        name. Finding nothing does not mean there is nothing there.</div>`;
      return;
    }
    box.innerHTML = hosts.map(h => `
      <div class="rowitem" data-host="${esc(h.host)}">
        <div class="grow">
          <div class="t">${esc(h.host)}</div>
          <div class="s">${esc(h.address)} · found by ${esc(h.via === "mdns" ? "Bonjour" : "network scan")}</div>
        </div>
        <span class="badge">SMB</span>
      </div>`).join("");
    qa(".sf-hosts .rowitem").forEach(n => n.onclick = () => {
      qa(".sf-hosts .rowitem").forEach(x => x.classList.remove("on"));
      n.classList.add("on");
      pickHost(n.dataset.host);
    });
  }

  async function pickHost(host, creds) {
    if (!host) return;
    if (host !== data.host) { data.share = ""; data.path = ""; }
    data.host = host;
    // Carry credentials across a re-browse. The share list itself is behind
    // authentication on most servers, so asking anonymously and only then offering a
    // username means the list is empty exactly when it matters.
    if (creds) { data.user = creds.user; data.pass = creds.pass; }
    const user = data.user, pass = data.pass;

    const d = q(".sf-detail");
    // Same shell as the loaded state below -- header, .card, .body -- so the panel
    // doesn't change component type mid-flight, exactly where the eye is waiting.
    d.innerHTML = `<div class="card">
      <header><h3>${esc(host)}</h3></header>
      <div class="body">
        <div class="result busy"><span class="spin"></span>Asking ${esc(host)} what it offers…</div>
      </div></div>`;
    d.scrollIntoView({ block: "nearest", behavior: "smooth" });
    let res;
    try {
      res = await api.post("/api/shares/browse", { host, username: user, password: pass });
    } catch (e) { res = { ok: false, error: e.message, shares: [] }; }

    const needsAuth = !res.ok && /LOGON_FAILURE|ACCESS_DENIED|NT_STATUS_ACCESS/i.test(res.error || "");
    const as = user ? `as ${esc(user)}` : "as a guest";
    d.innerHTML = `<div class="card">
      <header><h3>${esc(host)}</h3></header>
      <div class="body">
        ${res.ok ? "" : `<div class="result ${needsAuth ? "" : "bad"}"><b>${
            needsAuth ? "This server wants a username and password"
                      : "Couldn't list shares"}</b>
           <div class="why">${esc(res.error)}</div></div>`}
        <label class="f"><span>Username</span>
          <input class="sf-user" value="${esc(user)}" autocomplete="off"
                 placeholder="user, or DOMAIN\\user — empty for guest"></label>
        <label class="f"><span>Password</span>
          <input class="sf-pass" type="password" value="${esc(pass)}"
                 autocomplete="new-password"></label>
        <div class="btn-row">
          <button class="btn sf-recheck">List shares with these credentials</button>
        </div>
        ${res.ok ? `<div class="result sf-listed ${res.shares.length ? "ok" : ""}">${
            res.shares.length
              ? `<b>Found ${res.shares.length} share${res.shares.length === 1 ? "" : "s"}
                   on ${esc(host)} ${as}</b>
                 Pick the one rips should go to:
                 <div class="share-picks">${res.shares.map(x =>
                   `<button class="btn tiny" data-pick-share="${esc(x)}">${esc(x)}</button>`
                 ).join("")}</div>`
              : `<b>Connected to ${esc(host)} ${as}</b>
                 It didn't list any shares, so type the share name below.`}</div>` : ""}
        <label class="f"><span>Share</span>
          <input class="sf-share" placeholder="Media">
          <span class="help">${res.shares.length
            ? "Pick one above, or type a share that wasn't listed."
            : "Type the share name — it doesn't have to be one we could list."}
            Just the top-level name, one word. Anything deeper goes in the next box.</span>
        </label>
        <label class="f"><span>Folder inside the share</span>
          <input class="sf-path" placeholder="e.g. Rips or Movies/4K">
          <span class="help">Optional, and it may be several levels deep. Riparr creates
            it if it isn't there. Leave empty to use the top level.</span></label>
        ${opts.askName ? `<label class="f"><span>Name</span>
          <input class="sf-name" placeholder="optional — shown in the list">
          <span class="help">Only for your own benefit when you have more than
            one.</span></label>` : ""}
        <div class="dest-path sf-preview"></div>
        <div class="btn-row">
          <button class="btn primary sf-test">Test and save</button>
        </div>
        <div class="sf-testres"></div>
      </div></div>`;

    // Re-ask the server, this time as somebody. Keeps whatever share and folder were
    // already typed, so entering a password does not throw the rest away.
    const keep = () => {
      data.share = q(".sf-share").value.trim();
      data.path = q(".sf-path").value.trim();
      if (q(".sf-name")) data.name = q(".sf-name").value.trim();
    };
    q(".sf-recheck").onclick = () => {
      q(".sf-recheck").disabled = true;
      q(".sf-recheck").textContent = "Listing…";
      keep();
      pickHost(host, { user: q(".sf-user").value.trim(), pass: q(".sf-pass").value });
    };
    q(".sf-share").value = data.share;
    q(".sf-path").value = data.path;
    if (q(".sf-name")) q(".sf-name").value = data.name;

    // What the boxes add up to. The commonest mistake is a whole path pasted into
    // Share, and this is where that becomes obvious.
    const preview = () => {
      const parts = (q(".sf-share").value + "/" + q(".sf-path").value)
        .replace(/\\/g, "/").split("/").map(x => x.trim()).filter(Boolean);
      q(".sf-preview").textContent = `//${host}/${parts.join("/") || "share"}`;
    };
    // The listed shares as buttons, because a <datalist> only shows itself to somebody
    // who already knows to click into the field.
    const markPicked = () => qa("[data-pick-share]").forEach(b =>
      b.classList.toggle("primary", b.dataset.pickShare === q(".sf-share").value.trim()));
    qa("[data-pick-share]").forEach(b => b.onclick = () => {
      q(".sf-share").value = b.dataset.pickShare;
      markPicked(); preview();
      q(".sf-path").focus();
    });
    q(".sf-share").addEventListener("input", () => { markPicked(); preview(); });
    q(".sf-path").addEventListener("input", preview);
    markPicked(); preview();
    qa(".sf-detail input").forEach(i => {
      i.onkeydown = (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        (i.classList.contains("sf-user") || i.classList.contains("sf-pass")
          ? q(".sf-recheck") : q(".sf-test")).click();
      };
    });

    q(".sf-test").onclick = async () => {
      keep();
      const body = { host, share: data.share, path: data.path,
                     username: q(".sf-user").value.trim(), password: q(".sf-pass").value };
      const out = q(".sf-testres");
      if (!body.share) {
        out.innerHTML = `<div class="result bad"><b>Which share?</b>
           Enter the share name — for \\\\server\\Media\\Rips that is
           <code>Media</code>, with <code>Rips</code> as the folder.</div>`;
        return;
      }
      const btn = q(".sf-test");
      btn.disabled = true;
      out.innerHTML = `<div class="result busy"><span class="spin"></span>Writing a test
        file and reading it back…</div>`;
      try {
        const r = await api.post("/api/shares/test", body);
        if (!r.ok) {
          out.innerHTML = `<div class="result bad"><b>That didn't work</b>
            Failed at the ${esc(r.stage)} step.<div class="why">${esc(r.error)}</div></div>`;
          btn.disabled = false;
          return;
        }
        const saved = await api.post("/api/shares",
          { ...body, name: data.name || `${host}/${body.share}` });
        out.innerHTML = `<div class="result ok"><b>The share works, and it's saved</b>
          Wrote a file to ${esc(r.target)}, read it back and deleted it.</div>`;
        toast("Share saved", "ok");
        if (opts.onSaved) opts.onSaved(saved);
      } catch (e) {
        out.innerHTML = `<div class="result bad"><b>That didn't work</b>
          <div class="why">${esc(e.message)}</div></div>`;
        btn.disabled = false;
      }
    };
  }

  scan();
}

/* ════════════════════ first run ════════════════════ */
const wizard = {
  step: 0,
  data: { username: "", password: "", host: "", share: "", path: "", user: "", pass: "" },
  skipped: new Set(),
  steps: ["account", "makemkv", "share", "layout", "done"],

  render() {
    const name = this.steps[this.step];
    $("#gate").classList.add("hidden");
    $("#shell").classList.add("hidden");
    const w = $("#wizard");
    w.classList.remove("hidden");
    w.innerHTML = `
      <div class="wz-head">
        <div class="logo"><img class="logo-mark" src="/static/img/riparr-mark.png" alt=""> <span class="logo-word">Riparr</span></div>
        <div class="wz-rail">${this.steps.map((_, i) =>
          `<div class="${i <= this.step ? "done" : ""}"></div>`).join("")}</div>
      </div>
      <div class="wz-body" id="wz-body"></div>`;
    this[name]();

    // Enter finishes the step. These inputs are not in a <form> -- each step is plain
    // markup with an onclick on one primary button -- so nothing submits on its own,
    // and typing the last field then pressing Enter appeared to do nothing.
    // Bound on the body rather than per-input so every step gets it, including the
    // async ones that fill this element after we return.
    $("#wz-body").onkeydown = (e) => {
      if (e.key !== "Enter" || e.isComposing) return;
      // A field with its own Enter handler (the share step has two) has already acted
      // and called preventDefault; do not also fire the step's primary button.
      if (e.defaultPrevented) return;
      const t = e.target;
      if (!t || t.tagName !== "INPUT" || t.type === "checkbox" || t.type === "radio") return;
      const btn = $("#wz-body").querySelector(".wz-actions .btn.primary:not([disabled])");
      if (btn) { e.preventDefault(); btn.click(); }
    };
  },

  next() { this.step++; this.render(); },
  // Back only goes as far as step 2: the account already exists once step 1 is done.
  back() { if (this.step > 1) { this.step--; this.render(); } },
  backBtn() { return this.step > 1 ? `<button class="btn" id="w-back" type="button">Back</button>` : ""; },
  wireBack() { const b = $("#w-back"); if (b) b.onclick = () => this.back(); },

  account() {
    $("#wz-body").innerHTML = `
      <div class="wz-step">Step 1 of 5</div>
      <h1>Create your login</h1>
      <p class="muted">This protects the web interface. It is separate from any account
        on the server or container.</p>
      <div class="section"><div>
        <label class="f"><span>Username</span><input id="w-user" autocomplete="username" autocapitalize="none"></label>
        <label class="f"><span>Password</span><input id="w-pass" type="password">
          <span class="help">At least 8 characters.</span></label>
        <label class="f"><span>Confirm password</span><input id="w-pass2" type="password"></label>
        <div class="result bad hidden" id="w-err"></div>
      </div></div>
      <div class="wz-actions">
        <div class="grow"></div>
        <button class="btn primary" id="w-go">Create account</button>
      </div>`;
    $("#w-go").onclick = async () => {
      const u = $("#w-user").value.trim(), p = $("#w-pass").value, p2 = $("#w-pass2").value;
      const err = $("#w-err");
      const fail = (m) => { err.textContent = m; err.classList.remove("hidden"); };
      if (!u) return fail("Pick a username.");
      if (p.length < 8) return fail("Use at least 8 characters.");
      if (p !== p2) return fail("The two passwords don't match.");
      try {
        await api.post("/api/setup/user", { username: u, password: p });
        this.next();
      } catch (e) { fail(e.message); }
    };
  },

  async makemkv() {
    const i = await api.get("/api/makemkv");
    const st = i.status;
    // The drive belongs on this step. Setup used to run to completion without ever
    // mentioning it, so someone whose drive was in the socket that cannot host got
    // five green steps and an empty tray at the end -- with the explanation sitting on
    // a dashboard they had not reached yet.
    let opt = null;
    try { opt = (await api.get("/api/status")).optical; } catch (e) {}
    const ready = st.installed && st.eula_accepted;
    $("#wz-body").innerHTML = `
      <div class="wz-step">Step 2 of 5</div>
      <h1>Disc reading</h1>
      <p class="muted">Riparr doesn't read discs itself — <b>MakeMKV</b> does, and it's
        made by GuinpinSoft, not by us. It's compiled when ${i.install === "bare"
          ? "Riparr starts" : "the container first starts"}, once you've accepted its
        licence with <code>MAKEMKV_ACCEPT_EULA</code>${i.install === "bare"
          ? " in <code>/etc/riparr/riparr.env</code>" : ""}.</p>

      <div class="section"><h2>MakeMKV
        <span class="grow"></span>
        <span class="badge ${ready ? "ok" : "warn"}">${ready ? "Installed" : "Not installed"}</span></h2>
        <div>
          ${ready ? `<div class="kv">
              <div class="k">Version</div><div class="v">${esc(st.version || "—")}</div>
              <div class="k">Key</div><div class="v">${st.key_expires
                ? `${esc(st.key_type || "beta")} — expires ${esc(st.key_expires)} (${st.days_left} days)`
                : "none yet"}</div>
            </div>`
          : `<div class="result bad"><b>MakeMKV isn't installed.</b>
               <div class="why">${esc((i.install_hint) || "Rebuild the image or re-run the installer.")}</div></div>`}
        </div>
      </div>

      ${opt ? `<div class="section"><h2>Your drive
        <span class="grow"></span>
        <span class="badge ${opt.drives && opt.drives.length ? "ok" : "warn"}">${
          opt.drives && opt.drives.length ? "Found" : "Not found"}</span></h2>
        <div>${opt.drives && opt.drives.length
          ? `<div class="kv">
               <div class="k">Drive</div><div class="v">${esc(
                 [opt.drives[0].vendor, opt.drives[0].model].filter(Boolean).join(" ")
                 || opt.drives[0].device)}</div>
               <div class="k">Reads</div><div class="v">${esc(
                 opt.drives[0].reads || "—")}</div>
             </div>`
          : `<p class="muted">Riparr can't see an optical drive yet. You can finish
               setting up and come back to this — but nothing can be ripped until a
               drive appears.</p>
             ${opt.hint ? `<p class="why">${mdBold(opt.hint)}</p>` : ""}
`}
        </div>
      </div>` : ""}

      <div class="section"><h2>Key</h2><div>
        <div class="f"><span></span><div class="grow" id="wz-key-offer"></div></div>
        <label class="f"><span>MakeMKV key</span>
          <input id="w-key" placeholder="Paste a beta or purchased key">
          <span class="help">The free beta key expires at the end of a month rather
            than a fixed number of days after you enter one, so Riparr says which month
            yours is good for and fetches the next one for you. A
            <a href="${esc(i.homepage)}" target="_blank" rel="noopener">purchased key</a>
            removes the only recurring chore in the product. You can add this later.</span>
        </label>
      </div></div>

      <div class="wz-actions">
        <div class="grow"></div>
        <button class="btn" id="w-skip">Do this later</button>
        <button class="btn primary" id="w-go">Continue</button>
      </div>`;

    offerBetaKey("#wz-key-offer", "#w-key");

    const save = async () => {
      const k = $("#w-key").value.trim();
      if (k) {
        try { await api.post("/api/makemkv/key", { key: k }); }
        catch (e) { toast(`The key wasn't saved: ${e.message}`, "bad"); return; }
      }
      this.next();
    };
    $("#w-go").onclick = async () => {
      if ($("#w-key").value.trim()) this.skipped.delete("key"); else this.skipped.add("key");
      await save();
    };
    $("#w-skip").onclick = () => { this.skipped.add("key"); this.next(); };
  },

  share() {
    $("#wz-body").innerHTML = `
      <div class="wz-step">Step 3 of 5</div>
      <h1>Where should finished rips go?</h1>
      <p class="muted">Riparr looks for network shares on your LAN, then writes a real
        test file and reads it back. A wrong path found now is a wrong path you never
        discover at 3am on your first rip.</p>
      <div id="w-finder"></div>
      <div class="wz-actions">
        ${this.backBtn()}
        <div class="grow"></div>
        <button class="btn" id="w-skip">Set this up later</button>
        <button class="btn primary" id="w-go" disabled>Continue</button>
      </div>`;
    $("#w-skip").onclick = () => { this.skipped.add("share"); this.next(); };
    $("#w-go").onclick = () => { this.skipped.delete("share"); this.next(); };
    this.wireBack();
    shareFinder($("#w-finder"), { onSaved: () => { $("#w-go").disabled = false; } });
  },

  async layout() {
    const s = await api.get("/api/settings");
    $("#wz-body").innerHTML = `
      <div class="wz-step">Step 4 of 5</div>
      <h1>How should files be named?</h1>
      <p class="muted">These defaults follow Plex and Jellyfin conventions. You can
        change them later in Settings.</p>
      <div class="section"><div>
        <div class="grid2">
          <label class="f"><span>Movie folder</span>
            <input id="s-movie-folder" value="${esc(s.movie_folder)}"></label>
          <label class="f"><span>TV folder</span>
            <input id="s-tv-folder" value="${esc(s.tv_folder)}"></label>
        </div>
        <label class="f"><span>Movie file name</span>
          <input id="s-movie" value="${esc(s.movie_template)}"></label>
        <label class="f"><span>Episode file name</span>
          <input id="s-tv" value="${esc(s.tv_template)}"></label>
        <label class="f"><span>When Riparr can't identify a disc</span>
          <select id="s-unknown">
            <option value="label" ${s.on_unknown_disc === "label" ? "selected" : ""}>Use the disc label (default)</option>
            <option value="ask" ${s.on_unknown_disc === "ask" ? "selected" : ""}>Ask me</option>
            <option value="skip" ${s.on_unknown_disc === "skip" ? "selected" : ""}>Skip the disc</option>
          </select>
          <span class="help">Only about the name. The disc label is the better answer
            if rips land in a folder you tidy up later; pick "Ask me" if they go
            straight into a library you browse.</span></label>
      </div></div>
      <div class="wz-actions">
        ${this.backBtn()}
        <div class="grow"></div>
        <button class="btn primary" id="w-go">Continue</button>
      </div>`;
    this.wireBack();
    $("#w-go").onclick = async () => {
      try {
        await api.put("/api/settings", {
          movie_folder: $("#s-movie-folder").value, tv_folder: $("#s-tv-folder").value,
          movie_template: $("#s-movie").value, tv_template: $("#s-tv").value,
          on_unknown_disc: $("#s-unknown").value,
        });
      } catch (e) { toast(`Couldn't save that: ${e.message}`, "bad"); return; }
      this.next();
    };
  },

  /* Says what will actually happen next, rather than what the product does in general.
     The old copy promised "insert a disc, close the tray, walk away" and the very next
     screen showed Auto Rip switched off and greyed out — because MakeMKV was still
     compiling and Auto Rip is gated on it being installed. Being sold a feature by the
     page immediately before the page that says you cannot have it yet reads as a broken
     box, not as a build in progress. */
  async done() {
    // Painted twice on purpose: once immediately so the panel is never blank, then again
    // when the box has said what state it is actually in. render() does not await the
    // step, so anything that needs a fetch has to draw something first.
    const paint = (lede, first) => {
      $("#wz-body").innerHTML = `
      <div class="wz-step">All set</div>
      <h1>Riparr is ready</h1>
      <p class="muted">${lede}</p>
      <div class="section"><div>
        <div class="kv">
          <div class="k">${first[0]}</div><div class="v">${first[1]}</div>
          <div class="k">Everything else</div><div class="v">Lives in Settings, and most people never open it</div>
        </div>
      </div></div>
      <div class="wz-actions">
        ${this.backBtn()}
        <div class="grow"></div>
        <button class="btn primary" id="w-go">Open Riparr</button>
      </div>`;
      this.wireBack();
      $("#w-go").onclick = async () => {
        await api.post("/api/setup/complete");
        location.hash = "#/queue";
        await boot();
      };
    };

    const skipped = [...this.skipped].map(k => ({ key: "the MakeMKV key", share: "a share" }[k]));
    paint(skipped.length
      ? `You skipped ${andList(skipped)} — Settings is where to add ${skipped.length > 1 ? "them" : "it"}. One moment — checking what Riparr can already do.`
      : `Everything is configured. One moment — checking what Riparr can already do.`,
          ["Insert a disc", "Riparr identifies it and gets to work"]);

    let st = null;
    try { st = await api.get("/api/status"); } catch (e) { /* offline: keep the neutral copy */ }
    if (!st) return;
    const ar = st.autorip || {};
    const building = !!(st.makemkv && !st.makemkv.installed);

    const lede =
      ar.enabled ? `From here the loop is: insert a disc, close the tray, walk away.
                    The disc ejects when it's done.`
    : ar.ready   ? `Turn on <b>Auto Rip</b> on the next screen and the loop becomes:
                    insert a disc, close the tray, walk away.`
    : building   ? `MakeMKV isn't installed, so no disc can be read yet. Rebuild the
                    image (or re-run the installer) with the MakeMKV licence accepted.`
    :              `<b>Auto Rip</b> needs one or two more things first. <b>System → Status</b>
                    lists exactly what, and each one links to where to fix it.`;

    paint((skipped.length ? `You skipped ${andList(skipped)}; you can add ${
             skipped.length > 1 ? "them" : "it"} in Settings. ` : "") + lede, ar.enabled
      ? ["Insert a disc", "Riparr identifies it and starts on its own"]
      : building
      ? ["First", "Install MakeMKV — Settings → MakeMKV says how"]
      : ["Insert a disc", "Then press Rip. Auto Rip can start it for you once it is on"]);
  },
};

/* A newer MakeMKV than the one built on this box. Installing it is agreeing to its
   licence again -- the same terms, but the agreement is per version and between the
   user and GuinpinSoft, so the button says so rather than carrying the old consent
   over silently. */
function mkUpgradeBlock(mk) {
  if (!mk.upgrade) return "";
  return `
    <div class="alert warn" style="margin-bottom:14px">
      <b>MakeMKV ${esc(mk.upgrade)} is available</b> — this install has
      ${esc(mk.status.version || "an older version")}. ${esc(mk.install_hint || "")}
      <div class="btn-row" style="margin-top:10px">
        <a class="btn" href="${esc(mk.eula_url)}" target="_blank" rel="noopener">Read the licence</a>
      </div>
    </div>`;
}

/* Said once, on the first visit after the box renewed the beta key on its own. The
   renewal keeps a box working while makemkv.com's shop is down, which it often is; it
   is not a substitute for buying MakeMKV, and the dialog says so. Dismissing it is
   remembered on the box, so it comes back only with the next renewal. */
async function showRenewalNotice() {
  let r;
  try { r = (await api.get("/api/makemkv/renewal")).renewal; } catch (e) { return; }
  if (!r || document.getElementById("renewal-dialog")) return;
  const until = r.expires
    ? new Date(r.expires + "T12:00:00").toLocaleDateString(undefined,
        { day: "numeric", month: "long", year: "numeric" })
    : "";
  const d = document.createElement("dialog");
  d.id = "renewal-dialog";
  d.className = "notice-dialog";
  d.setAttribute("aria-labelledby", "renewal-title");
  d.innerHTML = `
    <h2 id="renewal-title">${icon("circle-check", "ok")} MakeMKV key ${r.first ? "added" : "renewed"}</h2>
    <p>${r.first ? "There was no MakeMKV key, so Riparr put in" : "Your MakeMKV beta key ran out, so Riparr put in the new"}
      free one that GuinpinSoft publishes each month${until ? `. It works until <b>${esc(until)}</b>` : ""}.
      Your discs keep ripping without you having to do anything.</p>
    ${r.shop_open === false ? `
    <p>Riparr can only read your discs because of MakeMKV. GuinpinSoft isn't selling
      licences right now, and their own site asks everyone to use the free beta key
      until they are. When sales reopen, buying one pays the people who make MakeMKV,
      and a bought key never runs out.</p>
    <div class="btn-row">
      <button class="btn primary" id="renewal-dismiss">OK</button>
    </div>` : `
    <p>Riparr can only read your discs because of MakeMKV. If it's worth it to you,
      please buy a licence. It pays the people who make MakeMKV, and a bought key never
      runs out.</p>
    <div class="btn-row">
      <a class="btn primary" href="${esc(r.buy_url)}" target="_blank" rel="noopener"
         id="renewal-buy">Buy MakeMKV</a>
      <button class="btn" id="renewal-dismiss">Dismiss</button>
    </div>`}`;
  document.body.appendChild(d);
  paintIcons(d);
  const close = async () => {
    try { await api.post("/api/makemkv/renewal/dismiss", {}); } catch (e) { /* asked again next visit */ }
    d.close();
    d.remove();
  };
  d.querySelector("#renewal-dismiss").onclick = close;
  const buy = d.querySelector("#renewal-buy");
  if (buy) buy.addEventListener("click", close);
  d.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  d.showModal();
}

/* ── delete, with a moment to take it back ──
   The item disappears at once and the request goes out a few seconds later, unless
   Undo is pressed first. Forgetting a disc or removing a share can't be reversed on
   the server, so the undo has to happen before it gets there. */
function undoable(el, message, request) {
  if (el) el.hidden = true;
  toast(message, "", {
    ms: 6000,
    action: { label: "Undo", run: () => { if (el) el.hidden = false; } },
    // The request goes when the toast runs out, which pauses while it's hovered.
    onTimeout: async () => {
      try { await request(); }
      catch (e) { toast(e.message, "bad"); if (el) el.hidden = false; return; }
      if (el && el.isConnected) route();
    },
  });
}

/* ════════════════════ views ════════════════════ */
const views = {};

/* One page, one thing. The toolbar row of icon-over-label buttons that used to sit
   between Auto Rip and the table is now two actions in the page header: Options and
   Status were links to pages already one click away in the sidebar, and Refresh and
   Eject are the only two verbs this page actually owns.

   The queue and the tray are also one card rather than two sections. "Drive" repeated
   the disc name the empty state had just said, which is the kind of duplication that
   reads as an interface describing its own data model. */
views.queue = async () => {
  // Fetch the drive state rather than reading the snapshot boot() took. The tray is
  // the one thing on this page that changes without the user doing anything -- a disc
  // goes in and nothing on screen knew, and the Refresh button re-rendered the same
  // stale snapshot, so it looked broken rather than slow.
  const [q, st, ar] = await Promise.all([
    api.get("/api/queue"),
    api.get("/api/status"),
    api.get("/api/autorip"),
  ]);
  // A refused duplicate leaves nothing on this page to look at -- no job, no file --
  // so the page it belongs on is Discs, next to the disc in question and the button
  // that overrides the refusal. Checked here because this is the only view that keeps
  // polling, and putting a disc in is the one thing that happens with no user action.
  if (st.duplicate && st.duplicate.fingerprint) {
    goToDuplicate(st.duplicate);
    // Not an empty string. Acknowledging the duplicate is a round trip, and a page
    // that goes blank for even a moment reads as a crash rather than as a redirect.
    return `<div class="card"><div class="empty-state">
      <div class="big">${icon("compact-disc")}</div>
      <h2>You've already ripped ${esc(st.duplicate.title || "this disc")}</h2>
      <p>Taking you to it…</p></div></div>`;
  }
  const jobs = q.jobs;
  state.lastJobs = jobs;
  const sending = q.sending || [];
  state.autoripOn = !!ar.enabled;
  state.typical = q.typical_seconds;
  state.typicalN = q.typical_samples;
  state.typicalStages = q.typical_stages || {};
  state.stageLabels = q.stage_labels || {};
  state.stageLabelSets = q.stage_label_sets || {};
  state.stageOrder = q.stage_order || [];
  state.status = st;
  const drives = state.status.drives || [];
  announceFiled(q.filed);
  announceAsk(jobs.filter(j => j.state === "needs_input"));

  // One card per drive once there's more than one: each tray holds its own disc, rips
  // on its own, and has its own Eject and Disc info. A job from before there could be
  // two has no drive recorded, and belongs to the first.
  const first = (drives[0] || {}).device;
  const onDrive = (dev) => (j) => (j.device || first) === dev;
  const cardFor = (d, slice) => {
    const loaded = d && d.present ? d : null;
    setDiscArt(loaded && loaded.label);      // fire and forget; never blocks the render
    // A rip still uploading whose disc hasn't come out yet stays the hero. Otherwise
    // the card fell back to "you ripped this … Rip it again" for the length of the
    // upload, as if nothing had happened.
    const ownDisc = (j) => loaded && (j.disc_label || "") === (loaded.label || "");
    const hero = slice.jobs.length ? slice.jobs : slice.sending.filter(ownDisc);
    // The rip that just finished stays on the card until the next disc goes in. A
    // different disc in the tray is the next moment, so the tray takes over again.
    const filed = !hero.length && showFiled(slice.filed, loaded) ? slice.filed : null;
    if (filed) setFiledArt(filed);
    return { d, loaded, hero, filed, busy: hero.some(j => j.state !== "needs_input"),
             mk: slice.mk, away: slice.jobs.length ? slice.sending : slice.sending.filter(j => !ownDisc(j)) };
  };
  let cards;
  if (drives.length > 1) {
    const by = q.by_device || {};
    cards = drives.map(d => cardFor(d, {
      jobs: jobs.filter(onDrive(d.device)), sending: sending.filter(onDrive(d.device)),
      filed: (by[d.device] || {}).filed, mk: (by[d.device] || {}).makemkv || [] }));
  } else {
    cards = [cardFor(drives.find(x => x.present) || drives[0],
                     { jobs, sending, filed: q.filed, mk: q.makemkv || [] })];
  }
  const away = cards.flatMap(c => c.away);
  return nowRipping({ q, ar, drives, cards, away });
};


/* ── the queue: "now ripping" ──
   One object, the disc, as large as the page allows: its poster, its title, one bar,
   one finish time, and the things you can do to it on the card itself. What's still
   uploading and what was filed last sit in a short strip under it, and Auto Rip and
   the rip options -- set once, rarely touched -- fold into a footer. */
function nowRipping({ q, ar, drives, cards, away }) {
  const multi = drives.length > 1;
  const html = cards.map((c, i) => discCard(c, { drives: multi ? [c.d] : drives, multi,
                                                 todo: i === 0 })).join("");
  // Not while the same film is being ripped again -- that reads as a duplicate.
  const hero = (cards[0] || {}).hero || [];
  const last = !multi && hero.length && q.filed && q.filed.state === "done"
    && (q.filed.disc_label || "") !== (hero[0].disc_label || "")
    ? `<a class="np-last" href="#/history">${icon("circle-check")}
         <span>Last filed <b>${esc(filedName(q.filed))}</b> · ${esc(ago(q.filed.finished_at))}</span></a>`
    : "";
  // On a phone the header's warnings are hidden, so the Queue says what's in the way --
  // unless a card is already listing it.
  const bad = problems(state.status).filter(p => p.level === "bad");
  const notReady = bad.length && !html.includes('class="np-todo"')
    ? `<a class="np-notready" href="#/system/status">${icon("triangle-exclamation")}
         <span><b>Not ready:</b> ${esc(bad.map(p => p.short || p.what).join(" \u00b7 "))}</span>
         <span class="np-notready-go">Fix</span></a>` : "";
  return `<div class="np-page${multi ? " np-multi" : ""}">
    ${head("Queue", multi ? `${drives.length} drives` : "")}
    ${notReady}
    ${html}
    ${sendingStrip(away)}
    ${last}
    <div class="np-foot">${autoRipPanel(ar)}</div>
  </div>`;
}

/* One drive's card: its disc as large as the page allows -- poster, title, one bar, one
   finish time -- and the things you can do to it on the card itself. With several
   drives each has its own, named at the top. */
function discCard({ d, loaded, hero, busy, filed, mk }, { drives, multi, todo }) {
  const dev = (d || {}).device || "";
  const square = (hero[0] && hero[0].kind === "music") || (filed && filed.kind === "music")
    || (loaded && loaded.disc_family === "cd");
  const poster = (img) => `<div class="np-art${square ? " square" : ""}">${img
    ? `<img src="${esc(img)}" alt="">`
    : `<span class="np-art-none">${icon("compact-disc")}</span>`}</div>`;
  // A CD has no label to look a poster up by; an album Riparr knows brings its cover.
  const art = artFor(loaded && loaded.label) || (loaded && loaded.known && loaded.known.art) || null;
  // Eject leads: right after a rip it is the next thing anybody does. Disc info next,
  // then whatever belongs to this card, with the destructive one last.
  const acts = ({ lead = "", trail = "", ejectDisabled = false, ejectPrimary = false } = {}) => {
    const disc = loaded ? `
      <button class="btn sm${ejectPrimary && !busy ? " primary" : ""}" data-eject="${esc(dev)}" ${busy || ejectDisabled ? "disabled" : ""}
              ${ejectDisabled ? `title="Answer or skip first"` : busy ? `title="The drive is in use — cancel the rip to eject"` : ""}>${icon("eject")} Eject</button>
      <button class="btn sm" data-disc="${esc(dev)}">${icon("compact-disc")} Disc info</button>` : "";
    return lead || disc || trail ? `<div class="np-acts">${lead}${disc}${trail}</div>` : "";
  };
  const shell = (img, inner, cls = "") =>
    `<div class="np${cls ? " " + cls : ""}">${poster(img)}<div class="np-body">${inner}</div></div>`;

  // The drive's own line -- model, device, what it reads -- is the System page's and Disc
  // info's business. On the card it's only worth room when there's no disc to show, or
  // when there's more than one drive and the card has to say which it is.
  let body, strip = !loaded && !multi;
  if (hero.length) {
    body = hero.map(j => j.state === "needs_input"
      ? shell(j.art || art, npAsk(j, acts), "np-ask")
      : shell(j.art || art, npLive(j, acts, mk), "np-live")).join("");
  } else if (filed) {
    body = shell(filed.art || filedArtFor(filed) || art, npFiled(filed, acts),
                 filed.state === "done" ? "np-done" : "np-bad");
  } else if (loaded && loaded.known && !loaded.cannot_read) {
    body = shell(art, npKnown(loaded, acts), "np-done");
  } else if (drives.length && !(loaded && loaded.cannot_read)) {
    body = shell(loaded ? art : null, npIdle(drives, loaded, busy, acts, todo), "np-idle");
  } else {
    // No drive at all, or a disc this drive can't read: the tray explains it best.
    body = tray(drives, state.status.optical, loaded && !busy);
    strip = false;           // the tray carries its own drive line
  }
  const named = multi && d ? `<div class="np-drive">${icon("compact-disc")}
      <span>${esc(driveName(d))}</span> <span class="muted">${esc(dev)}</span></div>` : "";
  return `<div class="card np-card"${multi ? ` data-drive="${esc(dev)}"` : ""}>${named}${body}${
    strip ? trayStrip(drives, state.status.optical) : ""}</div>`;
}

/* ── one bar for the whole job ──
   Each stage counts for what it usually costs on this machine, so the bar moves at the
   pace the rip actually goes and never runs to 100% and starts again for the upload.
   Ticks mark where one step hands over to the next. */
const STAGE_GUESS = { identify: 300, decrypt: 300, save: 1500, upload: 600, verify: 60 };
function jobProgress(j) {
  const med = state.typicalStages || {};
  const order = (state.stageOrder && state.stageOrder.length ? state.stageOrder
                 : ["identify", "decrypt", "save", "upload", "verify"])
    .filter(k => !(k === "verify" && (state.settings || {}).verify_mode === "off"))
    // A CD isn't decrypted: cdparanoia reads and saves in one step.
    .filter(k => !(k === "decrypt" && j.disc_family === "cd"));
  // Steps with no history yet are guessed, scaled to the steps that do have one -- a
  // five-minute guess beside medians of seconds would make one step the whole bar.
  const known = order.filter(k => med[k] && med[k].seconds);
  const scale = known.length
    ? known.reduce((a, k) => a + med[k].seconds, 0) / known.reduce((a, k) => a + (STAGE_GUESS[k] || 300), 0)
    : 1;
  const w = order.map(k => (med[k] && med[k].seconds) || (STAGE_GUESS[k] || 300) * scale);
  const total = w.reduce((a, b) => a + b, 0) || 1;
  const byState = { queued: "identify", identifying: "identify", ripping: "save",
                    transferring: "upload", verifying: "verify" };
  let at = order.indexOf(j.stage_name || byState[j.state]);
  if (at < 0) at = 0;
  // How far through the current stage: its own report where there is one, bytes where not.
  const bytes = j.state === "ripping" ? pct(j.bytes_ripped, j.bytes_total)
              : j.state === "transferring" ? pct(j.bytes_sent, j.bytes_total)
              : j.state === "verifying" ? pct(j.bytes_verified, j.bytes_total) : 0;
  const frac = Math.max(0, Math.min(1, typeof j.stage_pct === "number" ? j.stage_pct
                                         : Number(bytes) / 100));
  const done = w.slice(0, at).reduce((a, b) => a + b, 0) + w[at] * frac;
  let edge = 0;
  const ticks = w.slice(0, -1).map(x => (edge += x) / total * 100);
  return { pct: Math.min(100, (done / total) * 100), step: at + 1, steps: order.length,
           name: stageLabel(j, order[at]), ticks };
}

function npLive(j, acts, mk) {
  const p = jobProgress(j);
  const shown = Math.round(p.pct);
  const working = shown <= 0;
  const eta = overallEta(j);
  const t = stageTiming(j);
  // The stage's own name, the same words History's legend uses, said once.
  const verb = j.state === "queued" ? "Waiting" : p.name;
  const planned = j.planned && j.planned.path
    ? (j.planned.kind === "tv" || j.planned.kind === "music"
        ? `<div class="np-facts">${j.planned.count} ${j.planned.kind === "tv" ? "episode" : "track"}${
            j.planned.count === 1 ? "" : "s"}</div>`
        : `<details class="np-path"><summary>${icon("folder-open")}<span>${
            esc(shortPath(j.planned.path, isFolderJob(j)))}</span></summary><code>${esc(j.planned.path)}</code></details>`)
    : "";
  return `
    <div class="np-kicker live">${icon("compact-disc")} ${esc(verb)}
      <span class="muted">· step ${p.step} of ${p.steps}</span></div>
    <h2 class="np-title" tabindex="-1">${esc((j.title || j.disc_label || "Unknown disc")
      + (j.title && j.year && j.kind !== "tv" ? ` (${j.year})` : ""))}${seasonTag(j)} ${familyTag(j.disc_family)}</h2>
    ${j.music && j.music.artist ? `<div class="np-sub">${esc(j.music.artist)}</div>` : ""}
    ${npPhase(j, verb) ? `<div class="np-sub">${esc(npPhase(j, verb))}</div>` : ""}
    ${j.warning ? `<div class="job-warn">${icon("triangle-exclamation")}<span>${esc(j.warning)}</span></div>` : ""}
    <div class="np-bar${working ? " working" : ""}" role="progressbar" aria-label="Progress of the whole rip"
         aria-valuemin="0" aria-valuemax="100"${working ? "" : ` aria-valuenow="${shown}"
         aria-valuetext="${shown}%, step ${p.step} of ${p.steps}${eta ? ", " + esc(eta) : ""}"`}>
      <i${working ? "" : ` style="transform:scaleX(${(p.pct / 100).toFixed(4)})"`}></i>${p.ticks.map(x =>
        `<b class="np-tick" style="left:${x.toFixed(1)}%"></b>`).join("")}</div>
    <div class="np-figs"><span class="np-pct">${working
      // No percentage to be had (reading an encrypted disc reports none): say how long
      // it's been going instead of a 0% that looks stuck.
      ? (j.started_at ? `${esc(duration(Math.max(0, Date.now() / 1000 - j.started_at)))} so far` : "")
      : `${shown}%`}</span><span class="grow"></span>
      <span class="np-eta">${esc(eta)}</span></div>
    ${(() => {
      // Everything about the current step on one labelled line, so its numbers aren't
      // read against the whole-rip percentage above.
      const bits = [npBytes(j), t && t.mine
        ? `${duration(t.elapsed)} of a usual ${duration(t.mine)}` : ""].filter(Boolean);
      return bits.length ? `<div class="np-step">This step: ${esc(bits.join(" \u00b7 "))}</div>` : "";
    })()}
    ${planned}
    ${npMakemkv(mk, j.device || "")}
    ${acts({ trail: `<button class="btn sm" data-cancel="${j.id}">${icon("xmark")} Cancel</button>` })}`;
}

/* The one moment Riparr needs a person, in the same card as everything else: the
   question, the poster for context, and one row of buttons. */
/* Under the stage name, something it didn't already say: how much has moved, or what
   the stage is waiting on. */
function npBytes(j) {
  const moved = j.state === "ripping" ? j.bytes_ripped
              : j.state === "transferring" ? j.bytes_sent
              : j.state === "verifying" ? j.bytes_verified : 0;
  return moved && j.bytes_total ? `${filesize(moved)} of ${filesize(j.bytes_total)}` : "";
}

function npPhase(j, stageName) {
  const ph = (j.phase || "").trim();
  if (!ph) return "";
  // "Reading the disc — 14 tracks catalogued" under "Reading the disc": keep the news,
  // drop the repeat.
  const lead = ph.split(/\s+[\u2014-]\s+/);
  if (lead[0].toLowerCase() === stageName.toLowerCase()) return lead.slice(1).join(" \u2014 ");
  const first = (x) => x.toLowerCase().split(" ")[0];
  return first(ph) === first(stageName) && lead.length === 1 ? "" : ph;
}

/* MakeMKV's own commentary -- what it's reading, which titles it found, what it skips --
   folded away, for anyone who wants to see exactly what it's doing. */
function npMakemkv(lines, dev) {
  lines = lines || [];
  if (!lines.length) return "";
  const t = (at) => new Date(at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
  return `<details class="np-mk" data-mk="${esc(dev)}"${(state.mkOpen || {})[dev] ? " open" : ""}>
    <summary>What MakeMKV is doing</summary>
    <ol class="np-mk-lines">${lines.slice().reverse().map(l =>
      `<li><time>${esc(t(l.at))}</time><span>${esc(l.text)}</span></li>`).join("")}</ol>
  </details>`;
}

function npAsk(j, acts) {
  // The prompt's form, under the same heading as every other card: what's happening,
  // the disc's name, and the question. The old header (label + badge) goes.
  const holder = document.createElement("div");
  holder.innerHTML = j.output === "music" ? musicPrompt(j) : identifyPrompt(j);
  const form = holder.firstElementChild;
  const q = form.querySelector(".job-phase")?.textContent.trim();
  form.querySelector(".job-head")?.remove();
  // One full-size primary, everything else the same small size, Eject held back while
  // the question is open -- the answer is about the disc that's in there.
  // TMDb's suggestions lead when there are any; typing a name is the fallback.
  const picks = form.querySelector(".ni-tmdb");
  const named = form.querySelector("label.f.wide");
  if (j.output !== "music" && picks && (j.candidates || []).length && named) {
    const other = document.createElement("details");
    other.className = "ni-other";
    other.innerHTML = `<summary>Not listed? Type the name</summary>`;
    named.querySelector(":scope > span:first-child")?.remove();
    other.append(named);
    picks.after(other);
    picks.querySelector(".ni-label").textContent = "Pick the film";
    form.prepend(picks);
  }
  const row = form.querySelector(".btn-row");
  if (row) {
    row.className = "np-acts";
    // Rip it is the one full-size button; the rest are small.
    row.querySelectorAll(".btn:not(.primary)").forEach(b => b.classList.add("sm"));
    row.insertAdjacentHTML("beforeend",
      acts({ ejectDisabled: true }).replace(/^<div class="np-acts">|<\/div>$/g, ""));
  }
  const name = (j.episode_plan || {}).series || j.title || pretty(j.disc_label)
    || (j.output === "music" ? "Audio CD" : "A disc");
  const tv = !!(j.episode_plan || {}).episodes;
  return `
    <div class="np-kicker ask">${icon("circle-question")} Needs you</div>
    <h2 class="np-title" tabindex="-1">${esc(name)} ${familyTag(j.disc_family)}</h2>
    ${j.disc_label && pretty(j.disc_label) !== name && j.disc_label !== name
      ? `<div class="np-sub">${esc(j.disc_label)}</div>` : ""}
    <p class="np-q">${esc(q || (tv ? "Check the episodes before Riparr rips them." : "Which film is this?"))}</p>
    ${form.outerHTML}`;
}

function npIdle(drives, loaded, busy, acts, checklist = true) {
  const d = loaded || drives[0];
  // With two drives the checklist is said once, on the first card, not on both. A CD
  // doesn't go anywhere near MakeMKV, so MakeMKV's problems don't block one.
  const makemkv = ["Riparr can read discs", "The MakeMKV key is current"];
  const blocking = checklist ? problems(state.status).filter(p => p.level === "bad"
    && !(loaded && loaded.disc_family === "cd" && makemkv.includes(p.what))) : [];
  if (!loaded && blocking.length) {
    return `
      <div class="np-kicker ask">${icon("triangle-exclamation")} Not ready</div>
      <h2 class="np-title" tabindex="-1">Finish setting up</h2>
      <ul class="np-todo">${blocking.map(p => `<li>${esc(p.short || p.message)}${
        p.href ? ` <a href="${esc(p.href)}">Fix</a>` : ""}</li>`).join("")}</ul>
      <div class="np-sub">Then insert a disc.</div>`;
  }
  if (!loaded) {
    return `
      <div class="np-kicker">${icon("compact-disc")} Ready</div>
      <h2 class="np-title" tabindex="-1">Nothing in the tray</h2>
      <div class="np-sub">${state.autoripOn
        ? "Insert a disc and close the tray. Riparr takes it from there."
        : "Insert a disc and close the tray, then press Rip this disc."}</div>`;
  }
  const todo = blocking.length ? `<ul class="np-todo">${blocking.map(p => `<li>${esc(p.short || p.message)}${
    p.href ? ` <a href="${esc(p.href)}">Fix</a>` : ""}</li>`).join("")}</ul>` : "";
  return `
    <div class="np-kicker${blocking.length ? " ask" : ""}">${icon(blocking.length ? "triangle-exclamation" : "compact-disc")} ${
      blocking.length ? "Disc loaded \u00b7 not ready to rip" : "Disc loaded"}</div>
    <h2 class="np-title" tabindex="-1">${esc(pretty(d.label) || d.label
      || (d.disc_family === "cd" ? "Audio CD" : "A disc"))} ${familyTag(d.disc_family)}</h2>
    ${d.label ? `<div class="np-sub">${esc(d.label)}${d.disc_word ? ` \u00b7 ${esc(d.disc_word)}` : ""}</div>`
      : d.audio_tracks ? `<div class="np-sub">${d.audio_tracks} track${d.audio_tracks === 1 ? "" : "s"} \u00b7 Riparr looks it up on MusicBrainz when you rip it</div>` : ""}
    ${todo}
    ${d.space_warning ? `<p class="np-err np-caution">${esc(d.space_warning)}</p>` : ""}
    ${acts({ lead: busy ? "" : blocking.length
      // A rip that can only fail isn't offered as though it would work.
      ? `<button class="btn sm" disabled>Fix ${blocking.length} thing${blocking.length === 1 ? "" : "s"} first</button>`
      : `<button class="btn sm primary" data-rip="${esc(d.device || "")}">${icon("play")} Rip this disc</button>` })}`;
}

/* The end of a path, which is the part that says where it went; the whole of it is one
   tap away. */
function shortPath(p, folder = false) {
  const parts = String(p || "").split("/").filter(Boolean);
  // The folder it's in -- "Movies/The Matrix (1999)" -- not the file name, which on a
  // TRaSH template is most of a line by itself. When the destination *is* a folder (an
  // album, a full-disc backup), its own name and the one above it.
  if (folder) return parts.length > 2 ? parts.slice(-2).join("/") : String(p || "");
  return parts.length > 2 ? parts.slice(-3, -1).join("/") : String(p || "");
}
const isFolderJob = (j) => j && (j.output === "music" || j.output === "backup");

function npFiled(j, acts) {
  const ok = j.state === "done";
  const size = j.bytes_sent || j.bytes_ripped || j.bytes_total;
  const worked = (j.stages || []).reduce((a, st) => a + st.seconds, 0);
  const checked = { quick: "size check passed", deep: "full check passed" }[j.verified_mode];
  const facts = [size ? filesize(size) : "", worked ? `took ${duration(worked)}` : "",
                 checked || ""].filter(Boolean);
  // A failed rip is retried here, with the same verbs History offers -- not by sending
  // somebody off to History to find the button.
  const retry = !ok && (j.retries || [])[0];
  return `
    <div class="np-kicker ${ok ? "ok" : "bad"}">${icon(ok ? "circle-check" : "triangle-exclamation")}
      ${ok ? "In your library" : "Didn't finish"} <span class="muted">· ${esc(ago(j.finished_at))}</span></div>
    <h2 class="np-title" tabindex="-1">${esc(filedName(j))} ${familyTag(j.disc_family)}</h2>
    ${j.music && j.music.artist ? `<div class="np-sub">${esc(j.music.artist)}</div>`
      : j.disc_label && j.title ? `<div class="np-sub">${esc(j.disc_label)}</div>` : ""}
    ${ok && j.dest_path ? `<details class="np-path"><summary>${icon("hard-drive")}<span>${
        esc(shortPath(j.dest_path, isFolderJob(j)))}</span></summary><code>${esc(j.dest_path)}</code></details>` : ""}
    ${!ok && j.error ? `<p class="np-err">${esc(j.error)}</p>` : ""}
    ${ok && facts.length ? `<div class="np-facts">${facts.map(esc).join(" · ")}</div>` : ""}
    ${acts({ ejectPrimary: ok, lead: retry ? `<button class="btn sm primary" data-hretry="${j.id}" data-haction="${esc(retry.action)}"
                title="${esc(retry.why)}">${icon(RETRY_ICON[retry.action] || "arrows-rotate")} ${esc(retry.label)}</button>` : "",
              trail: `<a class="btn sm" href="#/history">History</a>
      <button class="btn sm" data-filed-dismiss="${j.id}">Dismiss</button>` })}`;
}

function npKnown(d, acts) {
  const k = d.known;
  const name = k.title ? (k.year ? `${k.title} (${k.year})` : k.title) : (d.label || "This disc");
  return `
    <div class="np-kicker ok">${icon("circle-check")} Already in your library
      <span class="muted">· ripped ${esc(ago(k.ripped_at))}</span></div>
    <h2 class="np-title" tabindex="-1">${esc(name)} ${familyTag(d.disc_family)}</h2>
    ${k.artist ? `<div class="np-sub">${esc(k.artist)}</div>`
      : d.label ? `<div class="np-sub">${esc(d.label)}</div>` : ""}
    ${acts({ ejectPrimary: true, trail: `<button class="btn sm" data-rerip="${esc(k.fingerprint)}">${icon("arrows-rotate")} Rip again</button>
      <a class="btn sm" href="#/discs">See it in Discs</a>` })}`;
}

/* A rip finishing is said out loud to screen readers -- once, when it happens, not
   every time the page is opened afterwards. */
let lastFiledSeen;
function announceFiled(j) {
  const id = j ? j.id : null;
  if (lastFiledSeen !== undefined && id && id !== lastFiledSeen) {
    say(j.state === "done"
      ? `${filedName(j)} is in your library.`
      : `${filedName(j)} didn't finish. ${j.error || ""}`);
  }
  lastFiledSeen = id;
}

let askSeen = new Set();
function announceAsk(asking) {
  const ids = new Set(asking.map(j => j.id));
  const fresh = asking.filter(j => !askSeen.has(j.id));
  if (fresh.length) say(`${fresh[0].title || pretty(fresh[0].disc_label) || "A disc"} needs you.`);
  askSeen = ids;
  state.asking = asking.length;
  // In the tab title too, so it's seen from another tab.
  document.title = asking.length ? `(${asking.length}) Needs you \u00b7 Riparr` : "Riparr";
}

/* Clear, then set: a live region only speaks when its text changes, and the same film
   finishing twice would otherwise be silent the second time. */
function say(text) {
  const el = $("#announce");
  if (!el) return;
  el.textContent = "";
  setTimeout(() => { el.textContent = text; }, 60);
}

function focusHeading() {
  const h = $("#content .np-title") || $("#content .page-head h1");
  if (!h) return;
  if (!h.hasAttribute("tabindex")) h.setAttribute("tabindex", "-1");
  h.focus({ preventScroll: false });
}

/* ── the rip that just finished ──
   Finishing used to be a three-second toast and then an empty page, so the one moment
   the whole box exists for -- the film is in your library -- left no trace unless you
   happened to be looking. This keeps it on the card, with where it went and what it
   cost, until the next disc goes in or it is dismissed. */
const filedArts = {};           // job id -> poster, once looked up (null while asking)
const filedArtFor = (j) => (j && filedArts[j.id]) || null;
const FILED_KEY = "riparr.filedDismissed";

// The finished cards dismissed in this browser. One per drive can be showing, so it's a
// short list; it used to be a single id.
function dismissedFiled() {
  let v = null;
  try { v = JSON.parse(localStorage.getItem(FILED_KEY) || "null"); } catch (e) { /* fine */ }
  return Array.isArray(v) ? v.map(String) : v != null ? [String(v)] : [];
}

function showFiled(job, loaded) {
  if (!job) return false;
  if (dismissedFiled().includes(String(job.id))) return false;
  // Still the same disc (not yet ejected), or nothing in the tray at all.
  return !loaded || (loaded.label || "") === (job.disc_label || "");
}

function filedName(j) {
  const t = j.title || pretty(j.disc_label) || "Unknown disc";
  return j.year && j.kind !== "tv" ? `${t} (${j.year})` : t;
}

async function setFiledArt(j) {
  // An album brings its own cover; looking it up by name would find a film.
  if (j.id in filedArts || j.art || j.kind === "music") return;
  filedArts[j.id] = null;
  // The title first, then the disc label: the lookup is strict, and either alone can
  // miss where the other is certain.
  let hit = null;
  for (const label of [j.title, j.disc_label].filter(Boolean)) {
    try { hit = await api.get(`/api/artwork?label=${encodeURIComponent(label)}`); }
    catch (e) { return; }
    if (hit && hit.ok) break;
  }
  if (!hit || !hit.ok) return;
  await new Promise((res) => {
    const img = new Image();
    img.onload = img.onerror = res;
    img.src = hit.image;
  });
  filedArts[j.id] = hit.image;
  if ((location.hash.replace(/^#\//, "").split("/")[0] || "queue") === "queue") route({ live: true });
}

/* ── a job in flight ──
   A table row cannot hold a question, and `needs_input` has to be able to ask one, so
   a job is a block rather than a `<tr>`. That also buys room for the phase line, which
   is the difference between a bar that is moving and a box that has hung -- the
   distinction that decides whether somebody pulls the cable. */

/* ── which disc is this, at a glance ──
   Riparr's three families, in the words on the box. The Queue, History and Discs all
   render this identically, because "is that my DVD or my Blu-ray of the same film" is
   a question the answer to must not change shape depending on where it is asked. */
const FAMILY = {
  dvd:    { label: "DVD",     cls: "fam-dvd" },
  bluray: { label: "Blu-ray", cls: "fam-bluray" },
  uhd:    { label: "4K UHD",  cls: "fam-uhd" },
  cd:     { label: "CD",      cls: "fam-cd" },
};

function familyTag(family, extra = "") {
  const f = FAMILY[family];
  if (!f) return "";
  return `<span class="fam ${f.cls}${extra ? " " + extra : ""}">${esc(f.label)}</span>`;
}

const STATE_LABEL = {
  queued: "Waiting", identifying: "Reading the disc", ripping: "Ripping",
  transferring: "Uploading", verifying: "Verifying", needs_input: "Needs you",
};

/* ── still crossing the network ──
   A disc whose rip is on the card has already been handed back, and the next one may
   well be spinning. These jobs are finished as far as the user is concerned -- they
   just are not *there* yet -- so they get a quiet strip under the drive rather than a
   panel competing with the disc actually in the machine. */
function sendingStrip(sending) {
  if (!sending.length) return "";
  return `<div class="sending">
    <div class="sending-head">${icon("upload")}
      <span>${sending.length === 1 ? "Still crossing to your library"
                                   : `${sending.length} still crossing to your library`}</span>
      <span class="grow"></span>
      <span class="muted">the drive is free — put the next disc in</span></div>
    ${sending.map(j => {
      const done = j.state === "verifying" ? 100 : Number(pct(j.bytes_sent, j.bytes_total));
      return `<div class="send-row">
        <span class="send-name" title="${esc(j.title || j.disc_label || "")}">${
          esc(j.title || j.disc_label || "Unknown disc")}</span>
        ${familyTag(j.disc_family)}
        <div class="send-bar"><i style="width:${done}%"></i></div>
        <span class="send-pct">${
          j.state === "verifying" ? "checking"
          : done > 0 ? `${Math.round(done)}%` : "waiting"}</span>
        <span class="send-size muted">${esc(filesize(j.bytes_total))}</span>
        <button class="icon-btn" data-cancel="${j.id}" title="Cancel" aria-label="Cancel this rip"
                aria-label="Cancel sending ${esc(j.title || j.disc_label || "this disc")}">${icon("xmark")}</button>
      </div>`;
    }).join("")}
  </div>`;
}


/* What a season job is, in the four words there is room for next to its title. A TV
   job's own title is the series, which on its own reads exactly like a film -- and the
   difference between "ripping Twin Peaks" and "ripping six episodes of Twin Peaks"
   is the whole reason somebody would look at this panel. */
function seasonTag(j) {
  const plan = j.episode_plan;
  if (!plan || !(plan.episodes || []).length) return "";
  const kept = plan.episodes.filter(e => e.include !== false);
  if (!kept.length) return "";
  const done = kept.filter(e => e.state === "done").length;
  const range = kept.length === 1 ? episodeCode(kept[0])
    : `${episodeCode(kept[0])}–${episodeCode(kept[kept.length - 1]).split("E").pop()}`;
  return ` <span class="season-tag">${esc(range)}${
    done && done < kept.length ? ` · ${done}/${kept.length} done` : ""}</span>`;
}

/* What's left, said once. The stage clock below the bar answers "is this stage slow";
   this answers "when can I come back". They used to disagree near the end -- "11s so
   far" beside "about 0s left in this stage" -- because each guessed on its own. Both
   now come from stageTiming(), and both say "finishing up" for the last minute. */
function overallEta(j) {
  const now = Date.now() / 1000;
  const t = stageTiming(j);
  if (t && t.mine && !t.over) {
    const total = t.left + t.restSecs;
    return total < 60 ? "finishing up" : `done around ${clockAt(now + total)}`;
  }
  // A stage just past its usual time is still finishing, not late.
  if (t && t.mine && t.over && -t.left < 60) {
    // A step just past its usual time is nearly done; the steps after it aren't.
    return t.restSecs < 60 ? "finishing up" : `done around ${clockAt(now + t.restSecs + 30)}`;
  }
  if (j.eta_seconds) return j.eta_seconds < 60 ? "finishing up" : `${duration(j.eta_seconds)} left`;
  if (t && t.over) return "taking longer than usual";
  if (j.started_at && state.typical && j.started_at + state.typical > now + 60)
    return `usually done by ${clockAt(j.started_at + state.typical)}`;
  if (j.started_at) return `${duration(Math.max(0, now - j.started_at))} so far`;
  return "";
}

/* ── disc details ──
   Everything MakeMKV said about the disc, title by title, and what Riparr makes of each
   for naming. For checking a name before a long rip, and for a bug report when one
   comes out wrong: Copy puts a plain-text version on the clipboard. */
const fmtStream = (x) => [x.type, x.codec_long || x.codec_short, x.video_size,
  x.layout || (x.channels ? `${x.channels} ch` : ""), x.lang, x.name]
  .filter(Boolean).join(" · ");

function discReport(d) {
  const lines = [`Riparr ${state.status ? state.status.version : ""} disc details`,
    `Drive: ${d.drive ? [d.drive.vendor, d.drive.model, d.drive.device].filter(Boolean).join(" ") : "none"}`,
    `Label: ${(d.drive && d.drive.label) || "-"}   Media: ${(d.drive && d.drive.media) || "-"}   Family: ${d.family || "-"}`,
    `From: ${d.source === "job" ? "the rip in progress" : "a scan"}`, ""];
  for (const t of d.titles) {
    lines.push(`Title ${t.index}${t.chosen ? " (ripping this one)" : ""}: ${duration(t.seconds)}, ${gb(t.bytes || 0)}, ${t.chapters || 0} chapter${t.chapters === 1 ? "" : "s"}, ${t.source || t.name || ""}`);
    (t.streams || []).forEach(x => lines.push(`  ${fmtStream(x)}`));
    const m = t.media || {};
    lines.push(`  -> ${[m.quality, m.video_codec, m.bit_depth && m.bit_depth + "bit", m.dynamic_range,
                        m.audio_codec, m.audio_channels, m.audio_languages].filter(Boolean).join(" ")}`);
  }
  return lines.join("\n");
}

// The phone's status bar follows the theme: Windows 98's title bar is navy.
function applyTheme(name) {
  $("#theme").href = `/static/themes/${name}.css`;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = name === "win98" ? "#000080" : "#241155";
}

const clockTime = (sec) => `${Math.floor((sec || 0) / 60)}:${String((sec || 0) % 60).padStart(2, "0")}`;

/* A question with two answers, in the app's own dialog rather than the browser's: it
   can say which drive, show a warning, and looks like the rest of Riparr. Resolves to
   true for the main button. */
function askDialog({ title, body = "", ok = "OK", cancel = "Cancel", danger = false }) {
  return new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.className = "notice-dialog";
    d.setAttribute("aria-labelledby", "ask-title");
    d.innerHTML = `<h2 id="ask-title">${esc(title)}</h2>${body}
      <div class="btn-row">
        <button class="btn ${danger ? "danger" : "primary"}" data-ok>${esc(ok)}</button>
        <button class="btn" data-no>${esc(cancel)}</button></div>`;
    document.body.appendChild(d);
    const done = (v) => { d.close(); d.remove(); resolve(v); };
    d.querySelector("[data-ok]").onclick = () => done(true);
    d.querySelector("[data-no]").onclick = () => done(false);
    d.addEventListener("cancel", (e) => { e.preventDefault(); done(false); });
    d.showModal();
    d.querySelector("[data-no]").focus();
  });
}

async function showDiscDetails(device = "") {
  const q = device ? `?device=${encodeURIComponent(device)}` : "";
  const dlg = document.createElement("dialog");
  dlg.className = "notice-dialog disc-dlg";
  document.body.appendChild(dlg);
  const close = () => { dlg.close(); dlg.remove(); };
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  let timer = null;

  const paint = async () => {
    let d;
    try { d = await api.get(`/api/disc/details${q}`); }
    catch (e) { dlg.innerHTML = `<div class="result bad">${esc(e.message)}</div>`; return; }
    const titles = d.titles || [];
    const cd = d.family === "cd";
    const drive = (state.status && state.status.drives || []).find(x => x.device === d.device)
      || (state.status && state.status.drives || [])[0];
    // The disc's own name: what Riparr knows it as, else its label, tidied.
    const known = drive && drive.known;
    const heading = (known && (known.year ? `${known.title} (${known.year})` : known.title))
      || pretty((d.drive && d.drive.label) || "") || (cd ? "Audio CD" : "Disc");
    dlg.innerHTML = `
      <div class="dlg-head"><h3>${esc(heading)}</h3>
        <span class="grow"></span>${familyTag(d.family)}
        <button class="icon-btn" data-close aria-label="Close">${icon("xmark")}</button></div>
      ${drive ? `<p class="disc-drive">${icon("compact-disc")} ${esc(driveName(drive))}
          <span class="muted">${esc(drive.device || "")}${drive.reads ? ` \u00b7 reads ${esc(drive.reads)}` : ""}</span></p>` : ""}
      <p class="muted">${
        d.source === "job" ? "From the rip in progress."
        : d.source === "toc" ? "From the CD's table of contents. The track names come from MusicBrainz when it's ripped."
        : d.source === "scan" ? "From the last scan of this disc."
        : "This disc hasn't been read yet."}${cd ? ""
        : " Titles under a minute are menus and idents and are left out."}</p>
      ${d.scanning ? `<div class="result busy"><span class="spin"></span><span>${esc(
          d.scan_progress || "Reading the disc")}${d.scan_seconds != null
          ? ` \u00b7 ${esc(duration(d.scan_seconds))}` : ""}<br><span class="muted">An
          encrypted disc can take several minutes. MakeMKV's progress is on
          <a href="#/system/logs">System \u2192 Log Files</a>.</span></span></div>`
        : !titles.length ? `<div class="btn-row"><button class="btn primary" data-scan>Read the disc</button>
          <span class="test-out">Only while nothing is ripping.</span></div>` : ""}
      ${d.scan_error ? `<div class="result bad">${esc(d.scan_error)}</div>` : ""}
      ${cd ? `<ol class="cd-tracks">${titles.map(t => `<li><span>${esc(t.name || `Track ${t.index}`)}</span>
          <span class="muted">${esc(clockTime(t.seconds))}</span></li>`).join("")}</ol>` : ""}
      <div class="disc-titles">${cd ? "" : titles.filter(t => t.seconds >= 60).map(t => {
        const m = t.media || {};
        const tags = [m.quality, m.video_codec, m.bit_depth && `${m.bit_depth}-bit`, m.dynamic_range,
                      [m.audio_codec, m.audio_channels].filter(Boolean).join(" "), m.audio_languages]
                     .filter(Boolean);
        return `<div class="disc-title${t.chosen ? " chosen" : ""}">
          <div class="dt-head"><b>Title ${t.index}</b>
            <span>${esc(duration(t.seconds))}</span><span class="muted">${esc(gb(t.bytes || 0))}</span>
            <span class="muted">${t.chapters || 0} chapter${t.chapters === 1 ? "" : "s"}</span>
            <span class="muted">${esc(t.source || t.name || "")}</span>
            ${t.chosen ? `<span class="badge ok">ripping this one</span>` : ""}</div>
          <div class="dt-media">${tags.map(x => `<code>${esc(x)}</code>`).join(" ") || `<span class="muted">no stream details</span>`}</div>
          <ul class="dt-streams">${(t.streams || []).map(x => `<li>${esc(fmtStream(x))}</li>`).join("")}</ul>
        </div>`;
      }).join("")}</div>
      <div class="btn-row">
        ${titles.length ? `<button class="btn" data-copy>Copy as text</button>` : ""}
        ${d.raw ? `<a class="btn" href="/api/disc/raw${q}" download>MakeMKV's raw output</a>` : ""}
        <button class="btn" data-close>Close</button>
      </div>`;
    paintIcons(dlg);
    dlg.querySelectorAll("[data-close]").forEach(b => b.onclick = close);
    const copy = dlg.querySelector("[data-copy]");
    if (copy) copy.onclick = async () => {
      try { await navigator.clipboard.writeText(discReport(d)); toast("Copied", "ok"); }
      catch (e) { toast("Couldn't copy — your browser blocked it", "bad"); }
    };
    const scan = dlg.querySelector("[data-scan]");
    if (scan) scan.onclick = async () => {
      scan.disabled = true;
      try { await api.post("/api/disc/scan", { device }); } catch (e) { toast(e.message, "bad"); }
      paint();
    };
    clearTimeout(timer);
    if (d.scanning && dlg.open) timer = setTimeout(paint, 3000);
  };
  dlg.showModal();
  dlg.innerHTML = `<div class="result busy"><span class="spin"></span>Loading…</div>`;
  await paint();
}

/* Where the rip is going, before it gets there. */
function plannedLine(j) {
  const p = j.planned;
  if (!p || !p.path) return "";
  const what = p.kind === "tv"
    ? `${p.count} episode${p.count === 1 ? "" : "s"}, the first saved as`
    : p.kind === "backup" ? "Will be saved in" : "Will be saved as";
  return `<div class="job-planned">${icon("folder-open")}
    <span>${what} <code>${esc(p.path)}</code></span></div>`;
}

/* Point the browser at the disc it already has, once. The acknowledgement is what
   stops it happening again on the next poll -- without it the page would bounce back
   to Discs every five seconds and the user could never leave. */
async function goToDuplicate(dupe) {
  try { await api.post("/api/duplicate/ack", {}); } catch (e) { /* show it anyway */ }
  location.hash = `#/discs/${encodeURIComponent(dupe.fingerprint)}`;
}

/* ── the counting timer ──
   MakeMKV cannot say how far through a disc scan it is, and the kernel cannot see the
   reads because they go through /dev/sg0 -- so for the sixteen minutes before a byte
   is written there is no percentage to show and never will be. What there is: this box
   has done this before and took about as long each time.

   So the slow stages get a clock instead of a bar. It counts up (which is always true)
   against the median (which is a guess, and says so), and the remaining stages are
   added on to answer the question actually being asked -- when can I come back. */
function stageLabel(j, name) {
  // The job's own mode decides the words: a staged rip isn't "writing to your library".
  const sets = state.stageLabelSets || {};
  const set = (j.mode && j.mode !== "direct" ? sets.staged : sets.direct) || state.stageLabels || {};
  return set[name] || name;
}

function stageTiming(j) {
  const med = state.typicalStages || {};
  const order = state.stageOrder || [];
  const name = j.stage_name;
  if (!name || !j.stage_started) return null;
  const elapsed = Math.max(0, Date.now() / 1000 - j.stage_started);
  const mine = med[name] && med[name].seconds;
  // Everything after this stage, at its usual cost. Verification is skipped when it
  // is off, because promising a stage that will not run is worse than a vaguer number.
  const at = order.indexOf(name);
  const rest = at < 0 ? [] : order.slice(at + 1)
    .filter(k => med[k] && !(k === "verify" && state.settings
                             && state.settings.verify_mode === "off"));
  const restSecs = rest.reduce((a, k) => a + med[k].seconds, 0);
  const left = mine ? mine - elapsed : null;
  return { name, elapsed, mine, left, over: mine ? left < 0 : false, restSecs };
}

/* The server is allowed to change a setting you did not send -- see db.reconcile,
   where turning on direct rips takes deep verification with it, because deep has
   nothing to compare against once there is only one copy. Everything it changed comes
   back under `adjusted`, so the fix is to copy it into local state rather than to
   re-fetch, and callers get the map back so they can mention it. */
function applyAdjusted(res) {
  const adj = (res && res.adjusted) || {};
  if (state.settings) Object.assign(state.settings, adj);
  return adj;
}

/* `direct` is passed rather than read, because the caller has already worked out
   whether this rip has two copies and the answer changes what "quick" is worth saying
   about. On a direct rip the size check is not the cheap half of a choice -- it is the
   whole of what can honestly be checked, and the note should say why rather than
   leaving somebody hunting for a deep option that is deliberately absent. */
function verifyNote(direct) {
  const s = state.settings || {};
  if (s.verify_mode === "off") return "Nothing is checked after the upload.";
  if (s.verify_mode === "deep")
    return "Reads the whole film back off the share — roughly doubles the time and needs as much free space again.";
  return direct
    ? "Compares the size on your library with what was sent. Going straight to your library leaves one copy, so there is nothing to hash it against — this is the whole check."
    : "Compares the size on your library with what was sent.";
}

const leg = (p) => (p >= 100 ? "\u2713" : p > 0 ? `${Math.round(p)}%` : "");

/* Time, not bytes. concept.md says the user should never see a gigabyte and says the
   same about progress and time estimates; the queue did the first half and showed two
   bars that answered "how far" but never "how long". */
/* A wall-clock time, because "usually done by 07:12" is a thing a person can plan
   around and "about 26 minutes" is a thing they have to do arithmetic on. */
function clockAt(epochSeconds) {
  const d = new Date(epochSeconds * 1000);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function duration(sec) {
  sec = Math.max(0, Math.round(sec));
  if (sec < 90) return `${sec}s`;
  const m = Math.round(sec / 60);
  if (m < 90) return `${m} min`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

/* ── the identify prompt ──
   `on_unknown_disc` has defaulted to "ask" since the beginning and nothing anywhere
   asked. This is the asking. */
/* ── the episode plan ──
   A season disc asks a different question from a film disc. A film asks "what is this
   and which title is it"; a season asks "is this the right order, starting at the right
   number", which is a table, not a radio group.

   The table is the answer to a problem that has no clean automatic solution: the disc
   knows its own episode order and the metadata knows the episode names, and on a
   handful of famous shows the two disagree because the broadcast order was not the
   production order. Riparr takes the sequence from the disc and the names from the guide
   and shows both together, so the disagreement is visible in one glance instead of
   being discovered a year later mid-rewatch. Shifting the first episode number
   renumbers and renames in one move, which fixes the whole disc in one control. */

function seasonPrompt(j) {
  const plan = j.episode_plan || {};
  const rows = plan.episodes || [];
  const opts = plan.series_options || [];
  const trust = { high: ["Read off the disc", "ok"], medium: ["Very likely right", ""],
                  low: ["A guess", "warn"] }[plan.confidence] || ["", ""];
  return `
    <div class="job needs">
      <div class="job-head">
        <div class="grow">
          <div class="job-title">${esc(plan.series || j.disc_label || "A season disc")}</div>
          <div class="job-phase">${esc(j.question || "Check this before Riparr rips it.")}</div>
        </div>
        <span class="badge warn">Needs you</span>
      </div>

      ${(plan.warnings || []).length ? `
        <ul class="ep-warnings">
          ${plan.warnings.map(w => `<li>${esc(w)}</li>`).join("")}
        </ul>` : ""}

      <div class="ep-controls">
        <label class="f"><span>Series</span>
          ${opts.length ? `
            <select id="ep-series">
              ${opts.map(o => `<option value="${o.id}"
                ${o.id === plan.series_id ? "selected" : ""}>${esc(o.name)}${
                  o.year ? ` (${esc(o.year)})` : ""}${
                  o.network ? ` — ${esc(o.network)}` : ""}</option>`).join("")}
              <option value="">Not listed — use the name below</option>
            </select>` : ""}
          <input id="ep-name" value="${esc(plan.series || "")}"
                 placeholder="e.g. Twin Peaks">
          <span class="help">${opts.length
            ? "Picking a different series re-fetches the episode names. The box below "
              + "is the folder name."
            : "This is the folder name."}</span></label>
        <label class="f"><span>Season</span>
          <input id="ep-season" type="number" min="0" max="99" style="width:80px"
                 value="${plan.season === null || plan.season === undefined
                          ? "" : plan.season}">
          <span class="help">Set 0 to file these as specials.</span></label>
        <label class="f"><span>First episode</span>
          <input id="ep-first" type="number" min="1" max="999" style="width:80px"
                 value="${rows.length ? rows[0].episode : 1}">
          <span class="help">Shift this if the disc doesn't start where the episode guide does.</span>
        </label>
      </div>

      ${trust[0] ? `<div class="ep-trust">
        <span class="badge ${trust[1]}">${esc(trust[0])}</span>
        <span class="muted">Episode order ${plan.order_source === "segments"
          ? "came from the disc's own “play all” list, which is as good as it gets."
          : plan.order_source === "source"
          ? "came from the disc's playlist numbering."
          : "could not be read from the disc — this is the order MakeMKV found them in."
        }</span></div>` : ""}

      <div class="ep-table" id="ep-rows">
        ${rows.map((e, i) => episodeRow(e, i, rows.length)).join("")}
      </div>

      <div class="btn-row">
        <button class="btn primary" data-answer-season="${j.id}">
          Rip ${rows.length} episode${rows.length === 1 ? "" : "s"}</button>
        <button class="btn" data-skip="${j.id}">Skip this disc</button>
      </div>
      ${plan.series_id == null ? "" : plan.series_id < 0
        ? `<div class="ep-credit muted">Episode names from
            <a href="https://www.themoviedb.org" target="_blank" rel="noopener">TMDb</a>.
            This product uses the TMDB API but is not endorsed or certified by TMDB.</div>`
        : `<div class="ep-credit muted">Episode names from
            <a href="https://www.tvmaze.com" target="_blank" rel="noopener">TVmaze</a>.</div>`}
    </div>`;
}

function episodeRow(e, i, total) {
  const span = e.episode_last && e.episode_last > e.episode;
  return `
    <div class="ep-row" data-ti="${e.title_index}">
      <input type="checkbox" class="ep-keep" ${e.include === false ? "" : "checked"}>
      <span class="ep-num">${esc(episodeCode(e))}${span ? "" : ""}</span>
      <span class="ep-dur">${esc(duration(e.seconds))}</span>
      <input class="ep-title" value="${esc(e.episode_title || "")}"
             placeholder="${span ? "Two episodes in one file" : "No name"}">
      <span class="ep-src muted">${esc(e.source || `Title ${e.title_index}`)}</span>
      <span class="ep-move">
        <button class="btn tiny" data-up="${e.title_index}" ${i === 0 ? "disabled" : ""}
                title="Move earlier">↑</button>
        <button class="btn tiny" data-down="${e.title_index}"
                ${i === total - 1 ? "disabled" : ""} title="Move later">↓</button>
      </span>
    </div>`;
}

function episodeCode(e) {
  const pad = (n) => String(n).padStart(2, "0");
  const head = (e.season === null || e.season === undefined)
    ? `E${pad(e.episode)}` : `S${pad(e.season)}E${pad(e.episode)}`;
  return (e.episode_last && e.episode_last > e.episode)
    ? `${head}-E${pad(e.episode_last)}` : head;
}

/* The question a control belongs to. Two drives can both be asking at once, each card
   with the same fields, so every lookup is made inside the card the control is in. */
const askRoot = (el) => el.closest(".job.needs") || document;

function identifyPrompt(j) {
  if ((j.episode_plan || {}).episodes) return seasonPrompt(j);
  const titles = (j.titles || []).filter(t => t.seconds >= 60);
  return `
    <div class="job needs">
      <div class="job-head">
        <div class="grow">
          <div class="job-title">${esc(j.disc_label || "A disc")}</div>
          <div class="job-phase">${esc(j.question || "Riparr needs a hand with this one.")}</div>
        </div>
        <span class="badge warn">Needs you</span>
      </div>
      <label class="f wide"><span>What is this film?</span>
        <input class="ni-name-input" value="${esc(j.title || "")}" placeholder="e.g. The Matrix (1999)">
        <span class="help">A year in brackets is used as the year. Without one Riparr
          won't invent it.</span></label>
      ${plannedLine(j)}
      ${state.status && state.status.tmdb ? `
        <div class="ni-tmdb" data-tmdb-for="${j.id}" data-picked="${j.tmdb_id || ""}">
          <div class="ni-label">${(j.candidates || []).length
            ? "TMDb's suggestions — pick one to use its name, year and IDs"
            : "Find it on TMDb, to use its name, year and IDs"}</div>
          <div class="tmdb-picks">${tmdbPicks(j.candidates || [], j.tmdb_id)}</div>
          <div class="manual-row">
            <input class="ni-tmdb-q" placeholder="Search TMDb — e.g. Blade Runner 1982">
            <button class="btn ni-tmdb-go">Search</button>
          </div>
        </div>` : ""}
      ${titles.length > 1 ? `
        <div class="ni-titles">
          <div class="ni-label">Which title is the film?
            <span class="muted">The film is usually the longest. Riparr remembers your pick for this disc.</span></div>
          ${titles.map(t => `
            <label class="ni-title">
              <input type="radio" name="ni-title-${j.id}" value="${t.index}"
                     ${t.index === j.chosen_title ? "checked" : ""}>
              <span class="ni-dur">${esc(duration(t.seconds))}</span>
              <span class="ni-name">${esc(t.name || `Title ${t.index}`)}</span>
              <span class="ni-size muted">${t.bytes ? esc(gb(t.bytes)) : ""}</span>
            </label>`).join("")}
        </div>` : ""}
      <div class="btn-row">
        <button class="btn primary" data-answer="${j.id}">Rip it</button>
        <button class="btn" data-skip="${j.id}">Skip this disc</button>
      </div>
    </div>`;
}

const gb = (b) => `${(b / 1073741824).toFixed(1)} GB`;

/* TMDb films as cards. Picking one fills the name in and remembers the ID; the poster
   comes through Riparr's image proxy. */
/* "Which album is this CD?": MusicBrainz's candidates to pick from, a search, and
   typing the names as the last resort. */
function musicPrompt(j) {
  const cands = j.candidates || [];
  return `
    <div class="job needs" data-music-for="${j.id}" data-picked="">
      <div class="job-head"><div class="grow">
        <div class="job-title">Audio CD</div>
        <div class="job-phase">${esc(j.question || "Which album is this?")}</div></div>
        <span class="badge warn">Needs you</span></div>
      <div class="ni-tmdb">
        ${cands.length ? `<div class="ni-label">Pick the album</div>` : ""}
        <div class="tmdb-picks mb-picks">${albumPicks(cands)}</div>
        <div class="mb-search">
          <input class="mb-album" placeholder="Album" aria-label="Album">
          <input class="mb-artist" placeholder="Artist" aria-label="Artist">
          <button type="button" class="btn mb-go">Search MusicBrainz</button>
        </div>
      </div>
      <details class="ni-other"><summary>Not on MusicBrainz? Type it</summary>
        <label class="f wide"><span>Artist</span><input class="mb-typed-artist"></label>
        <label class="f wide"><span>Album</span><input class="mb-typed-album"
               placeholder="e.g. Rumours (1977)"></label>
      </details>
      <div class="btn-row">
        <button class="btn primary" data-answer-music="${j.id}">Rip it</button>
        <button class="btn" data-skip="${j.id}">Skip this disc</button>
      </div>
    </div>`;
}

function albumPicks(albums) {
  return (albums || []).map(a => `
    <button type="button" class="tmdb-pick" data-mb-pick="${esc(a.id)}"
        title="${esc([a.title, a.artist, a.year, a.country].filter(Boolean).join(" · "))}">
      <span class="tmdb-poster"${a.poster ? ` style="background-image:url('${esc(a.poster)}')"` : ""}></span>
      <span class="tmdb-name">${esc(a.title)}</span>
      <span class="tmdb-year muted">${esc([a.artist, a.year, a.country].filter(Boolean).join(" · "))}${
        a.track_count ? ` · ${a.track_count} tracks` : ""}</span>
    </button>`).join("");
}

function tmdbPicks(films, picked) {
  if (!films.length) return "";
  return films.map(f => {
    const name = f.year ? `${f.title} (${f.year})` : f.title;
    return `<button type="button" class="tmdb-pick${String(f.id) === String(picked) ? " on" : ""}"
        data-tmdb-pick="${f.id}" data-name="${esc(name)}" title="${esc(f.overview || name)}">
      <span class="tmdb-poster"${f.poster ? ` style="background-image:url('${esc(f.poster)}')"` : ""}></span>
      <span class="tmdb-name">${esc(f.title)}</span>
      <span class="tmdb-year muted">${esc(f.year || "")}</span>
    </button>`;
  }).join("");
}

/* ── the tray ──
   The disc and the drive holding it are one fact, so they are drawn once. Which of
   the three shapes below applies depends only on how far up the chain something is
   missing: no drive at all, a drive with an open tray, or a disc sitting in one. */

function driveName(d) {
  return d.known_as || [d.vendor, d.model].filter(Boolean).join(" ") || "Optical drive";
}

/* ── what the drive can read ──
   Three chips, always all three, lit or not. Showing only what a drive *can* do would
   answer the question people ask ("what have I got?") and not the one that costs them
   money ("can it do the discs on my shelf?") — and 4K is the one that costs money, so
   it is never folded into Blu-ray however tempting the width saving is.

   The server decides the 4K chip. It is the one of the three that hardware cannot
   self-report: there is no MMC profile for UHD, so the answer comes from the drive
   registry and from MakeMKV, and neither of those is in the browser. */
function driveTags(d) {
  const uhdOn = d.uhd === "yes" || d.libredrive === "enabled";
  const chips = [
    ["DVD", !!d.reads_dvd, null],
    ["Blu-ray", !!d.reads_bluray, null],
    ["4K UHD", uhdOn, d.reads_bluray ? d.uhd_label : null],
  ];
  return `<span class="drive-tags">${chips.map(([label, on, title]) =>
    `<span class="tag ${on ? "on" : ""}"${title ? ` title="${esc(title)}"` : ""}>${label}</span>`
  ).join("")}</span>`;
}

/* The drive, its device node and what it reads — one line, used by every tray shape
   so the three cannot drift apart. */
function driveLine(d) {
  return `<p class="tray-drive">${esc(driveName(d))}
    <span class="dev">${esc(d.device)}</span>${driveTags(d)}</p>`;
}

// The diagnosis hints mark their single actionable sentence with **bold**. Escape
// first, then promote -- never the other way round.
function mdBold(text) {
  return esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
}

function tray(drives, optical, canRip) {
  if (!drives.length) {
    // An empty card used to render as nothing at all, so "no drive" was communicated
    // by absence -- the one case where the user most needs to be told something.
    const hint = optical && optical.hint;
    return `<div class="empty-state tray-none">
      <div class="big">${icon("triangle-exclamation")}</div>
      <h2>No optical drive detected</h2>
      <p>Riparr has nothing to read a disc with, so nothing else on this page can
         happen yet.</p>
      ${hint ? `<p class="why">${mdBold(hint)}</p>` : ""}
    </div>`;
  }
  const d = drives.find(x => x.present) || drives[0];
  if (!d.present) {
    return `<div class="empty-state">
      <div class="big">${icon("compact-disc")}</div>
      <h2>Nothing in the queue</h2>
      <p>${state.autoripOn ? "Insert a disc and close the tray. Riparr takes it from there."
           : "Insert a disc and close the tray, then press Rip this disc."}</p>
      ${driveLine(d)}
    </div>`;
  }
  /* A disc this drive cannot read is not an error state to be discovered three
     minutes into a rip. It is the tray, described accurately, with the reason. */
  if (d.cannot_read) {
    return `<div class="empty-state tray-loaded bad">
      <div class="big">${icon("triangle-exclamation")}</div>
      <h2>${esc(d.label || d.disc_word || "Disc loaded")}</h2>
      <p class="why">${esc(d.cannot_read)}</p>
      ${driveLine(d)}
    </div>`;
  }
  /* "BD-ROM" is what the drive calls it. "4K UHD disc" is what is printed on the box
     the user is holding, and the server works out which of the two this is. */
  const what = d.disc_word || d.media;
  /* Known before the button is pressed. Rip this disc on a disc Riparr already has
     would only refuse it and eject it, so the honest offer is the re-rip. */
  if (d.known) {
    const k = d.known;
    const name = k.title ? (k.year ? `${k.title} (${k.year})` : k.title)
                         : (d.label || "this disc");
    return `<div class="empty-state tray-loaded known">
      <div class="big">${icon("circle-check")}</div>
      <h2>${esc(d.label || "Disc loaded")}</h2>
      <p>Already in your library: you ripped <b>${esc(name)}</b> ${esc(ago(k.ripped_at))}.</p>
      ${canRip ? `<div class="btn-row tray-go">
        <button class="btn" data-rerip="${esc(k.fingerprint)}">${icon("arrows-rotate")} Rip again</button>
        <a class="btn" href="#/discs">See it in Discs</a>
      </div>` : ""}
      ${driveLine(d)}
    </div>`;
  }
  return `<div class="empty-state tray-loaded">
    <div class="big spinning">${icon("compact-disc")}</div>
    <h2>${esc(d.label || "Disc loaded")}</h2>
    <p>${what ? `${esc(what)} \u2014 loaded and ready.` : "Loaded and ready."}</p>
    ${d.space_warning ? `<p class="why warn-text">${esc(d.space_warning)}</p>` : ""}
    ${canRip ? `<div class="btn-row tray-go">
      <button class="btn primary" data-rip="${esc(d.device || "")}">${icon("play")} Rip this disc</button>
    </div>` : ""}
    ${driveLine(d)}
  </div>`;
}

/* When there are rips to look at, the tray is a footer on the same card rather than
   the hero -- present, but not competing with the thing that is actually moving. */
function trayStrip(drives, optical) {
  if (!drives.length) {
    return `<div class="tray-strip bad">${icon("triangle-exclamation")}
      <span>No optical drive detected</span></div>`;
  }
  const d = drives.find(x => x.present) || drives[0];
  return `<div class="tray-strip">${icon("compact-disc")}
    <span>${esc(driveName(d))} <span class="dev">${esc(d.device)}</span></span>
    ${driveTags(d)}
    <span class="grow"></span>
    <span class="${d.present ? "loaded" : "muted"}">${
      d.present ? esc(d.label || d.disc_word || "disc loaded") : "tray empty"}</span></div>`;
}

const pct = (a, b) => (b ? Math.min(100, (a / b) * 100).toFixed(1) : 0);

/* The checklist is the answer to "it isn't auto ripping" -- a question asked most
   often with the switch already ON, when something downstream broke afterwards. Every
   prerequisite is listed on System → Status whether or not it is met; the queue only
   says how many need attention and links there, so the disc stays the first thing on
   the page. */
const CHECK_ICON = { ok: "circle-check", warn: "triangle-exclamation", fail: "circle-exclamation" };

const andList = (xs) => xs.length < 2 ? (xs[0] || "")
  : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;

function autoRipPanel(ar) {
  const on = ar.enabled;
  const checks = ar.checks || [];
  const fails = checks.filter(c => c.state === "fail").length;
  const warns = checks.filter(c => c.state === "warn").length;
  return `
    <div class="autorip ${on ? "on" : ar.ready ? "" : "blocked"}">
      <label class="ar-switch ${ar.ready ? "" : "off"}">
        <input type="checkbox" id="autorip" role="switch" ${on ? "checked" : ""}
               aria-labelledby="ar-title" aria-describedby="ar-sub"
               ${ar.ready ? "" : "disabled"}>
        <span class="track"></span>
      </label>
      <div class="ar-text">
        <div class="ar-title" id="ar-title">Auto Rip</div>
        <div class="ar-sub" id="ar-sub">${
          on ? "Insert a disc and walk away. Riparr does the rest and ejects when it's done."
          : ar.ready ? "Turn this on and Riparr starts ripping the moment a disc is inserted."
          : `Needs ${andList(checks.filter(c => c.state === "fail")
                .map(c => (CHECK_NEED[c.what] || [c.what.toLowerCase()])[0]))} first.`}</div>
        ${fails || warns ? `<a class="ar-fix ${fails ? "fail" : "warn"}" href="#/system/status">${
          icon(CHECK_ICON[fails ? "fail" : "warn"])} ${esc(
          fails ? `${fails} thing${fails === 1 ? "" : "s"} to fix first`
                : `${warns} thing${warns === 1 ? "" : "s"} worth knowing about`)} \u2192 System</a>` : ""}
      </div>
    </div>
    ${ripOptions()}`;
}

/* ── how every rip behaves ──
   These two settings kept being bolted onto the end of the Auto Rip blurb until it was
   a paragraph with form controls buried in it. They are not part of the switch: they
   govern a rip started by hand too. So they get their own strip, two matched cards,
   each with its control on the top line and the consequence underneath -- the same
   shape twice, which is what makes a panel read as designed rather than accumulated. */
/* Folded into one line by default: set once, rarely changed, and on a desktop the two
   open cards pushed the disc -- the thing the page is for -- below the fold. The line
   says what will actually happen, which is not always what the select says: direct
   with no library mounted is staged. */
function ripOptions() {
  const s = state.settings || {};
  const lib = (state.status && state.status.library) || {};
  const direct = s.transfer_mode === "direct";
  const route = direct && !lib.mounted ? "staged, then copied (library not usable yet)"
              : direct ? "straight to your library"
              : "staged, then sent";
  const check = { quick: "size check", deep: "full check", off: "no check" }[s.verify_mode]
                || "size check";
  // Changed in one place, Settings → Ripping; the Queue says what's set and links there.
  return `
  <a class="rip-opts-d rip-opts-link" href="#/settings/ripping">
    <span class="ropt-k">${icon("gears")} Rip options</span>
    <span class="ropt-sum">${esc(route)} · ${esc(check)}</span>
    <span class="ropt-change">Change</span></a>`;
}

/* ── History: the data page ──
   The two pages had swapped jobs. History was a wall of posters that answered "what
   have I got" -- which Discs already knew, since Discs *is* the record of what this
   box has seen -- and answered "what happened, and how long did it take" not at all.
   A grouped tile saying "5 attempts" is the exact shape of a number with nowhere to
   go: no way to see what the five were, when, or why four of them failed.

   So History is now one row per attempt, newest first, with the stage breakdown the
   rip engine records and the retries the box can actually perform. Posters moved to
   Discs, where the page had four columns of text and nothing to look at. */

const RETRY_ICON = {
  "upload": "upload", "rip": "compact-disc",
  "verify-quick": "circle-check", "verify-deep": "magnifying-glass",
};

views.history = async () => {
  const h = await api.get("/api/history");
  const jobs = h.jobs || [];
  if (!jobs.length) {
    return `${head("History", "Every attempt, what each stage cost, and what can be retried.")}
      <div class="card"><div class="empty-state"><div class="big">${icon("clock-rotate-left")}</div>
        <h2>No rips yet</h2><p>Finished and failed rips are recorded here with a
          breakdown of where the time went.</p></div></div>`;
  }

  // "5 attempts" was the old page's whole answer. The number is only useful if the
  // five are visible, so each row is numbered within its film and every one of them is
  // on screen -- the count becomes "try 4 of 5" on a row you can read the error of.
  const key = (j) => (j.title || j.disc_label || "?")
    .toLowerCase().replace(/[_.]+/g, " ").replace(/\s+/g, " ").trim();
  const tally = new Map();
  for (const j of jobs) tally.set(key(j), (tally.get(key(j)) || 0) + 1);
  const seen = new Map();
  // `jobs` is newest first, so counting down from the total numbers them in the order
  // they actually happened.
  for (const j of jobs) {
    const k = key(j);
    const n = (seen.get(k) || 0) + 1;
    seen.set(k, n);
    j._try = tally.get(k) - n + 1;
    j._tries = tally.get(k);
  }
  // A re-rip of a disc that already worked isn't a failed attempt; say which it is.
  for (const j of jobs) {
    j._earlierDone = jobs.some(o => key(o) === key(j) && o._try < j._try && o.state === "done");
  }

  // Per family. A Blu-ray is four times the data of a DVD, so one blended median
  // describes neither -- each row is compared against its own kind.
  const byKind = h.typical_by_kind || {};
  const typicalFor = (j) => byKind[j.disc_family] || h.typical_stages || {};
  const typical = h.typical_stages || {};
  const row = (j) => {
    // data-label carries each cell's column heading, so the narrow layout can put the
    // heading back beside the value when the table stops being a table.
    const size = j.state === "done" ? j.bytes_sent || j.bytes_ripped || j.bytes_total
                                    : j.bytes_ripped || 0;
    // Work done, not wall clock. `finished_at` moves every time a job is retried or
    // re-verified, so the span from start to finish on a job checked again an hour
    // later reads "1h" for thirteen seconds of work. The stages know better, and this
    // is then the same number the bar beside it is drawn from.
    const worked = (j.stages || []).reduce((a, st) => a + st.seconds, 0);
    const took = worked || (j.finished_at && j.started_at
                            ? j.finished_at - j.started_at : null);
    const find = esc([j.title, j.disc_label, j.year].filter(Boolean).join(" "));
    return `<tr class="hist ${j.state}" data-job="${j.id}" data-find="${find}">
      <td class="stat">${icon(j.state === "done" ? "circle-check"
                             : j.state === "cancelled" ? "ban"
                             : "triangle-exclamation")}</td>
      <td class="hist-name">
        <div class="hist-title">${esc((j.title || j.disc_label || "Unknown disc")
          + (j.title && j.year && j.kind !== "tv" ? ` (${j.year})` : ""))}${
          familyTag(j.disc_family)}</div>
        ${j.title && j.disc_label && j.title !== j.disc_label
          ? `<div class="hist-sub">${esc(j.disc_label)}</div>` : ""}
        ${j._sameError ? `<div class="hist-err muted">Same reason as above.</div>`
          : j.error ? `<div class="hist-err">${esc(j.error)}</div>` : ""}
      </td>
      <td class="num" data-label="Attempt">${j._tries > 1
        ? `<span title="This disc has been ripped ${j._tries} times. Every attempt is a row here.">${
            j._earlierDone ? "re-rip" : "attempt"} ${j._try} of ${j._tries}</span>`
        : `<span class="muted">1</span>`}</td>
      <td class="num" data-label="Size">${size ? esc(filesize(size)) : `<span class="muted">—</span>`}</td>
      <td class="num" data-label="Took">${took != null ? esc(duration(took)) : `<span class="muted">—</span>`}</td>
      <td class="hist-stages" data-label="Where the time went">${
        stageBar(j.stages, typicalFor(j))}</td>
      <td class="num" data-label="When"><span title="${esc(when(j.finished_at))}">${
        j.finished_at ? esc(ago(j.finished_at)) : `<span class="muted">didn't start</span>`}</span></td>
      <td class="act">${(() => {
        const btns = (j.retries || []).map(r =>
          `<button class="btn tiny" data-hretry="${j.id}" data-haction="${esc(r.action)}"
                   title="${esc(r.why)}">${icon(RETRY_ICON[r.action] || "arrows-rotate")
                   } ${esc(r.label)}</button>`).join("");
        // A row that worked doesn't need its checks offered at full size, ten times
        // down the page. They're one click away instead.
        return btns && j.state === "done"
          ? `<details class="row-menu"><summary class="icon-btn" aria-label="More for this rip"
               title="More">${icon("ellipsis")}</summary><div class="row-menu-pop">${btns}</div></details>`
          : btns;
      })()}</td>
    </tr>
    ${j.dest_path ? `<tr class="hist-dest ${j.state}" data-find="${find}"><td></td>
      <td colspan="7"><span class="muted">${icon("hard-drive")} ${esc(j.dest_path)}</span>${
        j.verified_mode && j.verified_mode !== "off"
          ? ` <span class="badge ok">${j.verified_mode === "deep" ? "full check passed"
                                                         : "size check passed"}</span>` : ""}</td></tr>` : ""}`;
  };

  return historyGrouped(jobs, key, row, h, typical, byKind);
};

/* ── History, grouped by disc ──
   One line per disc: how it ended most recently, when, and how many attempts. The
   attempts themselves -- with the stage bars, paths and retries -- open underneath,
   because on most days nobody needs them. */
const histOpen = new Set();
function historyGrouped(jobs, key, row, h, typical, byKind) {
  const groups = new Map();
  for (const j of jobs) {
    if (!groups.has(key(j))) groups.set(key(j), []);
    groups.get(key(j)).push(j);          // newest first, as the jobs come
  }
  const head_ = head("History", "Every rip, grouped by disc: what worked, what didn't, and where the time went.",
                     stageLegend(typical, h.stage_order, h.stage_labels));
  const items = [...groups.entries()].map(([k, list]) => {
    const latest = list[0];
    const good = list.find(x => x.state === "done");     // the newest success, if any
    const j = good || latest;
    // The question this line answers is "is it in my library?" -- how the last attempt
    // went comes second.
    const inLib = !!good;
    const checked = good && ({ deep: "full check passed", quick: "size check passed" })[good.verified_mode];
    const result = inLib
      ? ["In your library", latest.state !== "done"
          ? `last attempt ${latest.state === "cancelled" ? "cancelled" : "failed"}` : checked]
          .filter(Boolean).join(" · ")
      : latest.state === "cancelled" ? "Cancelled" : (latest.error || "Didn't finish");
    const state = inLib ? "done" : latest.state;
    const name = (j.title || pretty(j.disc_label) || "Unknown disc")
      + (j.title && j.year && j.kind !== "tv" ? ` (${j.year})` : "");
    const open = histOpen.has(k);
    const find = esc([j.title, j.disc_label, j.year].filter(Boolean).join(" "));
    // Retries only for attempts newer than the last success: anything older has been
    // superseded by a rip that worked.
    const lastGood = good ? list.indexOf(good) : list.length;
    // The first few attempts, every failure, and the rest of the successes folded.
    let shownDone = 0;
    const rows = list.map((x, i) => {
      const r = Object.assign({}, x, i > lastGood ? { retries: [] } : {},
        // The same failure twice running is said once.
        x.error && i > 0 && list[i - 1].error === x.error ? { _sameError: true } : {});
      const fold = x.state === "done" && ++shownDone > 3;
      return { html: row(r), fold };
    });
    const folded = rows.filter(r => r.fold).length;
    const body = rows.map(r => r.fold
      // A class, not the hidden attribute: search shows and hides rows by that.
      ? r.html.replace(/<tr class="hist /g, `<tr data-hgfold="${esc(k)}" class="hg-folded hist `)
      : r.html).join("");
    return `<div class="hg ${esc(state)}" data-find="${find}">
      <button class="hg-head" type="button" data-hg="${esc(k)}" aria-expanded="${open}"
              aria-controls="hg-${esc(k).replace(/[^a-z0-9]/gi, "-")}">
        <span class="hg-stat">${icon(state === "done" ? "circle-check" : state === "cancelled" ? "ban"
                                     : "triangle-exclamation")}</span>
        <span class="hg-name"><b>${esc(name)}</b> ${familyTag(j.disc_family)}
          <span class="hg-result">${esc(result)}</span>
          ${good && good.dest_path ? `<span class="hg-path">${icon("hard-drive")}<span class="hg-path-t">${esc(shortPath(good.dest_path, isFolderJob(good)))}</span></span>` : ""}</span>
        <span class="hg-meta">${(() => {
          // Successes and the rest counted apart: twelve good rips aren't twelve attempts.
          const ok = list.filter(x => x.state === "done").length;
          const failed = list.filter(x => x.state === "failed").length;
          const cancelled = list.filter(x => x.state === "cancelled").length;
          const parts = [];
          if (ok > 1) parts.push(`${ok} rips`);
          if (failed) parts.push(`${failed} failed`);
          if (cancelled) parts.push(`${cancelled} cancelled`);
          return parts.length ? `${parts.join(", ")} \u00b7 ` : "";
        })()}${latest.finished_at ? esc(ago(latest.finished_at)) : "didn't start"}</span>
        <span class="hg-chev">${icon("chevron-down")}</span>
      </button>
      <div class="hg-body" id="hg-${esc(k).replace(/[^a-z0-9]/gi, "-")}"${open ? "" : " hidden"}>
        ${good && good.dest_path ? `<div class="hg-full muted">${esc(good.dest_path)}${good.sha256
          ? `<br>SHA-256 ${esc(good.sha256)}` : ""}</div>` : ""}
        <table class="hist-table"><thead><tr>
          <th></th><th></th><th class="num">Attempt</th><th class="num">Size</th>
          <th class="num">Took</th><th>Where the time went</th><th class="num">When</th><th></th>
        </tr></thead><tbody>${body}</tbody></table>
        ${folded ? `<button class="btn sm hg-more" type="button" data-hgshow="${esc(k)}">Show ${folded} more successful rip${folded === 1 ? "" : "s"}</button>` : ""}
      </div>
    </div>`;
  }).join("");
  return `${head_}<div class="card hg-list">${items}</div>${stageNote(byKind)}`;
}

/* A proportional bar of the stages, because the interesting fact about a rip is not
   that it took thirty minutes -- it is that half of that was spent before a single
   byte was written, and no amount of staring at a total tells you that. */
function stageBar(stages, typical) {
  stages = (stages || []).filter(s => s.seconds > 0);
  if (!stages.length) return `<span class="muted">—</span>`;
  const total = stages.reduce((a, s) => a + s.seconds, 0);
  return `<div class="stagebar">${stages.map(s => {
    const med = typical[s.name] && typical[s.name].seconds;
    const vs = med ? ` — usually ${duration(med)}` : "";
    return `<i class="sg-${esc(s.name)}" style="flex:${s.seconds}"
       title="${esc(s.label)}: ${esc(duration(s.seconds))}${vs}${
         s.runs > 1 ? ` across ${s.runs} runs` : ""}"></i>`;
  }).join("")}</div>
  <div class="stagenums">${stages.map(s =>
    `<span><i class="sg-${esc(s.name)}"></i>${esc(duration(s.seconds))}</span>`).join("")}
  </div>`;
}

/* The key for the stage colours. It belongs in the header row rather than under the
   table: it is what makes every bar on the page readable, and a key you have to scroll
   past the data to reach is a key you look at once and then stop using.

   Doubling as "how long does this box normally take" -- the same medians the queue's
   counting timer is built from -- so it earns the space twice. */
const STAGE_SHORT = {
  identify: "Reading", decrypt: "Decrypting", save: "Saving",
  upload: "Uploading", verify: "Verifying",
};

function stageLegend(typical, order, labels) {
  order = order || Object.keys(STAGE_SHORT);
  return `<div class="stage-key" role="group" aria-label="Stage colours">
    ${order.map(k => {
      const t = typical[k];
      const full = (labels || {})[k] || k;
      return `<span class="sk${t ? "" : " unknown"}" title="${esc(full)}${
        t ? ` — usually ${duration(t.seconds)} here, over ${t.samples} rip${
              t.samples === 1 ? "" : "s"}`
          : " — no finished rips to average yet"}">
        <i class="sg-${esc(k)}"></i><b>${esc(STAGE_SHORT[k] || full)}</b>${
        t ? `<span class="sk-t">${esc(duration(t.seconds))}</span>` : ""}</span>`;
    }).join("")}
  </div>`;
}

/* The caveat that does not fit in a header chip, and the per-family numbers, which are
   the honest form of "how long does this take" -- a Blu-ray and a DVD are not the same
   job wearing different labels. */
function stageNote(byKind) {
  const kinds = Object.entries(byKind || {}).filter(([, v]) => Object.keys(v).length);
  const order = ["identify", "decrypt", "save", "upload", "verify"];
  return `
    ${kinds.length ? `<div class="card stage-key-full"><h2 class="h3">Typical here</h2>
      ${kinds.map(([k, v]) => `<div class="kind-row">
        ${familyTag(k)}
        <span class="kind-times">${order.filter(n => v[n]).map(n =>
          `<span><i class="sg-${esc(n)}"></i>${esc(duration(v[n].seconds))}
            <span class="muted">${v[n].samples}&times;</span></span>`).join("")}</span>
      </div>`).join("")}</div>` : ""}
    <p class="muted stage-note">${kinds.length
      ? `Medians over Riparr's own finished rips, kept separate per kind of disc —
         a Blu-ray is several times the data of a DVD, so one blended number would be
         wrong about both.`
      : `Riparr needs two finished rips <b>of the same kind of disc</b> before it can say
         what is normal. Until then the queue counts up rather than down.`}
      </p>
    <details class="stage-why"><summary>Why the estimate starts late</summary>
      <p class="muted">MakeMKV can't report progress while it scans the disc, so Riparr uses
      how long this machine took last time.</p></details>`;
}

function when(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString();
}

/* A date a person would say out loud: no seconds, no am/pm on something months old. */
function day(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleDateString([],
    { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

/* ── Discs: the shelf ──
   Every disc this box has seen, and the one page in the product with something worth
   looking at. The record was already here; the artwork was being fetched for the tray
   and thrown away the moment the disc came out. */
views.discs = async (highlight) => {
  const { discs } = await api.get("/api/discs");
  const hit = highlight ? discs.find(d => d.fingerprint === highlight) : null;
  if (!discs.length) {
    return `${head("Discs", "Your collection: every film, show and album Riparr has ripped.")}
      <div class="card"><div class="empty-state"><div class="big">${icon("compact-disc")}</div>
        <h2>No discs recorded</h2>
        <p>Once Riparr rips a disc it remembers it, so reinserting it is refused
           instead of costing you forty minutes — and <b>Rip again</b> is here for when
           you meant it.</p></div></div>`;
  }
  const nameOf = (d) => (d.title || pretty(d.label) || "Unknown disc")
    + (d.title && d.year && d.kind !== "tv" ? ` (${d.year})` : "");
  // The collection: one tile per film, show or album, however many discs of it there
  // are -- a DVD and a Blu-ray of Arrival are one film. History is where each attempt is.
  const groups = new Map();
  for (const d of discs) {
    const k = `${d.kind || "movie"}|${nameOf(d).toLowerCase()}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(d);
  }
  const KIND_WORD = { movie: "Films", tv: "TV", music: "Music" };
  const kinds = [...new Set(discs.map(d => d.kind || "movie"))];
  const only = kinds.includes(state.discsKind) ? state.discsKind : "";
  const discWord = (d) => d.label ? pretty(d.label) : (FAMILY[d.disc_family] || {}).label || "Disc";
  const card = (list) => {
    const d = list.find(x => highlight && x.fingerprint === highlight) || list[0];
    const name = nameOf(d);
    const me = list.some(x => highlight && x.fingerprint === highlight);
    const newest = Math.max(...list.map(x => x.ripped_at || 0));
    const families = [...new Set(list.map(x => x.disc_family).filter(Boolean))];
    const menu = list.map(x => `
        ${list.length > 1 ? `<div class="rip-menu-h">${esc(discWord(x))} ${familyTag(x.disc_family)}</div>` : ""}
        <button class="btn tiny" data-rerip="${esc(x.fingerprint)}"
                title="Put this disc back in the tray and read it again from the start.">Rip again</button>
        <button class="btn tiny quiet-danger" data-forget="${esc(x.fingerprint)}"
                title="Forget this disc, so the next time it goes in it is treated as new.">Forget</button>`).join("");
    return `<figure class="rip${me ? " dupe" : ""}"${me ? ` id="dupe-tile"` : ""}
                    data-kind="${esc(d.kind || "movie")}"${only && (d.kind || "movie") !== only ? " hidden" : ""}
                    ${d.art ? "" : `data-art="${esc(d.title || d.label || "")}"`}
                    data-find="${esc([name, ...list.map(x => x.label), d.year].filter(Boolean).join(" "))}">
      <div class="rip-art${d.art ? " has" : ""}${d.kind === "music" ? " square" : ""}"${d.art ? ` style="background-image:url('${esc(d.art)}')"` : ""}>
        <span class="rip-fallback">${icon("compact-disc")}</span>
        ${families.map(f => familyTag(f, "on-art")).join("")}
        ${!d.ripped_at ? `<span class="rip-flag" title="Seen, but never finished a verified rip">${
          icon("triangle-exclamation")}</span>` : ""}
      </div>
      <figcaption>
        <div class="rip-title" title="${esc(name)}">${esc(name)}</div>
        <div class="rip-meta">${list.length > 1 ? `${list.length} discs \u00b7 ` : ""}${newest ? esc(ago(newest))
                                            : `<span class="bad">never finished</span>`}</div>
      </figcaption>
      <div class="rip-acts">
        ${list.length === 1 ? `<button class="btn tiny" data-rerip="${esc(d.fingerprint)}"
                title="Put this disc back in the tray and read it again from the start.">Rip again</button>` : ""}
        <details class="row-menu"><summary class="btn tiny" aria-label="More for ${esc(name)}">${
          list.length > 1 ? "Discs\u2026" : "\u22ef"}</summary>
          <div class="row-menu-pop">${list.length > 1 ? menu : menu.replace(/<button class="btn tiny" data-rerip[\s\S]*?<\/button>/, "")}</div></details>
      </div>
    </figure>`;
  };
  const filter = kinds.length > 1 ? `<div class="kind-filter" role="group" aria-label="Show">
      ${["", ...["movie", "tv", "music"].filter(k => kinds.includes(k))].map(k =>
        `<button class="btn sm${only === k ? " on" : ""}" data-discs-kind="${k}"
                 aria-pressed="${only === k}">${k ? KIND_WORD[k] : "All"}</button>`).join("")}
    </div>` : "";
  // The banner is the sentence the box would say out loud. It names the film and the
  // date, because "you already have this" is only convincing with evidence, and it
  // points at the button rather than describing a menu path.
  const banner = hit ? `
    <div class="card dupe-note">
      <div class="dupe-ic">${icon("compact-disc")}</div>
      <div class="grow">
        <h2>You've already ripped ${esc(hit.title || pretty(hit.label) || "this disc")}</h2>
        <p>It went into your library ${esc(ago(hit.ripped_at))}${
          // The exact date earns its place only once "3 days ago" stops being an
          // answer. Next to "2 min ago" it is just a timestamp with seconds in it.
          hit.ripped_at && Date.now() / 1000 - hit.ripped_at > 86400
            ? ` — ${esc(day(hit.ripped_at))}` : ""}, so Riparr gave the disc straight
          back rather than spending another half hour on it.</p>
        <p class="muted">Meant it? <b>Rip again</b> on the highlighted tile pulls the tray
          back in and starts over.</p>
      </div>
      <button class="icon-btn" id="dupe-dismiss" title="Dismiss" aria-label="Dismiss">${icon("xmark")}</button>
    </div>` : "";
  return `${head("Discs", "Your collection: every film, show and album Riparr has ripped. Put a disc back in and it says you already have it.")}
    ${banner}
    ${filter}
    <div class="rips">${[...groups.values()].map(card).join("")}</div>`;
};

/* The same tidy-up the server does to a volume label, so ALL_CAPS_1999 does not sit
   under a poster shouting. */
function pretty(label) {
  if (!label) return "";
  return label.replace(/[_.]+/g, " ").replace(/\s+/g, " ").trim()
              .replace(/\b\w/g, c => c.toUpperCase());
}

/* Fill the posters in after the grid is on screen. Each lookup is cached server-side by
   normalised title, and a miss simply leaves the disc icon showing -- a film we cannot
   identify is a tile without a picture, never a broken image. */
async function paintRipArt() {
  const cards = $$(".rip[data-art]");
  for (const el of cards) {
    const label = el.dataset.art;
    if (!label || el.dataset.done) continue;
    el.dataset.done = "1";
    let hit;
    try { hit = await api.get(`/api/artwork?label=${encodeURIComponent(label)}`); }
    catch (e) { continue; }
    if (!hit || !hit.ok) continue;
    const art = el.querySelector(".rip-art");
    if (art) {
      art.style.backgroundImage = `url("${hit.image}")`;
      art.classList.add("has");
      art.title = hit.title;
    }
  }
}

/* ── settings ── */
/* Five pages, not Sonarr's twenty. Riparr has no indexers, no download clients, no
   quality profiles and no custom formats, so the settings surface stays something a
   person can read in one sitting.

   Each page says what it is for rather than repeating a slogan. The five subtitles
   used to be one line -- "Configure once. Anything that needs revisiting is a bug." --
   which told somebody who had just opened Connect for the first time nothing at all
   about what Connect was. A subtitle is the only sentence guaranteed to be read on a
   settings page, so it is worth spending on the page rather than on the product. */
const SETTINGS_TABS = [
  ["library", "Library",
   "Where finished rips are written, what they are called, and which share each kind "
   + "of disc goes to."],
  ["ripping", "Ripping",
   "What Riparr takes off a disc, how it gets to your library, and how thoroughly it "
   + "is checked afterwards."],
  ["makemkv", "MakeMKV",
   "The software that reads your discs: its key, its version, and whether its websites "
   + "are up."],
  ["connect", "Connect",
   "How Riparr reaches you when you are not looking at this page, and where finished "
   + "files are handed on."],
  ["general", "General",
   "The look of this interface, your password, and updates."],
];

views.settings = async (sub = "library") => {
  const s = state.settings = await api.get("/api/settings");
  const body = await (settingsPages[sub] || settingsPages.library)(s);
  const tab = SETTINGS_TABS.find(([k]) => k === sub) || SETTINGS_TABS[0];
  return `${head(tab[1], tab[2])}${body}`;
};

const settingsPages = {};

/* A naming template with its preset list and a preview of what it makes. The preview is
   rendered by the server, which is the only thing that knows the template language. */
function namingField(kind, label, key, value) {
  const presets = (state.naming && state.naming[kind]) || [];
  const current = presets.find(p => p.template === value);
  return `
    <label class="f"><span>${esc(label)}</span>
      <select data-naming-preset="${kind}">
        ${presets.map(p => `<option value="${esc(p.id)}" ${
          current && current.id === p.id ? "selected" : ""}>${esc(p.label)}</option>`).join("")}
        <option value="" ${current ? "" : "selected"}>Custom</option>
      </select></label>
    <label class="f"><span></span>
      <input data-set="${key}" data-naming="${kind}" value="${esc(value || "")}"
             spellcheck="false" autocomplete="off">
      <span class="help naming-preview" data-naming-preview="${kind}">&nbsp;</span></label>`;
}

/* Library — where finished rips go and what they are called.

   Two destinations, not one. Films and box sets do not usually belong in the same
   folder and often do not belong on the same machine: a NAS for films and a spare
   drive for television is an ordinary household. Each kind therefore names its own
   share *and* its own folder, which makes "two folders on one share" and "two
   different machines" the same control rather than two features. */
settingsPages.library = async (s) => {
  const [{ shares, destinations, library }, naming] = await Promise.all([
    api.get("/api/shares"), api.get("/api/naming").catch(() => null)]);
  state.naming = naming;
  state.libShares = shares;
  const dest = (kind) => destinations[kind] || {};
  const shareOf = (id) => shares.find(sh => sh.id === id);

  const row = (kind, label, folderKey, shareKey) => {
    const d = dest(kind);
    const sh = shareOf(d.share_id);
    const lib = (library || {})[kind] || {};
    return `
      <div class="dest" data-dest="${kind}">
        <div class="dest-h">${label}</div>
        <div class="dest-f">
          <label class="f"><span>Share</span>
            <select data-set="${shareKey}" data-dest-share="${kind}" data-int>
              ${shares.map(x => `<option value="${x.id}" ${
                x.id === d.share_id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}
            </select></label>
          <label class="f"><span>Folder</span>
            <input data-set="${folderKey}" data-dest-folder="${kind}"
                   value="${esc(s[folderKey] || "")}" placeholder="${
                     ({ tv: "TV", music: "Music" })[kind] || "Movies"}"></label>
        </div>
        <div class="dest-path" data-dest-path="${kind}">${
          sh ? esc(destPath(sh, s[folderKey])) : "no share configured"}</div>
        <div class="dest-note">${
          !sh ? ""
          : lib.mounted
            ? `${icon("circle-check", "ok")} Mounted at <code>${esc(lib.mount)}</code>,
               so <b>Straight to your library</b> works for this one.`
            // "Nothing is mounted" is said once for the page, below; a mount that's
            // there but unusable is this kind's own problem and is said here.
            : lib.problem && !/^Nothing is mounted/.test(lib.problem)
              ? `${icon("circle-info")} ${esc(lib.problem)}` : ""}
        </div>
      </div>`;
  };

  return `
    <div class="section"><h2>Shares
      <span class="grow"></span>
      <button class="btn" id="add-share">Add a share</button></h2>
      <div>
      ${shares.length ? `<div class="shares">${shares.map(sh => `
        <div class="rowitem share-row${sh.verified_at ? "" : " untested"}" id="share-${sh.id}">
          <div class="grow">
            <div class="t">${esc(sh.name)} ${
              sh.is_default ? '<span class="badge ok">default</span>' : ""} ${
              sh.verified_at ? "" : '<span class="badge warn">not tested</span>'}</div>
            <div class="s">//${esc(sh.host)}/${esc(sh.path)}
              · ${sh.username ? `as ${esc(sh.username)}` : "as a guest"}
              · ${sh.verified_at ? `tested ${ago(sh.verified_at)}` : "never tested"}</div>
            <div class="share-out test-out" aria-live="polite"></div>
            <div class="share-login" hidden>
              <div class="grid2">
                <label class="f"><span>Username</span><input class="sl-user" value="${esc(sh.username || "")}"
                       autocomplete="off"></label>
                <label class="f"><span>Password</span><input class="sl-pass" type="password"
                       placeholder="unchanged" autocomplete="new-password"></label>
              </div>
              <div class="btn-row"><button class="btn primary" data-login-save="${sh.id}">Sign in and test</button>
                <button class="btn" data-login-cancel>Cancel</button></div>
            </div>
          </div>
          <div class="share-acts">
            <button class="btn${sh.verified_at ? "" : " primary"}" data-test-share="${sh.id}">Test</button>
            <button class="btn" data-login-share="${sh.id}">Sign-in</button>
            <button class="btn quiet-danger" data-del-share="${sh.id}">Remove</button>
          </div>
        </div>`).join("")}</div>` : ""}
      <div id="share-add"></div>
    </div></div>

    <div class="section"><h2>Where things go</h2><div>
      <p class="muted">Each kind of disc has its own share and its own folder inside
        it. Use the same share for all of them to keep everything on one machine, or
        different shares to split them.</p>
      ${shares.length ? `<div class="dests">
          ${row("movie", "Films", "movie_folder", "movie_share_id")}
          ${row("tv", "Television", "tv_folder", "tv_share_id")}
          ${row("music", "Music", "music_folder", "music_share_id")}
        </div>
        ${Object.values(library || {}).some(l => l && !l.mounted) ? `<p class="muted dests-note">${
          icon("circle-info")} Rips are copied to these shares over the network, which works
          as it is. To write straight into your library instead, mount the share on the
          host at <code>${esc(
            (Object.values(library).find(l => l && !l.mounted) || {}).mount || "/srv/library")}</code>${
          ((state.status || {}).build || {}).install === "bare" ? "" : " inside Riparr's container"}.</p>` : ""}`
      : `<div class="empty-state"><div class="big">${icon("hard-drive")}</div>
          <h2>No share configured</h2>
          <p>Finished rips have nowhere to go until you add one above.</p></div>`}
    </div></div>

    <div class="section"><h2>Handoff</h2><div>
    <p class="muted">Riparr does not transcode. If you run something that does, write
      each rip where it watches for work instead of straight into your library.</p>
    <label class="f" style="margin-top:14px"><span>Watch folder</span>
      <input data-set="watch_folder" value="${esc(s.watch_folder)}" placeholder="/Media/_incoming">
      <span class="help">A path on your library share. Tdarr and Unmanic both work this
        way: they pick the file up, transcode it, and put the result wherever they are
        configured to. Leave this empty to write straight to the folders above.</span></label>
  </div></div>

    <div class="section"><h2>Film lookup (TMDb)</h2><div>
      <p class="muted">With a key from <a href="https://www.themoviedb.org/settings/api"
        target="_blank" rel="noopener">The Movie Database</a>, Riparr looks each film up:
        the disc's real title and year, its TMDb and IMDb IDs for the naming presets, and
        its poster. A match is only used when it's clear-cut. A free account gives you a
        key: either the "API Read Access Token" or the "API Key" works.</p>
      <label class="f"><span>TMDb key</span>
        <input data-set="tmdb_token" id="tmdb-token" value="${esc(s.tmdb_token || "")}"
               placeholder="Paste your API Read Access Token" autocomplete="off"
               spellcheck="false"></label>
      <div class="f"><span></span><div class="btn-row" style="margin:0">
        <button class="btn" id="tmdb-test">Test the key</button>
        <span class="test-out" id="tmdb-test-out"></span></div></div>
      <label class="f"><span>When TMDb isn't sure</span>
        <select data-set="tmdb_unsure">
          ${opt("label", "Keep Riparr's name, without IDs (default)", s.tmdb_unsure)}
          ${opt("ask", "Ask me, with TMDb's suggestions", s.tmdb_unsure)}
        </select>
        <span class="help">"Not sure" means TMDb has films by that name but none that
          match the title and year exactly, like a disc labelled just DUNE. Asking stops
          the queue until you answer; keeping the name doesn't.
          <br><br>${esc("This product uses the TMDB API but is not endorsed or certified by TMDB.")}</span></label>
    </div></div>

    <div class="section"><h2>Naming</h2><div>
      <p class="muted">A template is the folder and file a rip is saved as, relative to
        the folder above. It understands Radarr and Sonarr's naming syntax, so the
        schemes from <a href="https://trash-guides.info/Radarr/Radarr-recommended-naming-scheme/"
        target="_blank" rel="noopener">TRaSH Guides</a> are in the list and can be
        pasted in as they are.</p>
      ${namingField("movie", "Films", "movie_template", s.movie_template)}
      ${namingField("tv", "Episodes", "tv_template", s.tv_template)}
      <div class="f naming-albums"><span>Albums</span>
        <div class="grow"><code>Artist/Album (Year)/01 - Title.flac</code>
          <p class="muted naming-note">Audio CDs are named from MusicBrainz, the way Plex,
            Plexamp and Jellyfin file music, with the discs of a set as 1-01, 2-01\u2026 and
            a cover.jpg. This one isn't a template.</p></div></div>
      <div class="f"><span></span><span class="help">
        Tokens: ${((naming && naming.tokens) || []).map(t => `<code>${esc(t)}</code>`).join(" ")}.
        <br><br>Text inside the braces is only written when the value exists, Radarr's
        way: <code>{[Quality Full]}</code> gives <code>[Remux-1080p]</code> or nothing.
        The zeroes in <code>{Season:00}</code> set the padding, and a file holding two
        episodes expands <code>E{Episode:00}</code> to <code>E01-E02</code>, which is what
        Plex and Jellyfin read as a double.
        <br><br>The media tokens come from what MakeMKV reports about the disc, and the IDs
        from TMDb when there's a key above and a clear-cut match. Anything Riparr doesn't
        know is left out of the name rather than guessed.</span></div>
      <label class="f"><span>When a disc can't be identified</span>
        <select data-set="on_unknown_disc">
          ${opt("label", "Use the disc label (default)", s.on_unknown_disc)}
          ${opt("ask", "Ask me", s.on_unknown_disc)}
          ${opt("skip", "Skip it", s.on_unknown_disc)}
        </select>
        <span class="help">Only about the <em>name</em>. Which title gets ripped is
          <a href="#/settings/ripping">a separate setting</a>. Pick "Ask me" if these
          land straight in a library you browse; the disc label is the better answer
          if they land in a folder you tidy up later.</span></label>
    </div></div>${saveBar()}`;
};

/* The full path a destination adds up to. Shown under the two fields because "share"
   and "folder" are only meaningful together, and because seeing the whole thing is how
   somebody notices they have typed the share name into the folder box. */
function destPath(share, folder) {
  const parts = [String(share.path || "").replace(/^\/+|\/+$/g, ""),
                 String(folder || "").replace(/^\/+|\/+$/g, "")].filter(Boolean);
  return `//${share.host}/${parts.join("/")}`;
}

/* Full-disc backup's one moving part: the DVD half needs tools MakeMKV does not provide.
   Blu-ray and UHD need nothing extra, so this only speaks up about DVDs, and only when
   backup is the chosen mode -- a line about decryption libraries on a page where
   nobody asked for backups is noise. */
function backupToolsLine(t) {
  if (!t) return "";
  if (t.ready) return `<span class="test-out ok">DVD backups are ready.</span>`;
  return `<span class="test-out warn">DVD backups need libdvdcss, which hasn't been
    compiled yet. ${esc(t.message || "")} Until then, DVDs are ripped as film files and
    Blu-rays are backed up as normal.</span>`;
}

/* Ripping — what comes off the disc, and how it gets out. */
settingsPages.ripping = async (s) => {
  let tools = null;
  if (s.rip_mode === "backup") {
    try { tools = await api.get("/api/backup/tools"); } catch (e) { tools = null; }
  }
  return `
  <div class="section"><h2>What to rip</h2><div>
    <label class="f"><span>Titles</span>
      <select data-set="rip_mode">
        ${opt("main", "Main title (default)", s.rip_mode)}
        ${opt("all", "All titles", s.rip_mode)}
        ${opt("backup", "Full disc backup", s.rip_mode)}
      </select>
      <span class="help"><b>Full disc backup</b> keeps the whole disc instead of one
        film file: a <code>VIDEO_TS</code> or <code>BDMV</code> folder with the menus,
        extras and every audio track, decrypted, so it plays from the folder and can be
        made into an ISO later. It lands where the film would have, in
        <code>Movies/Film (Year)/</code>. Expect the size of the disc itself: around
        4–8 GB for a DVD, 25–50 GB for a Blu-ray.</span>
      <div class="btn-row" id="backup-tools">${backupToolsLine(tools)}</div></label>
    <label class="f"><span>Minimum title length (seconds)</span>
      <input type="number" data-set="min_title_seconds" value="${s.min_title_seconds}">
      <span class="help">Filters menus and logo stings.</span></label>
    <label class="f"><span>When Riparr can't tell which title is the film</span>
      <select data-set="on_ambiguous_title">
        ${opt("auto", "Use the most likely one (default)", s.on_ambiguous_title)}
        ${opt("ask", "Ask me", s.on_ambiguous_title)}
      </select>
      <span class="help">The longest title wins, and where two are the same length the
        smaller file wins. Riparr remembers what you pick for a disc, so a wrong guess
        is corrected once rather than every time.</span></label>
    <label class="f"><span>On a disc with a 3D version</span>
      <select data-set="title_3d">
        ${opt("2d", "Rip the 2D version (default)", s.title_3d)}
        ${opt("3d", "Rip the 3D version", s.title_3d)}
      </select>
      <span class="help">Both cuts are the same length, so length alone can't separate
        them. The 3D one is roughly twice the size and most players won't use it.</span></label>
  </div></div>

  <div class="section"><h2>Television</h2><div>
    ${sw("tv_detect", "Look for season discs", s.tv_detect,
        "A disc with six titles of the same length is a season disc, not a film with "
        + "five decoys. Turn this off if you only own films — every test that finds "
        + "television is a test that can be wrong about a film.")}
    <label class="f"><span>Before ripping a season</span>
      <select data-set="on_season_disc">
        ${opt("unsure", "Show me the plan when Riparr isn't sure (default)",
              s.on_season_disc)}
        ${opt("ask", "Always show me the plan", s.on_season_disc)}
        ${opt("auto", "Never — just rip it", s.on_season_disc)}
      </select>
      <span class="help">The default stops <b>once per season</b> — on the first disc,
        where one correction fixes every disc after it — and on any later disc whose
        episode order Riparr could not read off the disc itself.
        <br><br>Reading the order off the disc is reliable; most Blu-ray season discs
        carry a "play all" playlist that <em>is</em> the disc's record of its own
        episode order. What that can't settle is whether the numbering matches your
        episode guide: a few shows were released on disc in production order while
        every guide lists them in broadcast order. Riparr can't detect which kind a
        show is, so it shows you the first disc and gets on with the rest.
        <br><br>A disc with no season number always asks, whatever this says, because
        there is no answer to get on with.</span></label>
    ${sw("tv_metadata", "Look up episode names", s.tv_metadata,
        "Off gives you correctly numbered files with no names — Plex and Jellyfin "
        + "still match those perfectly, because they match on the numbers.")}
    <label class="f"><span>Episode names from</span>
      <select data-set="tv_source">
        ${opt("auto", "TMDb if there's a key, otherwise TVmaze (default)", s.tv_source)}
        ${opt("tmdb", "TMDb", s.tv_source)}
        ${opt("tvmaze", "TVmaze", s.tv_source)}
      </select>
      <span class="help">${state.status && state.status.tmdb
        ? "You have a TMDb key, so the default uses TMDb: the same IDs as your films, plus the TVDB ID that the TRaSH TV presets put in folder names."
        : "TVmaze needs no account. Add a TMDb key on Settings → Library and TMDb is used instead, with the TVDB ID that the TRaSH TV presets put in folder names."}
        A box set started under one keeps numbering correctly under the other.</span></label>
    <label class="f"><span>Specials go in</span>
      <select data-set="tv_specials_folder">
        ${opt("Season 00", "Season 00 (default)", s.tv_specials_folder)}
        ${opt("Specials", "Specials", s.tv_specials_folder)}
      </select>
      <span class="help">Both are read as season zero by Plex and Jellyfin. Set the
        season to 0 on the episode plan to file a disc here.</span></label>
  </div></div>

  <div class="section"><h2>Tracks
    <span class="grow"></span>
    <span class="badge">Biggest effect on file size</span></h2><div>
    <label class="f"><span>Audio languages</span>
      <input data-set="audio_languages" data-list value="${esc((s.audio_languages || []).join(", "))}">
      <span class="help">Comma separated ISO codes, e.g. eng, fra.</span></label>
    <label class="f"><span>Subtitle languages</span>
      <input data-set="subtitle_languages" data-list value="${esc((s.subtitle_languages || []).join(", "))}"></label>
    ${sw("keep_forced_subtitles", "Keep forced subtitles", s.keep_forced_subtitles,
        "The subtitles for alien or foreign dialogue. Almost always wanted.")}
    ${sw("keep_commentary", "Keep commentary tracks", s.keep_commentary,
        "Keeping every language and commentary can roughly double file size.")}
  </div></div>

  <div class="section"><h2>Transfer</h2><div>
    <label class="f"><span>Each rip goes</span>
      <select data-set="transfer_mode">
        ${opt("direct", "Straight to your library (recommended)", s.transfer_mode)}
        ${opt("auto", "Staged first, then sent", s.transfer_mode)}
        ${["burst", "stream"].includes(s.transfer_mode)
          // Older settings. Both stage the whole rip and then send it -- sending while
          // ripping needs a transport Riparr doesn't have yet -- so they're shown only
          // when one is already chosen, and named for what they do.
          ? opt(s.transfer_mode, "Staged first, then sent (older setting)", s.transfer_mode) : ""}
      </select>
      <span class="help"><b>Straight to your library</b> writes the film into your
        library as it comes off the disc, so nothing is staged. It needs the library
        bind-mounted into Riparr at <code>/srv/library</code>; without that, each rip
        stages by itself and is copied over SMB afterwards, rather than failing.
        <br><br>The trade: the rip needs the share for its whole length rather than
        only at the end, and there is one copy rather than two, so verification checks
        the size rather than hashing. <b>Staged first</b> is the answer if your NAS
        sleeps, or you want deep verification.</span></label>
    <label class="f"><span>After each rip</span>
      <select data-set="verify_mode">
        ${opt("quick", "Size check — compare the size", s.verify_mode)}
        ${s.transfer_mode === "direct" ? ""
          : opt("deep", "Full check — read every byte back", s.verify_mode)}
        ${opt("off", "Don't verify", s.verify_mode)}
      </select>
      <span class="help">Quick asks the share how big the file is and compares it with
        what was sent. It is nearly free and catches what actually goes wrong — a
        truncated transfer, a share that filled up, a write that was refused.
        ${s.transfer_mode === "direct"
          ? `<br><br><b>Deep checking isn't offered while rips go straight to your
             library</b>, because it works by reading the file back and comparing it
             with the original — and going direct leaves one copy, not two. Hashing it
             against itself would pass every time and prove nothing. Switch the mode
             above to <b>staged first</b> if you want it, and give the staging volume
             room for two copies of the largest title you rip.`
          : `<b>Deep</b> reads the entire file back and hashes it, so it also catches
             silent corruption of bytes that did arrive. That means downloading the
             whole rip again: it roughly doubles the time after a rip and needs
             <b>as much free staging space as the film itself</b>, on top of the
             rip. Worth it for an archive you will never re-rip; overkill for most.`}</span></label>
    ${sw("keep_local_copy", "Keep a copy in staging", s.keep_local_copy,
        "Off: once a rip is in your library and has passed its check, the staged copy is deleted. History keeps its size, checksum and where it went. On: the copy stays until the room is needed, so a problem on the share can be re-copied rather than re-ripped.")}
  </div></div>

  <div class="section"><h2>Already-ripped discs</h2><div>
    <p class="muted">Put a disc back in that Riparr has already finished and it gives it
      straight back rather than spending another half hour on it. If a browser is open
      it jumps to <b>Discs</b> and points at the film. If nobody is looking at one, this
      is how Riparr says so.</p>
    <label class="f" style="margin-top:14px"><span>Tell me with</span>
      <select data-set="duplicate_signal">
        ${opt("flash", "The drive's own light", s.duplicate_signal)}
        ${opt("tray", "The tray — open and close it", s.duplicate_signal)}
        ${opt("both", "Both", s.duplicate_signal)}
        ${opt("off", "Nothing — just eject", s.duplicate_signal)}
      </select>
      <span class="help">Nothing can address the light on the front of an optical
        drive — there is no such command, in any standard. What the light reports is
        the drive <i>reading</i>, so Riparr reads the disc in a rhythm: three short
        flashes, three times. It works on any drive and needs no vendor knowledge, and
        it is the gentler of the two. <b>The tray</b> is unmissable across a room and
        is machinery, so it does two cycles and stops.</span></label>
    <div class="btn-row">
      ${((state.status || {}).drives || []).length > 1 ? `<select id="signal-drive" aria-label="Which drive">
        ${state.status.drives.map(d => `<option value="${esc(d.device)}">${esc(driveName(d))} (${esc(d.device)})</option>`).join("")}
      </select>` : ""}
      <button class="btn" data-signal-test="flash">Try the light</button>
      <button class="btn" data-signal-test="tray">Try the tray</button>
      <span class="test-out" id="signal-out"></span></div>
    <p class="help">Put a disc in first — the light is blinked by reading one. Riparr
      cannot see the result, so this is the only way to find out whether your drive
      blinks the way you would want: watch it.</p>
  </div></div>${saveBar()}`;
};

/* Connect — how Riparr reaches you, and how finished files reach everything else.
   The notification half exists because a box whose entire promise is "walk away" had
   no way to tell you to come back: an LED covers the person walking past it and
   nothing covered the person at work.

   Four channels, each with its own setup story of six to ten steps in somebody else's
   application. Laid out flat, that is a page you scroll through four times to find the
   one you want, and every reader pays the cost of the three they will never use. So
   each channel is a row wearing its own mark, and opening one is what asks for the
   instructions. The mark matters more than it looks: people recognise Discord's face
   long before they read the word, and a channel that is already working says so on the
   mark itself rather than in a word at the other end of the row. */
const CHANNELS = [
  {key: "ntfy", name: "ntfy", icon: "ntfy",
   blurb: "Push straight to your phone. No account, no signup — the least work of the four."},
  {key: "discord", name: "Discord", icon: "discord",
   blurb: "Posts into a channel, and can @-mention you so your phone actually buzzes."},
  {key: "email", name: "Email", icon: "envelope",
   blurb: "Any SMTP server: your provider's, your NAS's, or your own."},
  {key: "webhook", name: "Webhook", icon: "circle-nodes",
   blurb: "POSTs JSON to anything that speaks HTTP — Home Assistant, n8n, a script of your own."},
];

/* One channel: the row you click, and the panel it opens.

   `summary` is what this channel is actually pointed at — the topic, the address, the
   host. A row that says only "set up" is a row you have to open to check, and the one
   thing somebody comes back to this page for is *which* account they wired it to. */
function channelRow(c, on, summary, body) {
  return `
  <div class="chan ${on ? "on" : ""}" data-chan="${c.key}">
    <button class="chan-head" type="button" aria-expanded="false" aria-controls="chan-${c.key}">
      <span class="chan-ic chan-${c.key}">${icon(c.icon)}${
        on ? `<span class="chan-tick" title="Set up">${icon("circle-check")}</span>` : ""}</span>
      <span class="chan-txt">
        <span class="chan-name">${esc(c.name)}</span>
        <span class="chan-blurb">${esc(on && summary ? summary : c.blurb)}</span>
      </span>
      <span class="chan-state">${on ? "Set up" : "Not set up"}</span>
      <span class="chan-caret">${icon("chevron-down")}</span>
    </button>
    <div class="chan-body" id="chan-${c.key}" hidden>${body}</div>
  </div>`;
}

settingsPages.connect = async (s) => {
  const n = await api.get("/api/notifications");
  const on = new Set(n.enabled || []);
  const ch = n.configured || {};
  const live = Object.values(ch).filter(Boolean).length;

  const summary = {
    ntfy: s.ntfy_topic
      ? `${(s.ntfy_server || "https://ntfy.sh").replace(/^https?:\/\//, "").replace(/\/$/, "")}/${s.ntfy_topic}`
      : "",
    discord: s.discord_webhook
      ? (s.discord_mention ? "A channel webhook, mentioning you" : "A channel webhook, posting quietly")
      : "",
    email: s.smtp_to ? `To ${s.smtp_to} via ${s.smtp_host}` : "",
    webhook: s.webhook_url ? s.webhook_url.replace(/^https?:\/\//, "").slice(0, 60) : "",
  };

  const bodies = {};

  bodies.ntfy = `
    <ol class="steps">
      <li><b>Install ntfy.</b> It is free and on both app stores, or you can leave
        <a href="https://ntfy.sh/app" target="_blank" rel="noopener">ntfy.sh/app</a>
        open in a browser tab.</li>
      <li><b>Invent a topic.</b> A topic is just a name, and there is no password on
        one — anyone who guesses it reads your notifications. So make it
        <i>unguessable</i> rather than memorable: <code>riparr-3f9a2b7c</code>, not
        <code>riparr</code>.</li>
      <li><b>Subscribe to it</b> in the app: <b>+</b> → type the same topic → Subscribe.</li>
      <li><b>Paste it below</b> and send a test. The test arrives on your phone or it
        does not, which is the whole of the answer.</li>
    </ol>
    <label class="f"><span>Topic</span>
      <input data-set="ntfy_topic" value="${esc(s.ntfy_topic || "")}" placeholder="riparr-3f9a2b7c">
      <span class="help">Must match what you subscribed to in the app, exactly.</span></label>
    <label class="f"><span>Server</span>
      <input data-set="ntfy_server" value="${esc(s.ntfy_server || "")}">
      <span class="help">Leave this alone unless you run your own ntfy — a self-hosted
        one on your NAS works and never leaves your network.</span></label>
    <label class="f"><span>Access token</span>
      <input data-set="ntfy_token" type="password" value="${esc(s.ntfy_token || "")}"
             placeholder="only for a private server">
      <span class="help">Public ntfy.sh topics need no token. A private server that
        requires sign-in does.</span></label>
    ${testRow("ntfy")}`;

  bodies.discord = `
    <p class="muted">A Discord webhook posts into a <b>channel</b>. If you want Riparr
      to tell <i>you</i> — a notification on your phone rather than a line in a channel
      somebody might read on Tuesday — make a server of one and have Riparr mention you
      in it. Both halves are below.</p>
    <ol class="steps">
      <li><b>Make somewhere for it to post.</b> In Discord, click <b>+</b> at the bottom
        of the server list → <b>Create My Own</b> → <b>For me and my friends</b>. Call it
        anything. Nobody else can see it. A channel there is a private feed, and Discord
        pushes it to your phone like any other.</li>
      <li><b>Make the webhook.</b> Hover the channel → the gear (<b>Edit Channel</b>) →
        <b>Integrations</b> → <b>Create Webhook</b> → <b>Copy Webhook URL</b>. That URL
        is the password: anyone holding it can post as Riparr, so treat it like one.</li>
      <li><b>Paste it below</b> and press Check. Riparr asks Discord whether the webhook
        is real before trusting it — a URL that got truncated on the way through a
        clipboard fails silently forever otherwise.</li>
      <li><b>Optional but the point:</b> turn on <b>Developer Mode</b>
        (User Settings → Advanced), then right-click your own name →
        <b>Copy User ID</b>, and paste that in "Mention me". Riparr will @-mention you,
        which is the thing that actually buzzes a phone.</li>
    </ol>
    <label class="f"><span>Webhook URL</span>
      <input data-set="discord_webhook" id="dc-url" value="${esc(s.discord_webhook || "")}"
             placeholder="https://discord.com/api/webhooks/…">
      <span class="help">Nothing is sent anywhere until this is filled in.</span></label>
    <div class="btn-row"><button class="btn" id="dc-check">Check this webhook</button>
      <span class="test-out" id="dc-out"></span></div>

    <label class="f"><span>Mention me</span>
      <input data-set="discord_mention" value="${esc(s.discord_mention || "")}"
             placeholder="your Discord user ID, e.g. 218411284957167616">
      <span class="help">A user ID pings you. Prefix a <b>role</b> ID with
        <code>&amp;</code> — <code>&amp;123…</code> — to ping a role instead, for a
        household that shares Riparr. Leave empty to post quietly.</span></label>

    <div class="dc-when">
      <div class="dc-when-l">Ping me for</div>
      <div class="notify-events">
        ${n.events.map(e => `
          <label class="switch"><input type="checkbox" data-set="discord_mention_events"
                  data-multi value="${esc(e.key)}"
                  ${(s.discord_mention_events || []).includes(e.key) ? "checked" : ""}>
            <span class="track"></span><span class="lbl">${esc(e.label)}</span></label>`).join("")}
      </div>
      <p class="help">Everything else still posts to the channel — it just does not
        make your phone light up. "A rip finished" is off by default for exactly that
        reason: it is good news, and good news can wait.</p>
    </div>
    ${testRow("discord")}`;

  bodies.email = `
    <ol class="steps">
      <li><b>Find your provider's outgoing (SMTP) server.</b> Gmail is
        <code>smtp.gmail.com</code>, Outlook <code>smtp.office365.com</code>, Fastmail
        <code>smtp.fastmail.com</code>. Your NAS almost certainly has one too.</li>
      <li><b>Make an app password.</b> Any account with two-factor turned on — which is
        all of them now — will reject your ordinary password here and give no useful
        reason. Google calls it an <i>App password</i>; most others use the same words.
        Use that, not the password you sign in with.</li>
      <li><b>Port 587 with STARTTLS</b> is the usual pairing. If your provider says port
        <b>465</b>, use it and turn STARTTLS <i>off</i>: 465 is encrypted from the first
        byte, and asking it to start again fails.</li>
      <li><b>From</b> normally has to be the same address you signed in as. Providers
        refuse to send mail claiming to be somebody else.</li>
    </ol>
    <div class="grid2">
      <label class="f"><span>SMTP server</span>
        <input data-set="smtp_host" value="${esc(s.smtp_host || "")}" placeholder="smtp.gmail.com"></label>
      <label class="f"><span>Port</span>
        <input data-set="smtp_port" type="number" value="${esc(String(s.smtp_port ?? 587))}"></label>
      <label class="f"><span>Username</span>
        <input data-set="smtp_username" value="${esc(s.smtp_username || "")}"></label>
      <label class="f"><span>Password</span>
        <input data-set="smtp_password" type="password" value="${esc(s.smtp_password || "")}"></label>
      <label class="f"><span>From</span>
        <input data-set="smtp_from" value="${esc(s.smtp_from || "")}" placeholder="riparr@example.com"></label>
      <label class="f"><span>To</span>
        <input data-set="smtp_to" value="${esc(s.smtp_to || "")}" placeholder="you@example.com"></label>
    </div>
    ${sw("smtp_tls", "Use STARTTLS", s.smtp_tls, "Leave on unless the port is 465, which is TLS from the start.")}
    ${testRow("email")}`;

  bodies.webhook = `
    <p class="muted">The general-purpose escape hatch. Every event is POSTed as JSON to
      one URL, so anything that can receive an HTTP request can act on it — a Home
      Assistant automation, an n8n flow, a shell script behind a tiny listener.</p>
    <ol class="steps">
      <li><b>Get a URL that accepts a POST.</b> In Home Assistant that is a webhook
        trigger; in n8n, a Webhook node; anywhere else, whatever you already use.</li>
      <li><b>Paste it below and send a test.</b> The body looks like this:
        <code class="block">{"event":"done","title":"Arthur Christmas",
"body":"Ripped and verified","hostname":"riparr"}</code>
        When a disc needs you, there's also <code>actions</code>: each has a
        <code>label</code>, and a <code>url</code> to POST to (an answer) or open.</li>
      <li><b>Events are the ones ticked at the top of this page.</b> <code>event</code>
        is one of <code>${n.events.map(e => e.key).join("</code>, <code>")}</code>.</li>
    </ol>
    <label class="f"><span>URL</span>
      <input data-set="webhook_url" value="${esc(s.webhook_url)}" placeholder="https://…">
      <span class="help">Must be <code>http://</code> or <code>https://</code>. A
        service on your own network is fine and is the common case.</span></label>
    ${testRow("webhook")}`;

  return `
  <div class="section"><h2>Channels
    <span class="grow"></span>
    <span class="badge ${live ? "ok" : "warn"}">${
      live ? `${live} of ${CHANNELS.length} set up` : "none set up"}</span></h2><div>
    <p class="muted">Pick whichever you already use — one is enough, and setting up two
      is only worth it if you want a copy somewhere permanent. Open a channel to see
      what it needs. ${live ? "A tick on the mark means Riparr has what it needs to "
        + "send; the test button is how you find out whether it arrives."
      : "Nothing is set up yet, so Riparr currently has no way to reach you when you "
        + "are not on this page."}</p>
    <div class="channels">
      ${CHANNELS.map(c => channelRow(c, !!ch[c.key], summary[c.key], bodies[c.key])).join("")}
    </div>
  </div></div>

  <div class="section"><h2>Tell me when</h2><div>
    <p class="muted">Riparr sends every event ticked here to every channel set up
      above.${live ? "" : " None is set up yet, so for now nothing is sent anywhere."}</p>
    <div class="notify-events">
      ${n.events.map(e => `
        <label class="switch"><input type="checkbox" data-set="notify_events" data-multi
                value="${esc(e.key)}" ${on.has(e.key) ? "checked" : ""}>
          <span class="track"></span><span class="lbl">${esc(e.label)}</span></label>`).join("")}
    </div>
  </div></div>

  <div class="section"><h2>Answer from your phone</h2><div>
    <p class="muted">When a disc stops to ask which film, show or album it is, the
      notification has buttons with Riparr's best guesses. In ntfy a button answers straight away;
      Discord and email get links to a page with the button on it. Either way, your
      phone has to be able to reach Riparr.</p>
    <label class="f" style="margin-top:14px"><span>Riparr's address</span>
      <input data-set="public_url" value="${esc(s.public_url || "")}"
             placeholder="${esc(n.seen_url || "http://192.168.1.10:8080")}">
      <span class="help">${n.seen_url
        ? `Empty means the address you signed in at, <code>${esc(n.seen_url)}</code>.`
        : "Empty means the address you next open Riparr at."} Away from home, the buttons
        only work if this address reaches Riparr from there too, through a VPN or a
        reverse proxy.</span></label>
    ${live && /^https?:\/\/(localhost|127\.|\[::1\])/.test(s.public_url || n.seen_url || "")
      ? `<div class="alert warn"><b>Your phone can't reach this address.</b> <code>${esc(
          s.public_url || n.seen_url)}</code> only means "this computer". Put in the address
          you'd type on your phone, like <code>http://192.168.1.10:9797</code>.</div>` : ""}
  </div></div>
${saveBar()}`;
};

/* ── is MakeMKV's own infrastructure up? ──
   Not decoration. makemkv.com has been down for weeks, and the free key is published
   on the *forum*, which is a different host and is usually fine. "The site is down but
   the forum is up" is the difference between "you are stuck" and "go here, copy the
   key, paste it above" -- so the two are tracked separately and each says what its
   being down actually costs the person reading.

   The panel draws before the answer exists. It used to draw *after*, which meant
   opening General waited on two of somebody else's web servers -- and a host that is
   down burns the whole timeout, so the sidebar link looked broken for ten seconds and
   people clicked it again. Now the page appears immediately, this says "checking", and
   the answer arrives when it arrives. */
function sitesPanel(mk) {
  return `
  <div class="section" id="sites-panel"><h2>MakeMKV's website
    <span class="grow"></span>
    ${sitesBadge(mk.sites, mk.sites_checking)}</h2><div>
    <p class="muted">Riparr checks these because they are how MakeMKV gets installed and
      how its free key gets renewed. Neither affects a copy that is already working.</p>
    <div id="sites-inner">${sitesBody(mk.sites, mk.sites_checking, mk.key_topic)}</div>
    <div class="btn-row"><button class="btn" id="sites-recheck">Check again</button>
      <span class="test-out" id="sites-out"></span></div>
  </div></div>`;
}

function sitesBadge(sites, checking) {
  if (!sites || !sites.length)
    return `<span class="badge" id="sites-badge">${checking ? "checking…" : "not checked"}</span>`;
  const down = sites.filter(x => !x.up).length;
  return `<span class="badge ${down ? "warn" : "ok"}" id="sites-badge">${
    down === 0 ? "both reachable"
    : down === sites.length ? "both unreachable"
    : `${down} unreachable`}</span>`;
}

function sitesBody(sites, checking, keyTopic) {
  if (!sites || !sites.length)
    return `<div class="sites-wait">${checking
      ? `<span class="spin"></span>Asking makemkv.com and its forum whether they are
         answering. A host that is down takes a few seconds to admit it.`
      : `Nothing checked yet.`}</div>`;
  return `
    <div class="sites">
      ${sites.map(x => `
        <div class="site ${x.up ? "up" : "down"}">
          <span class="site-dot">${icon(x.up ? "circle-check" : "circle-exclamation")}</span>
          <div class="grow">
            <div class="site-name"><a href="${esc(x.url)}" target="_blank" rel="noopener">${
              esc(x.name)}</a>
              <span class="site-state">${x.up
                ? (x.note ? esc(x.note) : `answering in ${x.ms} ms`)
                : "not answering"}</span></div>
            <div class="site-why">${esc(x.why)}</div>
            ${!x.up && x.key === "site" ? `
              <div class="site-do">${icon("circle-info")} <span>An installed MakeMKV
                keeps working — this only stops a <b>rebuild</b> of the image from downloading it
                (the build falls back to mirrors).
                If you need a key, the forum below is a separate machine and is usually
                still up.</span></div>` : ""}
            ${!x.up && x.key === "forum" ? `
              <div class="site-do">${icon("circle-info")} <span>This is where the free
                key lives. If it is down and your key has lapsed, Blu-ray decryption
                will stop until it comes back. DVDs are unaffected.</span></div>` : ""}
          </div>
          ${x.key === "forum" && x.up ? `<a class="btn" href="${esc(keyTopic)}"
             target="_blank" rel="noopener">Get the current key</a>` : ""}
        </div>`).join("")}
    </div>`;
}

/* Replace the panel's contents in place rather than re-rendering the page. General
   holds a key field and a password field; blowing the page away underneath somebody
   who is halfway through typing one is not an acceptable price for a status dot. */
function paintSites(r, keyTopic) {
  const inner = $("#sites-inner"), badge = $("#sites-badge");
  if (!inner) return false;
  inner.innerHTML = sitesBody(r.sites, r.checking, keyTopic);
  if (badge) badge.outerHTML = sitesBadge(r.sites, r.checking);
  return true;
}

/* Poll until the probe finishes. Bounded: after a minute something is wrong with the
   probe itself, and a page that polls forever is a page that keeps a dead box busy. */
async function followSites(keyTopic) {
  for (let i = 0; i < 20; i++) {
    await new Promise(r => setTimeout(r, 1500));
    if (!$("#sites-inner")) return;            // navigated away
    let r;
    try { r = await api.get("/api/makemkv/sites"); } catch (e) { return; }
    if (!paintSites(r, keyTopic)) return;
    if (!r.checking) return;
  }
}

/* Save first, then send. A test button that tests the values already stored rather
   than the ones on screen answers a question nobody asked. */
function testRow(channel) {
  return `<div class="btn-row"><button class="btn" data-test-notify="${channel}">
    Save and send a test</button><span class="test-out" id="test-${channel}"></span></div>`;
}

settingsPages.makemkv = async (s) => {
  const mk = await api.get("/api/makemkv");
  const st = mk.status;
  state.mkKeyTopic = mk.key_topic;
  const expiringSoon = st.days_left != null && st.days_left < 8;
  return `
    <div class="section"><h2>MakeMKV
      <span class="grow"></span>
      <span class="badge ${!st.installed ? "bad" : expiringSoon ? "warn" : "ok"}">${
        !st.installed ? "Not installed"
        : st.days_left != null ? `${st.days_left} days left` : "Installed"}</span></h2>
      <div>
      ${mkUpgradeBlock(mk)}
      ${st.installed ? "" : `
        <div class="alert bad" style="margin-bottom:14px"><b>MakeMKV isn't installed.</b>
          ${esc(mk.install_hint || "")}
          <a href="${esc(mk.eula_url)}" target="_blank" rel="noopener">Read its licence</a>.</div>`}
      <label class="f" style="margin-top:${st.installed ? 0 : 16}px"><span>Key</span>
        <input data-set="makemkv_key" id="mk-key-input" value="${esc(s.makemkv_key)}" placeholder="Beta or purchased key">
        <span class="help">MakeMKV is free while it is in beta, behind a key GuinpinSoft
          publishes on the forum. ${esc((mk.key_advice || {}).note || "")}
          ${mk.shop_open === false
            ? `GuinpinSoft isn't selling licences at the moment and asks everyone to use
               the beta key until they are.`
            : `<a href="${esc(mk.buy_url)}" target="_blank" rel="noopener">Buying a licence</a>
               supports the people who make it, and a bought key never runs out.`}</span></label>
      <div class="f"><span></span><div class="grow" id="mk-key-offer"></div></div>
      ${sw("auto_renew_beta_key", "Renew the beta key automatically", s.auto_renew_beta_key !== false,
          "When the free beta key runs out, put in the new one GuinpinSoft publishes. "
          + "A bought key is never changed.")}
    </div></div>

    ${sitesPanel(mk)}
    ${saveBar()}`;
};

settingsPages.general = async (s) => {
  const themes = ["servarr", "organizr", "dark", "nord", "dracula", "plex",
                  "space-gray", "aquamarine", "hotline", "hotpink", "maroon", "overseerr", "win98"];
  const themeName = { win98: "Windows 98" };
  return `
    <div class="section"><h2>Appearance</h2><div>
      <p class="muted">Riparr uses the theme.park variable set, so a theme you already run
        on your *arr stack applies here too. Windows 98 is Riparr's own.</p>
      <label class="f" style="margin-top:14px"><span>Theme</span>
        <select id="theme-pick">${themes.map(t =>
          `<option value="${t}" ${s.theme === t ? "selected" : ""}>${themeName[t] || t}</option>`).join("")}</select>
      </label>

    </div></div>

    <div class="section"><h2>Password</h2><div>
      <label class="f"><span>Current password</span><input type="password" id="pw-cur"></label>
      <label class="f"><span>New password</span><input type="password" id="pw-new"></label>
      <label class="f"><span>Confirm new password</span><input type="password" id="pw-new2"></label>
      <div id="pw-res"></div>
      <div class="btn-row"><button class="btn" id="pw-go">Change password</button></div>
    </div></div>

    <div class="section"><h2>Updates</h2><div>
      ${sw("auto_check_updates", "Check for updates automatically", s.auto_check_updates,
          "Checks this fork's GitHub releases every few hours and tells you when there is a new one. Updating is pulling a new image.")}
      <div class="btn-row"><a class="btn" href="#/system/updates">Open updates</a></div>
    </div></div>${saveBar()}`;
};

/* ── system ──────────────────────────────────────────────────────────────────
   Six pages in Prowlarr's order. The shape is copied deliberately: full-width
   sections stacked down the page, a 21px heading with a rule under it, a toolbar of
   icon-over-label buttons where a page has actions, and tables at 14px with bold
   sentence-case headers. The *arrs put nothing side by side here and neither do we. */
const SYSTEM_TABS = [
  ["status",  "Status", "Whether Riparr is ready to rip, and what it's running on."],
  ["tasks",   "Tasks", "What Riparr does on a schedule, and when each last ran."],
  ["backup",  "Backup", "Copies of Riparr's settings and history, to restore from."],
  ["updates", "Updates", "Which version of Riparr and MakeMKV you're on."],
  ["events",  "Events", "What Riparr has been doing, newest first."],
  ["logs",    "Log Files", "The full log, live, and to download for a bug report."],
];

views.system = async (sub = "status") => {
  const body = await (systemPages[sub] || systemPages.status)();
  const tab = SYSTEM_TABS.find(([k]) => k === sub) || SYSTEM_TABS[0];
  return `${head(tab[1], tab[2])}${body}`;
};

const systemPages = {};

/* The key, said one way everywhere it is shown. */
function keyPhrase(m) {
  if (!m || !m.installed) return "MakeMKV isn't installed";
  if (m.key_type === "purchased") return "Bought \u2014 never runs out";
  if (!m.key_type) return "None entered";
  if (m.key_stale) return "Beta \u2014 a newer key has been published";
  if (m.days_left != null && m.days_left <= 0) return "Beta \u2014 expired";
  return m.key_expires ? `Beta \u2014 works until ${m.key_expires} (${m.days_left} days)` : "Beta";
}

/* ── Status ── */
systemPages.status = async () => {
  const st = await api.get("/api/status");
  state.status = st;
  const sys = st.system, m = st.makemkv, s = st.storage;

  // The full checklist lives here now, every row whether or not it passes -- the queue
  // only says how many need attention and links to this.
  const checks = (st.autorip || {}).checks || [];
  const health = healthMessages(st);
  const healthRows = checks.map(c => `<tr class="chk ${esc(c.state)}">
        <td class="stat">${icon(CHECK_ICON[c.state] || "circle-info",
                                c.state === "fail" ? "bad" : c.state === "warn" ? "warn" : "ok")}</td>
        <td><b>${esc(c.what)}</b><div class="muted">${esc(c.detail)}${
          c.state !== "ok" && c.why ? ` \u2014 ${esc(c.why)}` : ""}</div></td>
        <td class="act">${c.state !== "ok" && c.where
          ? `<a class="btn sm" href="${esc(c.where)}">Fix</a>` : ""}</td></tr>`).join("")
    + health.map(h => `<tr>
        <td class="stat">${icon(h.level === "bad" ? "circle-exclamation" : "triangle-exclamation",
                                h.level === "bad" ? "bad" : "warn")}</td>
        <td>${h.message}</td>
        <td class="act">${h.href
          ? `<a class="btn sm" href="${h.href}">${esc(h.action || "Fix")}</a>` : ""}</td></tr>`).join("");

  return `
    ${sys.mock ? `<div class="alert warn"><b>Development mode.</b>
      This process isn't running on Linux (or RIPARR_MOCK is set), so system, drive
      and share readings are simulated.</div>` : ""}

    <div class="section"><h2>Health</h2>
      <table class="health-table"><tbody>${healthRows}</tbody></table>
      <div class="btn-row"><button class="btn sm" data-task="health">${icon("arrows-rotate")} Check now</button>
        <span class="muted" style="font-size:13px">These run every six hours and whenever this
        page opens. Anything logged along the way is on <a href="#/system/events">Events</a>.</span></div>
    </div>

    <div class="section"><h2>About</h2>
      <div class="kv">
        <div class="k">Version</div><div class="v">${esc(st.version)} ${channelTag(st.build)}</div>
        <div class="k">Hostname</div><div class="v">${esc(st.hostname)}</div>
        <div class="k">Model</div><div class="v">${esc(sys.model)}</div>
        <div class="k">Operating system</div><div class="v">${esc(sys.os)}</div>
        <div class="k">Kernel</div><div class="v">${esc(sys.kernel || "—")}</div>
        <div class="k">Mode</div><div class="v">${sys.mock ? "Development (simulated)" : "Live hardware"}</div>
        <div class="k">Memory</div><div class="v">${sys.memory_used_mb} of ${sys.memory_total_mb} MB</div>
        ${sys.cpu_temp_c != null ? `<div class="k">Temperature</div><div class="v">${sys.cpu_temp_c} °C</div>` : ""}
        <div class="k">Uptime</div><div class="v">${uptime(sys.uptime_seconds)}</div>
      </div>
    </div>

    <div class="section"><h2>Storage</h2>
      <div class="kv">
        <div class="k">Capacity</div><div class="v">${capacityPhrase(s)}</div>
        <div class="k">Staging path</div><div class="v">${esc(s.path || "—")}
          ${s.dedicated === false ? '<span class="badge bad">shared with root</span>' : ""}</div>
        <div class="k">Used</div><div class="v">${filesize(s.used_bytes)}
          of ${filesize(s.total_bytes)}</div>
      </div>
      <div class="bar" style="margin:4px 0 8px"><i style="width:${pct(s.used_bytes, s.total_bytes)}%"></i></div>
      <p class="muted" style="font-size:13px">Buffer, not permanent storage — files
        leave as they're written.</p>
      ${s.dedicated === false ? `<div class="alert bad"><b>No staging volume.</b>
        The staging folder doesn't exist, so rips share the container's own filesystem.
        Mount a volume at the staging path.</div>` : ""}
    </div>

    <div class="section"><h2>Drives</h2>
      <div class="kv">
        ${m.sdf_stop ? `<div class="k">Drive data</div><div class="v">Skipped for this drive, to
          avoid a MakeMKV bug that hangs fetching it. DVDs and Blu-rays rip as usual; 4K
          LibreDrive features are off. <span class="muted">(<code>sdf_Stop</code> in
          MakeMKV's settings)</span></div>` : ""}
        <div class="k">${(st.drives || []).length > 1 ? "Drives" : "Drive"}</div><div class="v">${(st.drives && st.drives.length)
          ? st.drives.map(d => `${esc(driveName(d))} <span class="muted">· ${esc(d.reads || "capability unknown")}</span>`).join("<br>")
          : `<span class="muted">${esc((st.optical && st.optical.summary) || "no drive detected")}</span>`}</div>
        <div class="k">4K UHD</div><div class="v">${(() => {
          const d = (st.drives || [])[0];
          if (!d) return `<span class="muted">—</span>`;
          if (!d.reads_bluray) return `<span class="muted">Not applicable — this is a DVD drive</span>`;
          if (d.libredrive === "enabled") return `Yes — MakeMKV reports LibreDrive is active`;
          if (d.libredrive === "no") return `<span class="muted">No — MakeMKV can't get underneath this drive's firmware</span>`;
          if (d.uhd === "yes") return `Expected to work — this drive is on Riparr's list`;
          if (d.uhd === "firmware") return `<span class="muted">Depends on firmware — check MakeMKV's LibreDrive list</span>`;
          return `<span class="muted">Unconfirmed — 4K needs a specific drive, and this one isn't on Riparr's list</span>`;
        })()}</div>
      </div>
    </div>

    <div class="section"><h2>More Info</h2>
      <div class="kv">
        <div class="k">Source</div><div class="v">
          <a href="https://github.com/ziggy46/riparr-server" target="_blank" rel="noopener">github.com/ziggy46/riparr-server</a></div>
        <div class="k">Issues</div><div class="v">
          <a href="https://github.com/ziggy46/riparr-server/issues" target="_blank" rel="noopener">github.com/ziggy46/riparr-server/issues</a></div>
        <div class="k">Based on</div><div class="v">
          <a href="https://github.com/jackharvest/riparr" target="_blank" rel="noopener">github.com/jackharvest/riparr</a></div>
        <div class="k">MakeMKV</div><div class="v">
          <a href="https://www.makemkv.com/forum/" target="_blank" rel="noopener">makemkv.com/forum</a></div>
        <div class="k">Film data</div><div class="v">
          <a href="https://www.themoviedb.org/" target="_blank" rel="noopener">The Movie Database (TMDB)</a>
          <span class="muted">· This product uses the TMDB API but is not endorsed or certified by TMDB.</span></div>
      </div>
    </div>`;
};

/* Health is derived here rather than server-side because every message needs a link to
   the screen that fixes it, and only the client knows the routes. */
function healthMessages(st) {
  const out = [];

  /* The clock goes first, because it invalidates several of the messages below it:
     every "N days left" and "3 hours ago" in the interface is a subtraction against it.
     A container uses the host's clock, so this is the host's time being wrong. */
  const clk = st.clock;
  if (clk && !clk.plausible)
    out.push({ level: "bad", message: `The system clock reads ${
      new Date(clk.now * 1000).toLocaleString()}, which can't be right. Dates and key
      expiry are meaningless until it syncs — check the host's time settings.`,
      action: "Details" });
  else if (clk && clk.synced === false)
    out.push({ level: "warn", message: "The clock hasn't synchronised with a time "
      + "server yet, so dates may be slightly out." });

  // MakeMKV, its key, the drive and the share are on the Auto Rip checklist, which
  // problems() and System → Status read directly. Listing them here as well is how
  // four screens came to give four different answers about the same key.

  if (st.storage.dedicated === false)
    out.push({ level: "warn", message: "The staging folder doesn't exist, so rips are staged on the container's own filesystem. Mount a volume at the staging path." });

  if (st.storage.mode === "degraded")
    out.push({ level: "warn", message: "Not enough free space to rip safely." });

  return out;
}

/* ── Tasks ── */
systemPages.tasks = async () => {
  const t = await api.get("/api/system/tasks");
  const rows = t.scheduled.map(s => `<tr>
      <td class="st-name">${esc(s.label)}</td>
      <td data-label="Every">${interval(s.interval)}</td>
      <td data-label="Last run">${since(s.last_execution)}</td>
      <td data-label="Took">${s.last_duration == null ? "—" : hms(s.last_duration)}</td>
      <td data-label="Next">${since(s.next_execution)}</td>
      <td class="act"><button class="icon-btn" data-task="${esc(s.name)}"
          title="Run now" aria-label="Run ${esc(s.label)} now">${icon("arrows-rotate")}</button></td>
    </tr>`).join("");

  const queue = t.queue.length ? t.queue.map(q => `<tr>
      <td class="stat">${q.error ? icon("circle-exclamation", "bad")
                                 : q.ended_at ? icon("check", "ok") : icon("clock")}</td>
      <td class="st-name">${esc(q.label)}</td>
      <td data-label="Queued">${since(q.queued_at)}</td>
      <td data-label="Started">${since(q.started_at)}</td>
      <td data-label="Ended">${since(q.ended_at)}</td>
      <td data-label="Took">${q.ended_at && q.started_at ? hms(q.ended_at - q.started_at) : "—"}</td>
      <td>${q.error ? `<span class="badge bad">${esc(q.error)}</span>` : ""}</td>
    </tr>`).join("")
    : `<tr><td colspan="7" class="muted">Nothing has run yet.</td></tr>`;

  return `
    <div class="section"><h2>Scheduled</h2>
      <table class="stack-table">
        <thead><tr><th>Name</th><th>Interval</th><th>Last Execution</th>
          <th>Last Duration</th><th>Next Execution</th><th class="act"></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="section"><h2>Recent runs</h2>
      <table class="stack-table">
        <thead><tr><th class="stat"></th><th>Name</th><th>Queued</th><th>Started</th>
          <th>Ended</th><th>Duration</th><th></th></tr></thead>
        <tbody>${queue}</tbody>
      </table>
    </div>`;
};

/* ── Backup ── */
systemPages.backup = async () => {
  const b = await api.get("/api/system/backups");
  const rows = b.backups.length ? b.backups.map(x => `<tr>
      <td class="stat">${icon(x.kind === "scheduled" ? "clock" : "file-zipper")}</td>
      <td class="st-name"><a href="/api/system/backups/${encodeURIComponent(x.name)}">${esc(x.name)}</a></td>
      <td data-label="Size">${filesize(x.size)}</td>
      <td data-label="Made">${stamp(x.modified)}</td>
      <td class="act">
        <button class="icon-btn" data-restore="${esc(x.name)}" title="Restore"
                aria-label="Restore ${esc(x.name)}">${icon("clock-rotate-left")}</button>
        <button class="icon-btn" data-delbackup="${esc(x.name)}" title="Delete"
                aria-label="Delete ${esc(x.name)}">${icon("trash-can")}</button>
      </td></tr>`).join("")
    : `<tr><td colspan="5" class="muted">No backups yet.</td></tr>`;

  return `
    <div class="toolbar">
      <button class="tool" id="bk-now"><span class="ti">${icon("file-zipper")}</span>Back up</button>
      <button class="tool" id="bk-upload"><span class="ti">${icon("upload")}</span>Restore</button>
      <input type="file" id="bk-file" accept=".zip,application/zip,.json,application/json" class="hidden">
    </div>
    <div class="alert">Backups are written to <code>${esc(b.path)}</code> and hold your
      settings, shares and disc history — everything that is not re-derivable. A backup
      runs on its own every seven days and the last ${b.keep} are kept.
      <br>Share passwords are deliberately left out, so a restore asks for them again.</div>
    <div class="section"><h2>Backups</h2>
      <table class="stack-table">
        <thead><tr><th class="stat"></th><th>Name</th><th>Size</th><th>Time</th>
          <th class="act"></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
};

/* ── Updates ── */
/* Just enough Markdown for release notes: headings, paragraphs, lists, fenced code,
   inline code, bold and links. Escaped first, so nothing in the notes becomes markup
   it didn't ask for. */
function markdown(src) {
  const inline = (t) => esc(t)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
             (m, text, url) => `<a href="${url}" target="_blank" rel="noopener">${text}</a>`);
  const out = [];
  let para = [], list = null, code = null;
  const flush = () => {
    if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; }
    if (list) { out.push(`<${list.tag}>${list.items.map(i => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; }
  };
  for (const raw of String(src || "").replace(/<!--[\s\S]*?-->/g, "").split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (code !== null) {
      if (/^\s*```/.test(line)) { out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`); code = null; }
      else code.push(line.replace(/^ {0,3}/, ""));
      continue;
    }
    if (/^\s*```/.test(line)) { flush(); code = []; continue; }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    // Under the page's h2: "##" is h3, so no heading level is skipped.
    if (h) { flush(); const n = Math.min(6, h[1].length + 1); out.push(`<h${n}>${inline(h[2])}</h${n}>`); continue; }
    const li = line.match(/^\s*(?:[-*]|(\d+)\.)\s+(.*)$/);
    if (li) {
      if (para.length) flush();
      const tag = li[1] ? "ol" : "ul";
      if (!list || list.tag !== tag) { flush(); list = { tag, items: [] }; }
      list.items.push(li[2]);
      continue;
    }
    if (!line.trim()) { flush(); continue; }
    if (list && /^\s+/.test(raw)) { list.items[list.items.length - 1] += " " + line.trim(); continue; }
    if (list) flush();
    para.push(line.trim());
  }
  if (code !== null) out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
  flush();
  return out.join("");
}

function newerVersion(a, b) {
  const n = (v) => String(v || "").replace(/^v/, "").split(/[.-]/).map(x => parseInt(x, 10) || 0);
  const x = n(a), y = n(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  }
  return false;
}

systemPages.updates = async () => {
  const [u, mk] = await Promise.all([api.get("/api/update"),
                                      api.get("/api/makemkv").catch(() => null)]);
  const kind = u.status === "update" ? "warn" : u.status === "current" || u.status === "edge" ? "ok" : "";
  return `
    <div class="toolbar">
      <button class="tool" id="upd-check"><span class="ti">${icon("arrows-rotate")}</span>Check</button>
    </div>
    <div class="section"><h2>Riparr updates<span class="grow"></span>
      ${u.status === "edge" ? channelTag(u.build) : `<span class="badge ${kind}">${esc(u.status)}</span>`}</h2>
      <div class="kv">
        <div class="k">Installed</div><div class="v">${esc(u.current)} ${channelTag(u.build)}</div>
        <div class="k">Latest release</div><div class="v">${esc(u.latest || "—")}${
          u.latest && newerVersion(u.current, u.latest)
            ? ` <span class="muted">· you're on a newer build than the latest release</span>` : ""}</div>
        <div class="k">Source</div><div class="v">
          <a href="https://github.com/${esc(u.repo)}" target="_blank" rel="noopener">github.com/${esc(u.repo)}</a></div>
      </div>
      <div class="alert ${u.status === "update" ? "warn" : ""}">${esc(u.message || "")}</div>
      ${u.how && u.status !== "edge" ? `<p class="muted" style="font-size:13px">To update: <code>${esc(u.how)}</code></p>` : ""}
      ${u.build && u.build.channel === "edge" ? `<p class="muted" style="font-size:13px">${u.build.commit
        ? `Built from commit <a href="https://github.com/${esc(u.repo)}/commit/${esc(u.build.commit)}"
             target="_blank" rel="noopener">${esc(u.build.commit)}</a>. ` : ""}To get newer code:
        ${u.build.install === "bare"
          ? `<code>sudo /opt/riparr/deploy/install.sh --update</code> picks up the newest
             code. To go back to releases, run it with <code>--release</code>.`
          : `<code>docker compose pull</code> picks up the newest one. To go back to
             releases, change the image tag to <code>:latest</code>.`}</p>` : ""}
    </div>
    ${mk && mk.status.installed ? `<div class="section"><h2>MakeMKV<span class="grow"></span>
      <span class="badge ${mk.upgrade ? "warn" : "ok"}">${mk.upgrade ? "update" : "current"}</span></h2>
      ${mkUpgradeBlock(mk)}
      <div class="kv">
        <div class="k">Installed</div><div class="v">${esc(mk.status.version || "—")}</div>
        <div class="k">Latest</div><div class="v">${esc(mk.manifest.version)}</div>
        <div class="k">Key</div><div class="v">${esc(keyPhrase(mk.status))}</div>
      </div></div>` : ""}
    ${u.notes ? `<div class="section"><h2>Release notes${u.latest ? ` \u00b7 ${esc(u.latest)}` : ""}</h2>
      <div class="notes md">${markdown(u.notes)}</div></div>` : ""}`;
};

/* ── Events ── */
const EVENT_LEVELS = { info: ["circle-info", ""], warning: ["triangle-exclamation", "warn"],
                       warn: ["triangle-exclamation", "warn"], error: ["circle-exclamation", "bad"],
                       critical: ["circle-exclamation", "bad"], debug: ["circle", "muted"] };

systemPages.events = async () => {
  // Most of the log is routine. "Problems only" is what somebody opening it is after,
  // and the server filters, so paging back reaches older problems, not older chatter.
  const problemsOnly = state.evProblems;
  const pages = state.evPages || 1;
  const levels = problemsOnly ? "&levels=warning,warn,error,critical" : "";
  const got = await Promise.all(Array.from({ length: pages }, (_, i) =>
    api.get(`/api/system/events?limit=200&offset=${i * 200}${levels}`)));
  const e = { total: got[0].total, events: got.flatMap(g => g.events) };
  // The same line logged over and over (a drive polled every few seconds, say) is one
  // row with a count, not a screenful.
  const runs = [];
  for (const x of e.events) {
    const last = runs[runs.length - 1];
    if (last && last.level === x.level && last.component === x.component && last.message === x.message) {
      last.n++; last.from = x.at;
    } else runs.push({ ...x, n: 1, from: x.at });
  }
  const rows = runs.length ? runs.map(x => {
    const [ic, cls] = EVENT_LEVELS[x.level] || EVENT_LEVELS.info;
    return `<tr>
      <td class="stat">${icon(ic, cls)}</td>
      <td data-label="Time">${stamp(x.at)}${x.n > 1 ? `<div class="muted">since ${stamp(x.from)}</div>` : ""}</td>
      <td data-label="From">${esc(x.component)}</td>
      <td class="st-name">${esc(x.message)}${x.n > 1 ? ` <span class="badge">\u00d7${x.n}</span>` : ""}</td></tr>`;
  }).join("")
    : `<tr><td colspan="4" class="muted">${problemsOnly
        ? "No warnings or errors logged." : "Nothing logged yet."}</td></tr>`;
  const more = e.events.length < e.total;

  return `
    <div class="toolbar">
      <button class="tool" id="ev-refresh"><span class="ti">${icon("arrows-rotate")}</span>Refresh</button>
      <label class="switch sm" style="margin:auto 12px"><input type="checkbox" id="ev-problems"${
        problemsOnly ? " checked" : ""}><span class="track"></span>
        <span class="lbl">Warnings and errors only</span></label>
      <button class="tool" id="ev-clear"><span class="ti">${icon("trash-can")}</span>Clear</button>
    </div>
    <div class="section"><h2>Events<span class="grow"></span>
      <span class="muted" style="font-size:13px">${e.total} recorded</span></h2>
      <table class="stack-table">
        <thead><tr><th class="stat"></th><th>Time</th><th>Component</th><th>Message</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      ${more ? `<div class="btn-row"><button class="btn sm" id="ev-older">Show older</button>
        <span class="muted" style="font-size:13px">${e.events.length} of ${e.total} shown</span></div>` : ""}
    </div>`;
};

/* ── Log Files ── */
systemPages.logs = async () => {
  const l = await api.get("/api/system/logs");
  const rows = l.files.length ? l.files.map(f => `<tr>
      <td class="st-name">${esc(f.name)}</td>
      <td data-label="Size">${filesize(f.size)}</td>
      <td data-label="Changed">${stamp(f.modified)}</td>
      <td class="act"><a href="/api/system/logs/${encodeURIComponent(f.name)}"
        download>Download</a></td></tr>`).join("")
    : `<tr><td colspan="4" class="muted">No log files yet.</td></tr>`;

  return `
    <div class="toolbar">
      <button class="tool" id="lg-refresh"><span class="ti">${icon("arrows-rotate")}</span>Refresh</button>
      <a class="tool" href="/api/system/diagnostics" download><span class="ti">${icon("file-zipper")}</span>Diagnostics</a>
      <button class="tool sep" id="lg-delete"><span class="ti">${icon("trash-can")}</span>Delete old logs</button>
    </div>
    <div class="section"><h2>Live<span class="grow"></span>
      <label class="switch sm"><input type="checkbox" id="lv-debug"><span class="track"></span>
        <span class="lbl">Include debug</span></label>
      <button class="btn sm" id="lv-pause">Pause</button>
      <button class="btn sm" id="lv-clear">Clear view</button></h2>
      <pre class="live-log" id="lv-out" tabindex="0"></pre>
      <p class="muted" style="font-size:13px">The newest lines, as they're written. To keep
        or share a log, download a file below — or <b>Diagnostics</b>, which bundles the
        logs, recent events, the last MakeMKV disc scan and your settings, with passwords,
        tokens and keys removed. That's the thing to attach to a bug report.</p>
    </div>
    <div class="alert">Log files are in <code>${esc(l.path)}</code>.
      <br><code>riparr.txt</code> is the ordinary record; <code>riparr.debug.txt</code>
      keeps everything and is the one to send if you are asking for help. Each is capped
      at 1 MB and rotated five times.</div>
    <div class="section"><h2>Files</h2>
      <table class="stack-table">
        <thead><tr><th>Filename</th><th>Size</th><th>Last Write Time</th>
          <th class="act"></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
};

/* The live log: polls for lines newer than the last one it has, about once a second,
   for as long as the page is open. Sticks to the bottom unless you've scrolled up to
   read something. */
let liveLog = null;
function startLiveLog() {
  if (liveLog) clearTimeout(liveLog.timer);
  const out = $("#lv-out");
  if (!out) { liveLog = null; return; }
  const me = liveLog = { after: 0, paused: false, timer: null };
  const MAX_LINES = 2000;
  const tick = async () => {
    if (liveLog !== me || !document.body.contains(out)) return;   // page left
    if (!me.paused && !document.hidden) {
      let r = null;
      try {
        r = await api.get(`/api/system/logs/live?after=${me.after}&debug=${$("#lv-debug").checked}`);
      } catch (e) { /* the service restarting; keep trying */ }
      if (r && r.lines.length) {
        const atBottom = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
        out.insertAdjacentHTML("beforeend", r.lines.map(l => {
          const t = new Date(l.at * 1000).toLocaleTimeString();
          // One line of markup: this is inside a <pre>, so any whitespace here shows.
          return `<div class="lv-line lv-${esc(l.level)}"><span class="lv-t">${esc(t)}</span><span class="lv-c">${esc(l.component)}</span> ${esc(l.text)}</div>`;
        }).join(""));
        while (out.childElementCount > MAX_LINES) out.firstElementChild.remove();
        if (atBottom) out.scrollTop = out.scrollHeight;
      }
      if (r) me.after = r.last;
    }
    me.timer = setTimeout(tick, 1000);
  };
  $("#lv-pause").onclick = () => {
    me.paused = !me.paused;
    $("#lv-pause").textContent = me.paused ? "Resume" : "Pause";
  };
  $("#lv-clear").onclick = () => { out.innerHTML = ""; };
  // Switching debug on or off starts again from the lines still in memory.
  $("#lv-debug").onchange = () => { out.innerHTML = ""; me.after = 0; };
  tick();
}

/* ── shared fragments ── */
/* `acts` is raw markup for the right-hand side -- the *arr page toolbar, moved into
   the header row rather than given a band of its own under it. */
function head(title, sub, acts) {
  return `<div class="page-head"><div><h1>${esc(title)}</h1>
    ${sub ? `<div class="sub">${esc(sub)}</div>` : ""}</div>
    ${acts ? `<div class="head-acts">${acts}</div>` : ""}</div>`;
}
function opt(v, label, cur) {
  return `<option value="${v}" ${cur === v ? "selected" : ""}>${esc(label)}</option>`;
}
function sw(key, label, on, help) {
  return `<label class="switch"><input type="checkbox" data-set="${key}" ${on ? "checked" : ""}>
    <span class="track"></span><span class="lbl">${esc(label)}
    ${help ? `<small>${esc(help)}</small>` : ""}</span></label>`;
}
/* Sticks to the bottom of the window, so Save is never a scroll away from the change,
   and says when there is something to save. */
function saveBar() {
  return `<div class="save-bar" id="save-bar">
    <span class="save-state" id="save-state" aria-live="polite">No unsaved changes</span>
    <button class="btn" id="discard-settings" type="button" hidden>Discard</button>
    <button class="btn primary" id="save-settings">Save changes</button></div>`;
}


/* ════════════════════ navigation ════════════════════
   *arr apps put sub-navigation in the sidebar, expanded under the active section,
   rather than in a tab strip above the content. */
const NAV = [
  { id: "queue",   label: "Queue",   icon: "table", href: "#/queue" },
  { id: "history", label: "History", icon: "clock-rotate-left", href: "#/history" },
  { id: "discs",   label: "Discs",   icon: "compact-disc", href: "#/discs" },
  { id: "settings", label: "Settings", icon: "gears", href: "#/settings/library",
    children: SETTINGS_TABS.map(([k, l]) => ({ key: k, label: l, href: `#/settings/${k}` })) },
  { id: "system",  label: "System",  icon: "laptop", href: "#/system/status",
    children: SYSTEM_TABS.map(([k, l]) => ({ key: k, label: l, href: `#/system/${k}` })) },
];

/* What each prerequisite is called when it's missing, and in the header pill. */
const CHECK_NEED = {
  "Riparr can read discs": ["MakeMKV installed", "MakeMKV"],
  "The MakeMKV key is current": ["a working MakeMKV key", "MakeMKV key"],
  "A drive to read them in": ["an optical drive", "Drive"],
  "Somewhere to put the files": ["a tested share", "Share"],
  "Room to work": ["room in staging", "Staging"],
};

/* One source of truth for "is something wrong": the server's Auto Rip checklist plus
   the few health checks that aren't prerequisites. The badge, the header pills, the
   queue's line and System → Status all count the same list, so they can't disagree. */
function problems(st) {
  if (!st) return [];
  const checks = ((st.autorip || {}).checks || []).filter(c => c.state !== "ok")
    .map(c => ({ level: c.state === "fail" ? "bad" : "warn", what: c.what,
                 message: `${c.what}: ${c.detail}${c.why ? ` \u2014 ${c.why}` : ""}`,
                 short: (() => {
                   const topic = (CHECK_NEED[c.what] || [0, c.what])[1];
                   // "Share: Share hasn't been tested" says it twice.
                   return c.detail.toLowerCase().startsWith(topic.toLowerCase())
                     ? c.detail : `${topic}: ${c.detail}`;
                 })(),
                 href: c.where }));
  return checks.concat(healthMessages(st));
}

/* Which image this is: a release (the :latest tag), an edge build of main, an image
   built by hand, or a source checkout. Edge says which commit, since two edge builds
   share a version number. */
const CHANNEL = {
  latest: ["latest", "A release build: the :latest image"],
  edge:   ["edge",   "A build of the newest code on main: the :edge image"],
  local:  ["local",  "An image built on this machine"],
  dev:    ["dev",    "Running from a source checkout, not an image"],
};
function channelTag(b) {
  if (!b) return "";
  const [label, why] = CHANNEL[b.channel] || [b.channel, ""];
  return `<span class="chan-tag ch-${esc(b.channel)}" title="${esc(why)}${
    b.commit ? ` (commit ${esc(b.commit)})` : ""}">${esc(label)}${
    b.channel === "edge" && b.commit ? ` \u00b7 ${esc(b.commit)}` : ""}</span>`;
}

function navBadges() {
  const n = problems(state.status).length;
  return n ? { system: n } : {};
}

function renderSidebar(section, sub) {
  const badges = navBadges();
  const st = state.status;
  $("#sidebar").innerHTML = NAV.map(n => {
    const on = n.id === section;
    const badge = badges[n.id] ? `<span class="nav-badge">${badges[n.id]}</span>` : "";
    let html = `<a class="nav-top ${on ? "on" : ""}" href="${n.href}"${
      on && !n.children ? ` aria-current="page"` : ""}>
      <span class="ico">${icon(n.icon)}</span>${n.label}${badge}</a>`;
    if (on && n.children) {
      html += n.children.map(c =>
        `<a class="nav-sub ${c.key === sub ? "on" : ""}" href="${c.href}"${
          c.key === sub ? ` aria-current="page"` : ""}>${c.label}</a>`).join("");
    }
    return html;
  }).join("") + `<div class="side-foot">
    <div class="cap">${
      st ? `<span class="muted">Working space on ${esc(st.hostname)}</span><br>${capacityPhrase(st.storage)}` : ""
    }</div>
    <div class="side-ver">${st && st.version ? `Riparr ${esc(st.version)} ${channelTag(st.build)}` : ""}</div>
  </div>`;
}

/* ════════════════════ router ════════════════════ */
/* What the last render produced, so a poll that changes nothing changes nothing. */
let lastRender = { hash: null, html: null };

/* A selector that finds "the same control" in the next render: its id, or failing
   that its first data- attribute (the cancel buttons have no id). */
function focusKey(el) {
  if (!el || el === document.body) return null;
  if (el.id) return `#${CSS.escape(el.id)}`;
  const a = Array.from(el.attributes).find(x => x.name.startsWith("data-"));
  return a ? `[${a.name}="${CSS.escape(a.value)}"]` : null;
}

let routeSeq = 0;
async function route(opts) {
  const live = !!(opts && opts.live);
  const seq = ++routeSeq;
  currentHash = location.hash;
  const hash = location.hash.replace(/^#\//, "") || "queue";
  const [section, sub] = hash.split("/");
  const view = views[section] || views.queue;
  const content = $("#content");

  // The poll re-renders the whole page. Doing that under somebody choosing from a
  // dropdown or typing closed the dropdown and threw their focus away every second, so
  // a live refresh waits until they are done with the control.
  const active = document.activeElement;
  if (live && content.contains(active) && active.matches("select, input, textarea")) {
    scheduleLiveRefresh(section);
    return;
  }

  renderSidebar(section, sub);
  renderTabs(section);

  let html;
  try {
    html = await view(sub);
  } catch (e) {
    if (seq !== routeSeq) return;
    content.innerHTML = `<div class="card"><div class="empty-state">
      <div class="big">${icon("triangle-exclamation")}</div><h2>Couldn't load that</h2><p>${esc(e.message)}</p></div></div>`;
    lastRender = { hash: null, html: null };
    return;
  }
  // A newer navigation started while this page was loading: it owns the screen. Without
  // this a slow page (Updates asks GitHub) finished last and covered the one clicked.
  if (seq !== routeSeq) return;
  if (live && hash === lastRender.hash && html === lastRender.html) {
    scheduleLiveRefresh(section);
    return;
  }
  const keep = live && content.contains(document.activeElement)
    ? focusKey(document.activeElement) : null;
  content.innerHTML = html;
  lastRender = { hash, html };
  paintIcons(content);
  wireContent(section, sub);
  if (keep) {
    const again = content.querySelector(keep);
    if (again) again.focus({ preventScroll: true });
  }
  if (!live) {
    $("#sidebar").classList.remove("open");
    document.body.classList.remove("nav-open");
    $("#hamburger").setAttribute("aria-expanded", "false");
  }
  document.body.classList.remove("has-savebar");      // shown once there's a change
  if (state.status) renderChrome();
  applySearch();
  scheduleLiveRefresh(section);
}

/* ── live refresh ──
   A progress bar that only moves when you press Refresh is not a progress bar. The
   queue re-renders itself while something is actually moving, and stops the moment
   nothing is -- an appliance with 512 MB should not be polling itself for no reason.

   `needs_input` deliberately does NOT keep the timer alive: that state has a form in
   it, and re-rendering underneath somebody halfway through typing a film title is a
   worse bug than a stale page. */
let liveTimer = null;

/* ── disc artwork ──
   Plex's trick: the film's poster behind the disc panel, so the box visibly knows what
   you put in. Deliberately quiet -- see .tray-art in app.css.

   It lives *inside* the disc cell rather than behind the whole viewport. Two reasons.
   A page-wide backdrop only shows where the page happens to be empty, so it vanished
   on a narrow window and had to be switched off on mobile entirely; and anchored to
   the panel it is composed against something, which is what makes it read as design
   rather than as a picture that happens to be behind the text.

   State, not DOM: the lookup result is cached here and `tray()` paints it on every
   render. The queue re-renders every 2.5s during a rip, so anything that faded itself
   in on each render would strobe. Painting the same background-image is a no-op for
   the browser, so it simply sits there. */
// label -> poster, per disc: with two drives there are two discs to show at once.
const discArt = {};
const artFor = (label) => (label && (discArt[label] || {}).image) || null;

async function setDiscArt(label) {
  if (!label || discArt[label]) return;      // no disc, or already decided
  discArt[label] = { image: null };
  let hit;
  try { hit = await api.get(`/api/artwork?label=${encodeURIComponent(label)}`); }
  catch (e) { delete discArt[label]; return; }   // offline: no backdrop, try again later
  if (!hit || !hit.ok) return;                // not sure enough: show nothing
  // Decode before painting, so it appears complete rather than in bands, and so a
  // failed image never leaves a half-painted panel.
  await new Promise((res) => {
    const img = new Image();
    img.onload = img.onerror = res;
    img.src = hit.image;
  });
  discArt[label] = { image: hit.image, title: hit.title };
  if ((location.hash.replace(/^#\//, "").split("/")[0] || "queue") === "queue") route({ live: true });
}

function scheduleLiveRefresh(section) {
  clearTimeout(liveTimer);
  if (section !== "queue") return;
  // Still true: a job waiting for input has a form in it, and re-rendering underneath
  // somebody mid-sentence is worse than a stale page.
  if ($$(".job.needs").length) {
    // Don't redraw the form under somebody -- but notice if the question went away
    // (answered on another device, skipped, cancelled), and only then redraw.
    liveTimer = setTimeout(async () => {
      const onPage = $$("[data-answer], [data-answer-season], [data-skip]")
        .map(b => Number(b.dataset.answer || b.dataset.answerSeason || b.dataset.skip));
      let q;
      try { q = await api.get("/api/queue"); } catch (e) { scheduleLiveRefresh(section); return; }
      const still = new Set((q.jobs || []).filter(j => j.state === "needs_input").map(j => j.id));
      if (onPage.some(id => !still.has(id))) route();
      else scheduleLiveRefresh(section);
    }, 8000);
    return;
  }
  // An *idle* queue has to keep looking too. Putting a disc in is the one thing on this
  // page that happens with no user action, and this used to return early whenever the
  // queue was empty -- so the tray stayed empty until the user clicked something, and
  // Refresh re-rendered the same stale snapshot. Slower when idle: nothing is racing.
  // 1.2s while a job is live. The phase line, the legs and the ETA all move on their
  // own during a rip, and at 2.5s the numbers visibly stepped rather than counted.
  const delay = $$(".job, .np-live").length ? 1200 : 5000;
  liveTimer = setTimeout(() => {
    // A hidden tab must keep the loop alive, not end it. This used to just skip the
    // refresh and never reschedule, so switching away during a rip killed polling for
    // good: you came back to a page frozen on "Saving to MKV file" while the box had
    // long since finished uploading. Nothing was wrong with the box, and nothing was
    // wrong with the job -- the page had simply stopped asking.
    if (document.hidden) { scheduleLiveRefresh(section); return; }
    route({ live: true });
  }, delay);
}

/* Riparr asking a question has to reach you on any page and in a background tab: the
   queue's own refresh only runs on the queue, and pauses while hidden. This is a light
   check every 20s that only touches the tab title, the announcement and the tab dot. */
setInterval(async () => {
  if (!state.settings) return;                           // not signed in yet
  const onQueue = (location.hash.replace(/^#\//, "").split("/")[0] || "queue") === "queue";
  if (onQueue && !document.hidden) return;               // the queue's own loop has it
  let q;
  try { q = await api.get("/api/queue"); } catch (e) { return; }
  const asking = (q.jobs || []).filter(j => j.state === "needs_input");
  announceAsk(asking);
  state.asking = asking.length;
  renderTabs();
}, 20000);

/* Coming back to the tab should show now, not in a second and a bit. */
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && (location.hash.replace(/^#\//, "").split("/")[0] || "queue") === "queue") {
    route({ live: true });
  }
});

function collectSettings() {
  const out = {};
  $$("[data-set]").forEach(el => {
    const k = el.dataset.set;
    // `data-multi` means several checkboxes share one key and collect into a list --
    // the notification event switches, where each is a member rather than a boolean.
    if (el.dataset.multi !== undefined) {
      out[k] = out[k] || [];
      if (el.checked) out[k].push(el.value);
    } else if (el.type === "checkbox") out[k] = el.checked;
    else if (el.dataset.list !== undefined)
      out[k] = el.value.split(",").map(s => s.trim()).filter(Boolean);
    else if (el.type === "number") out[k] = Number(el.value);
    // A <select> whose values are row ids. Without this the share id is saved as the
    // string "2", which never equals the integer 2 the database hands back, so the
    // destination silently fell through to the default share.
    else if (el.dataset.int !== undefined) out[k] = el.value === "" ? null : Number(el.value);
    else out[k] = el.value;
  });
  return out;
}

function wireContent(section, sub) {
  const autorip = $("#autorip");
  if (autorip) autorip.onchange = async () => {
    const want = autorip.checked;
    try {
      const r = await api.post("/api/autorip", { enabled: want });
      toast(r.enabled ? "Auto Rip is on" : "Auto Rip is off", r.enabled ? "ok" : "");
      route();
    } catch (e) {
      autorip.checked = !want;
      toast(e.message, "bad");
    }
  };

  /* The channel accordion on Connect. One open at a time: these panels are ten steps
     of somebody else's instructions each, and two of them open at once is the flat
     page this replaced. Nothing is destroyed by closing one -- the inputs stay in the
     DOM, so `collectSettings` still reads a closed panel and Save still saves it. */
  $$(".chan .chan-head").forEach(head => {
    head.onclick = () => {
      const row = head.closest(".chan");
      const body = row.querySelector(".chan-body");
      const opening = body.hidden;
      $$(".chan").forEach(other => {
        other.classList.remove("open");
        other.querySelector(".chan-body").hidden = true;
        other.querySelector(".chan-head").setAttribute("aria-expanded", "false");
      });
      if (opening) {
        row.classList.add("open");
        body.hidden = false;
        head.setAttribute("aria-expanded", "true");
      }
    };
  });

  // Check the URL that is on screen, not the one that is stored. The whole point is
  // to catch a paste that went wrong, and a check that reads the database would pass
  // on the old value and tell the user nothing.
  const dcCheck = $("#dc-check");
  if (dcCheck) dcCheck.onclick = async () => {
    const out = $("#dc-out");
    dcCheck.disabled = true;
    out.className = "test-out";
    out.textContent = "Asking Discord…";
    try {
      const r = await api.post("/api/notifications/discord/check",
                               { url: ($("#dc-url") || {}).value || "" });
      if (r.ok) {
        out.className = "test-out ok";
        out.textContent = `Real webhook — posts as “${r.name}”. Save, then send a test.`;
      } else {
        out.className = "test-out bad";
        out.textContent = r.error;
      }
    } catch (e) {
      out.className = "test-out bad";
      out.textContent = e.message;
    }
    dcCheck.disabled = false;
  };

  // Nobody inside the software can see the drive's light, so this button exists for a
  // person to watch. The result reports sectors actually read, which is the only proof
  // available that the reads reached the drive rather than the page cache.
  $$("[data-signal-test]").forEach(b => b.onclick = async () => {
    const out = $("#signal-out");
    const mode = b.dataset.signalTest;
    $$("[data-signal-test]").forEach(x => x.disabled = true);
    out.className = "test-out";
    out.textContent = mode === "tray" ? "Watch the tray…" : "Watch the drive…";
    try {
      const r = await api.post("/api/drive/signal-test",
                               { mode, device: ($("#signal-drive") || {}).value || "" });
      out.className = "test-out " + (r.ok ? "ok" : "warn");
      out.textContent = r.message;
    } catch (e) {
      out.className = "test-out bad";
      out.textContent = e.message;
    }
    $$("[data-signal-test]").forEach(x => x.disabled = false);
  });

  $$("[data-test-notify]").forEach(b => b.onclick = async () => {
    const channel = b.dataset.testNotify;
    const out = $("#test-" + channel);
    b.disabled = true;
    out.className = "test-out";
    out.textContent = "Saving…";
    try {
      await api.put("/api/settings", collectSettings());
      out.textContent = "Sending…";
      const r = await api.post("/api/notifications/test", { channel });
      out.className = "test-out ok";
      out.textContent = r.message;
    } catch (e) {
      out.className = "test-out bad";
      out.textContent = e.message;
    }
    b.disabled = false;
  });

  /* ── System: Tasks, Backup, Events, Log Files ── */
  $$("[data-task]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try {
      const r = await api.post(`/api/system/tasks/${b.dataset.task}`);
      toast(r.error ? `${r.label} failed: ${r.error}` : `${r.label} finished`,
            r.error ? "bad" : "ok");
    } catch (e) { toast(e.message, "bad"); }
    route();
  });

  const bkNow = $("#bk-now");
  if (bkNow) bkNow.onclick = async () => {
    bkNow.disabled = true;
    try {
      const r = await api.post("/api/system/backups");
      toast(`Backup written — ${filesize(r.size)}`, "ok");
    } catch (e) { toast(e.message, "bad"); }
    route();
  };

  const bkUpload = $("#bk-upload"), bkFile = $("#bk-file");
  if (bkUpload) {
    bkUpload.onclick = () => bkFile.click();
    bkFile.onchange = async () => {
      const f = bkFile.files[0];
      if (!f) return;
      if (!confirm(`Restore from ${f.name}?\n\nThis overwrites your current settings.`)) {
        bkFile.value = "";
        return;
      }
      const fd = new FormData();
      fd.append("file", f);
      try {
        // FormData, so no JSON Content-Type -- the browser has to set the boundary.
        const r = await fetch("/api/system/backups/upload", { method: "POST", body: fd });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || "Restore failed");
        toast(`Restored ${d.settings} setting(s). ${d.note}`, "ok");
      } catch (e) { toast(e.message, "bad"); }
      bkFile.value = "";
      route();
    };
  }

  $$("[data-restore]").forEach(b => b.onclick = async () => {
    const name = b.dataset.restore;
    if (!confirm(`Restore ${name}?\n\nThis overwrites your current settings. `
                 + `Share passwords are not in a backup and will have to be re-entered.`)) return;
    try {
      const r = await api.post(`/api/system/backups/${encodeURIComponent(name)}/restore`);
      toast(`Restored ${r.settings} setting(s). ${r.note}`, "ok");
    } catch (e) { toast(e.message, "bad"); }
    route();
  });

  $$("[data-delbackup]").forEach(b => b.onclick = async () => {
    const name = b.dataset.delbackup;
    if (!confirm(`Delete ${name}?`)) return;
    try { await api.del(`/api/system/backups/${encodeURIComponent(name)}`); }
    catch (e) { toast(e.message, "bad"); }
    route();
  });

  const evProblems = $("#ev-problems");
  if (evProblems) evProblems.onchange = () => { state.evProblems = evProblems.checked; state.evPages = 1; route(); };
  const evOlder = $("#ev-older");
  if (evOlder) evOlder.onclick = () => { state.evPages = (state.evPages || 1) + 1; route(); };
  const evRefresh = $("#ev-refresh");
  if (evRefresh) evRefresh.onclick = () => route();
  const evClear = $("#ev-clear");
  if (evClear) evClear.onclick = async () => {
    if (!confirm("Clear the event log?\n\nThe log files on disk are not touched.")) return;
    try { await api.del("/api/system/events"); toast("Event log cleared", "ok"); }
    catch (e) { toast(e.message, "bad"); }
    route();
  };

  if ($("#lv-out")) startLiveLog();
  const lgRefresh = $("#lg-refresh");
  if (lgRefresh) lgRefresh.onclick = () => route();
  const lgDelete = $("#lg-delete");
  if (lgDelete) lgDelete.onclick = async () => {
    if (!confirm("Delete the rotated log files?\n\nThe two files currently being "
                 + "written to are kept.")) return;
    try {
      const r = await api.del("/api/system/logs");
      toast(r.deleted ? `Deleted ${r.deleted} file(s)` : "Nothing to delete", "ok");
    } catch (e) { toast(e.message, "bad"); }
    route();
  };

  $$("[data-disc]").forEach(b => b.onclick = () => showDiscDetails(b.dataset.disc || ""));
  const refresh = $("#t-refresh");
  if (refresh) refresh.onclick = () => route();
  $$("[data-eject]").forEach(b => b.onclick = async () => {
    const r = await api.post("/api/drive/eject", { device: b.dataset.eject || "" });
    toast(r.message, r.ok ? "ok" : "bad");
  });

  // Offered when the diagnosis says the drive is probably in the socket that cannot
  // host. Reboots, so it borrows the same full-screen overlay as restart.
  if ($(".rips")) paintRipArt();

  // Bring the tile to the user rather than making them find it. `center` because a
  // tile scrolled to the very top of the viewport reads as "the first one", not as
  // "this one".
  const dupeTile = $("#dupe-tile");
  if (dupeTile) {
    dupeTile.scrollIntoView({ behavior: "smooth", block: "center" });
    // The blink is attention, not decoration, so it stops. A tile that pulses forever
    // becomes part of the furniture and stops meaning anything.
    setTimeout(() => dupeTile.classList.remove("dupe"), 9000);
  }
  const dupeX = $("#dupe-dismiss");
  if (dupeX) dupeX.onclick = () => { location.hash = "#/discs"; };

  const arRoute = $("#ar-route");
  if (arRoute) arRoute.onchange = async () => {
    try {
      const r = await api.put("/api/settings", { transfer_mode: arRoute.value });
      if (state.settings) state.settings.transfer_mode = arRoute.value;
      // Turning on direct can take deep verification with it -- see db.reconcile. Take
      // the correction from the response rather than assuming, and say so: a second
      // control changing on its own is alarming unless somebody explains it.
      const changed = applyAdjusted(r);
      toast(arRoute.value === "direct"
              ? (changed.verify_mode === "quick"
                   ? "Rips go straight to your library. Deep checking needs two copies, so it's a size check now."
                   : "Rips go straight to your library")
              : "Rips are staged first", "ok");
      route();
    } catch (e) { toast(e.message, "bad"); }
  };

  // Measured, not asserted. The recommendation is only worth showing because it comes
  // from this card rather than from an opinion about cards in general.
  const speed = $("#ar-speedtest");
  if (speed) speed.onclick = async () => {
    const out = $("#ar-speed-out");
    speed.disabled = true;
    out.className = "test-out";
    out.textContent = "Writing 64 MB…";
    try {
      const r = await api.post("/api/storage/speedtest", {});
      const c = r.card || {};
      out.className = "test-out " + (r.recommend === "direct" ? "warn" : "ok");
      out.textContent = `${c.write_mbs ?? "?"} MB/s write, ${c.read_mbs ?? "?"} read. ${r.why || ""}`;
      if (state.settings) state.settings.card_speed = c;
      if (r.recommend && r.recommend !== (state.settings || {}).transfer_mode) {
        if (confirm(`${r.why}\n\nSwitch to ${
            r.recommend === "direct" ? "writing straight to your library" : "staging first"}?`)) {
          const saved = await api.put("/api/settings", { transfer_mode: r.recommend });
          if (state.settings) state.settings.transfer_mode = r.recommend;
          applyAdjusted(saved);
          route();
          return;
        }
      }
    } catch (e) {
      out.className = "test-out bad";
      out.textContent = e.message;
    }
    speed.disabled = false;
  };

  const arVerify = $("#ar-verify");
  if (arVerify) arVerify.onchange = async () => {
    try {
      await api.put("/api/settings", { verify_mode: arVerify.value });
      if (state.settings) state.settings.verify_mode = arVerify.value;
      toast("Saved", "ok");
      route();
    } catch (e) { toast(e.message, "bad"); }
  };


  $$("[data-hgshow]").forEach(b => b.onclick = () => {
    const rows = $$(`[data-hgfold="${CSS.escape(b.dataset.hgshow)}"]`);
    rows.forEach(r => r.classList.remove("hg-folded"));
    // Focus to the first row that just appeared, not back to the top of the page.
    if (rows[0]) { rows[0].setAttribute("tabindex", "-1"); rows[0].focus(); }
    b.remove();
  });
  $$("[data-hg]").forEach(b => b.onclick = () => {
    const k = b.dataset.hg, body = b.nextElementSibling;
    const open = body.hidden;
    body.hidden = !open;
    b.setAttribute("aria-expanded", String(open));
    if (open) histOpen.add(k); else histOpen.delete(k);
  });

  $$("[data-discs-kind]").forEach(b => b.onclick = () => {
    state.discsKind = b.dataset.discsKind;
    route();
  });

  $$("[data-filed-dismiss]").forEach(b => b.onclick = () => {
    const ids = dismissedFiled().concat(String(b.dataset.filedDismiss)).slice(-20);
    try { localStorage.setItem(FILED_KEY, JSON.stringify(ids)); } catch (e) { /* fine */ }
    // Focus goes to what replaced the card, not to the top of the page.
    route().then(() => focusHeading());
  });

  $$("[data-mk]").forEach(mk => mk.ontoggle = () => {
    state.mkOpen = Object.assign(state.mkOpen || {}, { [mk.dataset.mk]: mk.open });
  });

  const ripOpts = $("#rip-opts");
  if (ripOpts) ripOpts.ontoggle = () => {
    state.ripOptsOpen = ripOpts.open;
    $(".ropt-change", ripOpts).textContent = ripOpts.open ? "Done" : "Change";
  };

  $$("[data-rip]").forEach(ripNow => ripNow.onclick = async () => {
    // Say something immediately. Starting a rip reads the disc before the job exists,
    // and on a real encrypted DVD that scan is *nine minutes*, not the few seconds
    // this comment used to claim -- so `POST /api/rip` is a nine-minute request. The
    // spinner is not what saves it; the queue's own poll is. The job row appears
    // within a second or two and replaces this whole panel, button and all.
    ripNow.disabled = true;
    const was = ripNow.innerHTML;
    ripNow.innerHTML = `<span class="spin"></span> Starting\u2026`;
    try {
      await api.post("/api/rip", { device: ripNow.dataset.rip || "" });
    } catch (e) {
      toast(e.message, "bad");
      ripNow.innerHTML = was;
      ripNow.disabled = false;
      return;
    }
    route();   // the job now exists, so the panel becomes the progress view
  });

  $$("[data-cancel]").forEach(b => b.onclick = async () => {
    if (!await askDialog({ title: "Cancel this rip?", body: "<p>Anything done so far is discarded.</p>",
                           ok: "Cancel the rip", cancel: "Keep ripping", danger: true })) return;
    try { await api.post(`/api/queue/${b.dataset.cancel}/cancel`, {}); }
    catch (e) {
      // Pressed after it had already stopped: the outcome is the one asked for.
      if (!/already (finished|stopped|cancelled)/i.test(e.message)) toast(e.message, "bad");
    }
    route();
  });

  $$("[data-retry]").forEach(b => b.onclick = async () => {
    try {
      const r = await api.post(`/api/queue/${b.dataset.retry}/retry`, {});
      toast(r.message, "ok");
    } catch (e) { toast(e.message, "bad"); }
    route();
  });

  // The four retries on History. Each one is offered only when the box can actually
  // do it -- the server works that out, because whether the staged file is still on
  // the card is not something the browser can see.
  $$("[data-hretry]").forEach(b => b.onclick = async () => {
    const id = b.dataset.hretry, act = b.dataset.haction;
    const asks = {
      "rip": "Read this disc again from the start?\n\nLeave the disc on the tray — "
           + "Riparr will pull it in. This is the expensive one; the whole disc gets "
           + "read again.",
      "verify-deep": "Read the whole file back off your library and hash it?\n\n"
           + "This takes about as long as the upload did and needs as much free space "
           + "again as the film.",
    };
    if (asks[act] && !confirm(asks[act])) return;
    b.disabled = true;
    const wasLabel = b.innerHTML;
    if (act === "rip") b.innerHTML = `<span class="spin"></span> Starting…`;
    try {
      const r = act === "upload" ? await api.post(`/api/queue/${id}/retry`, {})
              : act === "rip"    ? await api.post(`/api/queue/${id}/rerip`, {})
              : await api.post(`/api/queue/${id}/verify`,
                               { mode: act === "verify-deep" ? "deep" : "quick" });
      toast(r.message || "Started", "ok");
      if (act === "rip" || act === "upload") location.hash = "#/queue";
      else route();
    } catch (e) {
      toast(e.message, "bad");
      b.innerHTML = wasLabel;
      b.disabled = false;
    }
  });

  /* TMDb in the "which film is this?" question: pick a card, or search for another. */
  $$("[data-tmdb-for]").forEach(box => {
    const wire = () => box.querySelectorAll("[data-tmdb-pick]").forEach(c => c.onclick = () => {
      const on = !c.classList.contains("on");
      box.querySelectorAll("[data-tmdb-pick]").forEach(x => x.classList.remove("on"));
      c.classList.toggle("on", on);
      box.dataset.picked = on ? c.dataset.tmdbPick : "";
      const name = askRoot(box).querySelector(".ni-name-input");
      if (name && on) name.value = c.dataset.name;
    });
    wire();
    const nameInput = askRoot(box).querySelector(".ni-name-input");
    if (nameInput) nameInput.addEventListener("input", () => {
      // A typed name is a different answer from the picked film.
      box.dataset.picked = "";
      box.querySelectorAll("[data-tmdb-pick]").forEach(x => x.classList.remove("on"));
    });
    const q = box.querySelector(".ni-tmdb-q"), go = box.querySelector(".ni-tmdb-go");
    go.onclick = async () => {
      if (!q.value.trim()) return;
      go.disabled = true;
      let r;
      try { r = await api.get(`/api/tmdb/search?q=${encodeURIComponent(q.value.trim())}`); }
      catch (e) { toast(e.message, "bad"); go.disabled = false; return; }
      box.querySelector(".tmdb-picks").innerHTML = (r.results || []).length
        ? tmdbPicks(r.results, box.dataset.picked)
        : `<p class="muted">Nothing on TMDb for that.</p>`;
      wire();
      go.disabled = false;
    };
    q.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); go.click(); } };
  });

  $$("[data-music-for]").forEach(box => {
    const wire = () => box.querySelectorAll("[data-mb-pick]").forEach(c => c.onclick = () => {
      const on = !c.classList.contains("on");
      box.querySelectorAll("[data-mb-pick]").forEach(x => x.classList.remove("on"));
      c.classList.toggle("on", on);
      box.dataset.picked = on ? c.dataset.mbPick : "";
    });
    wire();
    const go = box.querySelector(".mb-go");
    const search = async () => {
      const album = box.querySelector(".mb-album").value.trim();
      const artist = box.querySelector(".mb-artist").value.trim();
      if (!album && !artist) return;
      go.disabled = true;
      let r;
      // This question's own CD: with two loaded, the other drive's would reorder wrongly.
      const job = (state.lastJobs || []).find(j => String(j.id) === box.dataset.musicFor);
      const drive = ((state.status || {}).drives || []).find(d => job && d.device === job.device);
      const tracks = (drive && drive.audio_tracks) || (job && (job.titles || []).length) || 0;
      try {
        r = await api.get(`/api/musicbrainz/search?album=${encodeURIComponent(album)}&artist=${
          encodeURIComponent(artist)}&tracks=${tracks}`);
      } catch (e) { toast(e.message, "bad"); go.disabled = false; return; }
      box.querySelector(".mb-picks").innerHTML = (r.results || []).length
        ? albumPicks(r.results) : `<p class="muted">Nothing on MusicBrainz for that.</p>`;
      box.dataset.picked = "";
      wire();
      go.disabled = false;
    };
    go.onclick = search;
    box.querySelectorAll(".mb-album, .mb-artist").forEach(i => i.onkeydown = (e) => {
      if (e.key === "Enter") { e.preventDefault(); search(); }
    });
  });

  $$("[data-answer-music]").forEach(b => b.onclick = async () => {
    const box = b.closest("[data-music-for]");
    const body = {};
    if (box.dataset.picked) body.release_id = box.dataset.picked;
    else {
      body.artist = box.querySelector(".mb-typed-artist").value.trim();
      body.album = box.querySelector(".mb-typed-album").value.trim();
      if (!body.artist && !body.album) {
        toast("Pick the album, or type its artist and name.", "bad");
        return;
      }
    }
    b.disabled = true;
    try { await api.post(`/api/queue/${b.dataset.answerMusic}/answer`, body); }
    catch (e) { toast(e.message, "bad"); b.disabled = false; return; }
    route();
  });

  $$("[data-answer]").forEach(b => b.onclick = async () => {
    const root = askRoot(b);
    const picked = root.querySelector('input[name^="ni-title"]:checked');
    const body = { name: (root.querySelector(".ni-name-input") || {}).value || "" };
    if (picked) body.title_index = Number(picked.value);
    const film = $(`[data-tmdb-for="${b.dataset.answer}"]`);
    if (film && film.dataset.picked) body.tmdb_id = Number(film.dataset.picked);
    if (!body.name.trim() && !picked) {
      toast("Give it a name, or pick which title is the film.", "bad");
      return;
    }
    // TMDb offered films and none was picked or typed: a title alone isn't a name.
    if (film && film.querySelector("[data-tmdb-pick]") && !body.tmdb_id && !body.name.trim()) {
      toast("Pick one of the films, or type its name.", "bad");
      return;
    }
    b.disabled = true;
    try { await api.post(`/api/queue/${b.dataset.answer}/answer`, body); }
    catch (e) { toast(e.message, "bad"); b.disabled = false; return; }
    route();
  });

  /* The episode plan, sent as one answer. Everything the user can touch is read off
     the DOM at submit time rather than tracked in a model: the panel is redrawn from
     the server on every poll, so a model would have to be reconciled with it, and the
     reconciliation is more code than the read. */
  $$("[data-answer-season]").forEach(b => b.onclick = async () => {
    const root = askRoot(b);
    const field = (id) => root.querySelector("#" + id) || {};
    const rows = [...root.querySelectorAll("#ep-rows .ep-row")];
    const include = [], titles = {}, order = [];
    rows.forEach(r => {
      const ti = Number(r.dataset.ti);
      order.push(ti);
      if (r.querySelector(".ep-keep").checked) include.push(ti);
      titles[String(ti)] = r.querySelector(".ep-title").value || "";
    });
    if (!include.length) {
      toast("Tick at least one episode, or skip the disc.", "bad");
      return;
    }
    const season = field("ep-season").value;
    if (season === "") {
      toast("Give it a season number — the files need one.", "bad");
      return;
    }
    const picked = field("ep-series").value;
    const body = {
      season: Number(season),
      first_episode: Number(field("ep-first").value || 1),
      include, order, episode_titles: titles,
      name: (field("ep-name").value || "").trim(),
    };
    if (picked) body.series_id = Number(picked);
    b.disabled = true;
    try { await api.post(`/api/queue/${b.dataset.answerSeason}/answer`, body); }
    catch (e) { toast(e.message, "bad"); b.disabled = false; return; }
    route();
  });

  /* Reordering is done in the page and renumbered as it goes, so the numbers on screen
     always describe what would be written if the button were pressed now. Sending a
     move to the server and redrawing would work too and would cost a round trip per
     click on a box that is busy reading a disc. */
  const moveRow = (root, ti, delta) => {
    const box = root.querySelector("#ep-rows");
    if (!box) return;
    const rows = [...box.querySelectorAll(".ep-row")];
    const i = rows.findIndex(r => Number(r.dataset.ti) === ti);
    const to = i + delta;
    if (i < 0 || to < 0 || to >= rows.length) return;
    // Keep what the user has typed or unticked: the nodes are moved, not re-rendered.
    if (delta < 0) box.insertBefore(rows[i], rows[to]);
    else box.insertBefore(rows[to], rows[i]);
    renumberRows(root);
  };
  const renumberRows = (root) => {
    const seasonRaw = (root.querySelector("#ep-season") || {}).value;
    const season = seasonRaw === "" ? null : Number(seasonRaw);
    let n = Number((root.querySelector("#ep-first") || {}).value || 1);
    [...root.querySelectorAll("#ep-rows .ep-row")].forEach((r, i, all) => {
      const keep = r.querySelector(".ep-keep").checked;
      const span = r.querySelector(".ep-title").placeholder.startsWith("Two") ? 2 : 1;
      const cell = r.querySelector(".ep-num");
      r.classList.toggle("dropped", !keep);
      if (!keep) { cell.textContent = "—"; }
      else {
        cell.textContent = episodeCode({ season, episode: n,
                                         episode_last: n + span - 1 });
        n += span;
      }
      r.querySelector("[data-up]").disabled = i === 0;
      r.querySelector("[data-down]").disabled = i === all.length - 1;
    });
  };
  $$("[data-up]").forEach(b => b.onclick = () => moveRow(askRoot(b), Number(b.dataset.up), -1));
  $$("[data-down]").forEach(b => b.onclick = () => moveRow(askRoot(b), Number(b.dataset.down), 1));
  $$("#ep-rows .ep-keep").forEach(c => c.onchange = () => renumberRows(askRoot(c)));
  $$("#ep-season, #ep-first").forEach(el => el.oninput = () => renumberRows(askRoot(el)));

  $$("[data-skip]").forEach(b => b.onclick = async () => {
    if (!await askDialog({ title: "Skip this disc?", body: "<p>It's ejected without being ripped.</p>",
                           ok: "Skip it", cancel: "Keep it", danger: true })) return;
    try { await api.post(`/api/queue/${b.dataset.skip}/answer`, { skip: true }); }
    catch (e) { toast(e.message, "bad"); }
    route();
  });

  $$("[data-rerip]").forEach(b => b.onclick = async () => {
    // Say the right thing about the tray: the disc is either in the drive already, or
    // out on the tray waiting to be pulled back in.
    const drives = (state.status || {}).drives || [];
    const drive = drives.find(d => d.present && d.known && d.known.fingerprint === b.dataset.rerip);
    const name = drive && drive.known ? drive.known.title : "this disc";
    const which = drive && drives.length > 1 ? ` in ${driveName(drive)} (${drive.device})` : "";
    if (!await askDialog({
      title: `Rip ${name} again?`,
      body: (drive
        ? `<p>Riparr reads the whole disc${esc(which)} again and replaces what's in your library.</p>`
        : `<p>Leave the disc on its tray: Riparr pulls the tray in and reads the whole disc
             again, replacing what's in your library.</p>`)
        + (drive && drive.space_warning ? `<p class="np-err np-caution">${esc(drive.space_warning)}</p>` : ""),
      ok: "Rip again" })) return;
    // Closing the tray and waiting for the drive to find the disc takes up to half a
    // minute, and a button that sits there looking clickable for half a minute is a
    // button somebody clicks twice.
    b.disabled = true;
    const was = b.innerHTML;
    b.innerHTML = `<span class="spin"></span> Starting…`;
    try {
      await api.post(`/api/discs/${encodeURIComponent(b.dataset.rerip)}/rerip`, {});
      toast("Started", "ok");
      if ((location.hash || "#/queue").startsWith("#/queue")) route();
      else location.hash = "#/queue";
    } catch (e) {
      toast(e.message, "bad");
      b.innerHTML = was;
      b.disabled = false;
    }
  });

  // Fetching is a network round trip to somebody else's forum, so it happens after
  // the page is on screen rather than blocking it.
  if ($("#mk-key-offer")) offerBetaKey("#mk-key-offer", "#mk-key-input");

  /* The panel was drawn from whatever was already known, which on a first visit is
     nothing. Follow the probe that the page load kicked off. */
  if ($("#sites-inner")) followSites(state.mkKeyTopic);

  const recheck = $("#sites-recheck");
  if (recheck) recheck.onclick = async () => {
    const out = $("#sites-out");
    recheck.disabled = true;
    out.className = "test-out";
    out.textContent = "Checking…";
    try {
      // The one call that is allowed to wait: the user asked for it by pressing this.
      const r = await api.post("/api/makemkv/sites", {});
      paintSites(r, state.mkKeyTopic);
      out.textContent = "";
    } catch (e) {
      out.className = "test-out bad";
      out.textContent = e.message;
    }
    recheck.disabled = false;
  };


  const save = $("#save-settings");
  if (save) save.onclick = async () => {
    try {
      const r = await api.put("/api/settings", collectSettings());
      // The page can be showing a combination the box will not keep -- direct rips and
      // deep verification, saved together. Re-render when that happened, so the
      // controls agree with what was actually stored instead of quietly disagreeing
      // until the next reload.
      const adj = applyAdjusted(r);
      settingsSnapshot = JSON.stringify(collectSettings());
      markDirty();
      if (adj.verify_mode) {
        toast("Saved. Deep checking needs two copies, so verification is a size check while rips go straight to your library.", "ok");
        route();
        return;
      }
      toast("Settings saved", "ok");
    } catch (e) { toast(e.message, "bad"); }
  };
  settingsSnapshot = save ? JSON.stringify(collectSettings()) : null;
  if (save) $("#discard-settings").onclick = () => {
    settingsSnapshot = null;
    route().then(() => focusHeading());
  };

  // Long help folds to one line with a "More" link. Read once, it is in the way on
  // every later visit -- and on the Ripping page it was most of the page.
  $$(".f .help, .section p.help, .switch .lbl small").forEach(h => {
    if (h.classList.contains("naming-preview") || h.scrollHeight <= 42) return;
    h.classList.add("clamp");
    const more = document.createElement("button");
    more.type = "button";
    more.className = "help-more";
    more.textContent = "More";
    const about = (h.closest(".f")?.querySelector(":scope > span:first-child")
                   || h.closest(".switch")?.querySelector(".lbl")
                   || h.closest(".section")?.querySelector("h2"))?.firstChild?.textContent?.trim();
    if (about) more.setAttribute("aria-label", `More about ${about}`);
    more.setAttribute("aria-expanded", "false");
    more.onclick = (e) => {
      e.preventDefault();
      const open = h.classList.toggle("open");
      more.textContent = open ? "Less" : "More";
      more.setAttribute("aria-expanded", String(open));
    };
    h.after(more);
  });

  const themePick = $("#theme-pick");
  if (themePick) themePick.onchange = async () => {
    applyTheme(themePick.value);
    await api.put("/api/settings", { theme: themePick.value });
    toast(`Theme set to ${themePick.selectedOptions[0].textContent}`, "ok");
  };

  $$("[data-forget]").forEach(b => b.onclick = () => {
    const fp = b.dataset.forget;
    const fig = b.closest("figure");
    const what = (fig && $(".rip-title", fig)?.textContent.trim()) || "the disc";
    undoable(fig, `Forgot ${what}`,
             () => api.del(`/api/discs/${encodeURIComponent(fp)}`));
  });

  $$("[data-del-share]").forEach(b => b.onclick = () => {
    const id = b.dataset.delShare;
    const row = b.closest(".rowitem");
    const what = (row && $(".t", row)?.childNodes[0]?.textContent.trim()) || "the share";
    undoable(row, `Removed ${what}`, () => api.del(`/api/shares/${id}`));
  });

  const pwGo = $("#pw-go");
  if (pwGo) pwGo.onclick = async () => {
    const res = $("#pw-res");
    if ($("#pw-new").value !== $("#pw-new2").value) {
      res.innerHTML = `<div class="result bad">The two passwords don't match.</div>`;
      return;
    }
    try {
      await api.post("/api/auth/password", {
        current_password: $("#pw-cur").value, new_password: $("#pw-new").value });
      res.innerHTML = `<div class="result ok">Password changed.</div>`;
    } catch (e) { res.innerHTML = `<div class="result bad">${esc(e.message)}</div>`; }
  };

  const check = $("#upd-check");
  if (check) check.onclick = () => route();
  const imp = $("#import-btn");
  if (imp) {
    imp.onclick = () => $("#import-file").click();
    $("#import-file").onchange = async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      await api.post("/api/config/import", JSON.parse(await f.text()));
      toast("Settings imported", "ok"); route();
    };
  }

  /* The destination path preview. "Share" and "folder" only mean anything together,
     and seeing the whole thing is how somebody notices they have typed the share name
     into the folder box. */
  const tmdbTest = $("#tmdb-test");
  if (tmdbTest) tmdbTest.onclick = async () => {
    const out = $("#tmdb-test-out");
    tmdbTest.disabled = true;
    out.className = "test-out";
    out.textContent = "Asking TMDb…";
    try {
      const r = await api.post("/api/tmdb/test", { token: $("#tmdb-token").value.trim() });
      out.className = "test-out " + (r.ok ? "ok" : "bad");
      out.textContent = r.ok ? r.message + " Save to use it." : r.message;
    } catch (e) { out.className = "test-out bad"; out.textContent = e.message; }
    tmdbTest.disabled = false;
  };

  /* Naming: a preset fills the template, editing the template makes it Custom, and
     either one refreshes the preview -- debounced, since it's a round trip. */
  $$("[data-naming]").forEach(input => {
    const kind = input.dataset.naming;
    const out = $(`[data-naming-preview="${kind}"]`);
    const select = $(`[data-naming-preset="${kind}"]`);
    const presets = (state.naming && state.naming[kind]) || [];
    let timer = null;
    const preview = () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        try {
          const r = await api.post("/api/naming/preview", { template: input.value, kind });
          out.innerHTML = `${icon("folder-open")} <code>${esc(r.path)}</code>`;
        } catch (e) { out.textContent = ""; }
      }, 250);
    };
    input.addEventListener("input", () => {
      const match = presets.find(p => p.template === input.value);
      if (select) select.value = match ? match.id : "";
      preview();
    });
    if (select) select.onchange = () => {
      const p = presets.find(x => x.id === select.value);
      if (!p) return;                         // "Custom" keeps whatever is typed
      input.value = p.template;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    };
    preview();
  });

  const dests = $$("[data-dest]");
  if (dests.length) {
    const shares = state.libShares || [];
    const paint = (kind) => {
      const el = $(`[data-dest-path="${kind}"]`);
      const sel = $(`[data-dest-share="${kind}"]`);
      const fld = $(`[data-dest-folder="${kind}"]`);
      if (!el || !sel) return;
      const sh = shares.find(x => String(x.id) === sel.value);
      el.textContent = sh ? destPath(sh, fld ? fld.value : "") : "no share configured";
    };
    dests.forEach(d => {
      const kind = d.dataset.dest;
      const sel = $(`[data-dest-share="${kind}"]`);
      const fld = $(`[data-dest-folder="${kind}"]`);
      if (sel) sel.onchange = () => paint(kind);
      if (fld) fld.oninput = () => paint(kind);
    });
  }

  const addShare = $("#add-share");
  if (addShare) addShare.onclick = () => {
    const box = $("#share-add");
    box.innerHTML = `<div class="share-add"><h3>Add a share</h3>
      <p class="muted">Pick your server, then the share. Riparr writes a test file into
        the folder and reads it back before saving, so a share it can't write to fails
        now instead of at 3am on the first rip.</p>
      <div class="sf-root"></div></div>`;
    addShare.disabled = true;
    shareFinder(box.querySelector(".sf-root"), {
      askName: true,
      onSaved: () => route(),
      onCancel: () => { box.innerHTML = ""; addShare.disabled = false; },
    });
    box.scrollIntoView({ block: "start", behavior: "smooth" });
  };

  $$("[data-test-share]").forEach(b => b.onclick = async () => {
    const out = b.closest(".share-row").querySelector(".share-out");
    b.disabled = true;
    out.className = "share-out test-out";
    out.textContent = "Writing a test file and reading it back\u2026";
    try {
      const r = await api.post(`/api/shares/${b.dataset.testShare}/test`, {});
      toast(r.message, "ok");
      state.status = await api.get("/api/status").catch(() => state.status);
      renderChrome();
      route();
    } catch (e) {
      out.className = "share-out test-out bad";
      out.textContent = e.message;
      b.disabled = false;
    }
  });
  $$("[data-login-share]").forEach(b => b.onclick = () => {
    const box = b.closest(".share-row").querySelector(".share-login");
    box.hidden = !box.hidden;
    if (!box.hidden) box.querySelector(".sl-user").focus();
  });
  $$("[data-login-cancel]").forEach(b => b.onclick = () => {
    b.closest(".share-login").hidden = true;
  });
  $$("[data-login-save]").forEach(b => b.onclick = async () => {
    const row = b.closest(".share-row");
    const out = row.querySelector(".share-out");
    const pass = row.querySelector(".sl-pass").value;
    b.disabled = true;
    out.className = "share-out test-out";
    out.textContent = "Signing in and testing\u2026";
    try {
      const r = await api.put(`/api/shares/${b.dataset.loginSave}/login`, {
        username: row.querySelector(".sl-user").value.trim(),
        password: pass || "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" });
      toast(r.message, "ok");
      route();
    } catch (e) {
      out.className = "share-out test-out bad";
      out.textContent = e.message;
      b.disabled = false;
    }
  });
  // Arriving from a Fix link: straight to the share that needs it.
  const want = $(".share-row.untested");
  if (want && location.hash.endsWith("/share")) {
    want.scrollIntoView({ block: "center" });
    want.classList.add("flash");
  }
}

/* ════════════════════ chrome ════════════════════ */
/* One pill, from the same list as everything else, linking to where it's explained.
   Several pills used to sit side by side, and on a phone they pushed the header wider
   than the screen -- which made the whole page scroll sideways. */
function renderChrome() {
  const list = problems(state.status);
  const worst = list.find(p => p.level === "bad") || list[0];
  $("#health-pills").innerHTML = worst
    ? `<a class="pill ${worst.level}" href="#/system/status" title="${esc(
        list.map(p => p.short || p.message).join("\n"))}">${esc(worst.short || "Needs attention")}${
        list.length > 1 ? ` <b>and ${list.length - 1} more</b>` : ""}</a>`
    : "";
  // On a phone the sidebar (and its badge) is hidden behind the menu button.
  $("#hamburger").classList.toggle("has-issues", !!list.length);
  $("#hamburger").classList.toggle("bad", list.some(p => p.level === "bad"));
}

/* On a phone the sidebar is a drawer: closed, it is off screen and must not be in the
   tab order; open, it is a dialog that keeps focus until it's closed. On a desktop it is
   simply the sidebar. */
const drawerMode = () => matchMedia("(max-width: 820px)").matches;
function syncDrawer() {
  const sb = $("#sidebar");
  if (!sb) return;
  const open = sb.classList.contains("open");
  const drawer = drawerMode();
  sb.inert = drawer && !open;
  if (drawer && open) {
    sb.setAttribute("role", "dialog");
    sb.setAttribute("aria-modal", "true");
    sb.setAttribute("aria-label", "Menu");
  } else {
    sb.removeAttribute("role");
    sb.removeAttribute("aria-modal");
  }
}
new MutationObserver(syncDrawer).observe($("#sidebar"), { attributes: true, attributeFilter: ["class"] });
window.addEventListener("resize", syncDrawer);
syncDrawer();
document.addEventListener("keydown", (e) => {
  const sb = $("#sidebar");
  if (e.key !== "Tab" || !drawerMode() || !sb.classList.contains("open")) return;
  const items = $$("a, button", sb).filter(x => x.offsetParent !== null);
  if (!items.length) return;
  const first = items[0], last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  else if (!sb.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
});

$("#hamburger").onclick = (e) => {
  e.stopPropagation();
  const open = $("#sidebar").classList.toggle("open");
  document.body.classList.toggle("nav-open", open);
  $("#hamburger").setAttribute("aria-expanded", String(open));
};
// On a phone the menu covers the page; a tap anywhere outside it puts it away.
document.addEventListener("click", (e) => {
  const sb = $("#sidebar");
  if (sb && sb.classList.contains("open") && !sb.contains(e.target)) {
    sb.classList.remove("open");
    document.body.classList.remove("nav-open");
    $("#hamburger").setAttribute("aria-expanded", "false");
  }
});
$("#user-btn").onclick = (e) => {
  e.stopPropagation();
  const hidden = $("#user-menu").classList.toggle("hidden");
  $("#user-btn").setAttribute("aria-expanded", String(!hidden));
};
document.addEventListener("click", () => {
  $("#user-menu")?.classList.add("hidden");
  $("#user-btn")?.setAttribute("aria-expanded", "false");
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if ($("#sidebar").classList.contains("open")) {
    $("#sidebar").classList.remove("open");
    document.body.classList.remove("nav-open");
    $("#hamburger").setAttribute("aria-expanded", "false");
    const more = $("#tab-more");
    if (more) more.setAttribute("aria-expanded", "false");
    (more || $("#hamburger")).focus();
    return;
  }
  if (!$("#user-menu").classList.contains("hidden")) {
    $("#user-menu").classList.add("hidden");
    $("#user-btn").setAttribute("aria-expanded", "false");
    $("#user-btn").focus();
  }
});

/* ── search ──
   Finds a film on the two pages that list them: Discs and History. Typing anywhere
   else goes to Discs, the shelf of everything Riparr has ripped, and filters it. */
const search = $("#search");
function applySearch() {
  const q = onListPage() ? search.value.trim().toLowerCase() : "";
  const items = $$("[data-find]", $("#content"));
  if (!items.length) return;
  let shown = 0;
  items.forEach(el => {
    // Discs' kind filter still applies while searching.
    const kindOk = !el.dataset.kind || !state.discsKind || el.dataset.kind === state.discsKind;
    const hit = kindOk && (!q || el.dataset.find.toLowerCase().includes(q));
    el.hidden = !hit;
    if (hit && !el.classList.contains("hist-dest")) shown++;
  });
  let none = $("#search-none");
  if (q && !shown) {
    if (!none) {
      none = document.createElement("p");
      none.id = "search-none";
      none.className = "muted search-none";
      // Next to the list, not at the bottom of the page under everything else.
      const list = $(".rips") || $(".hist-table");
      (list ? (list.closest(".card") || list) : $("#content").lastElementChild)
        .insertAdjacentElement("afterend", none);
    }
    none.textContent = `Nothing matches \u201c${search.value.trim()}\u201d.`;
  } else if (none) none.remove();
}
const onListPage = () => ["discs", "history"].includes(
  location.hash.replace(/^#\//, "").split("/")[0]);

// On a phone the box is folded into a button; tapping it opens the box over the header.
const searchToggle = $("#search-toggle");
const searchOpen = (open) => {
  $(".topbar").classList.toggle("searching", open);
  searchToggle.setAttribute("aria-expanded", String(open));
  if (open) search.focus();
};
searchToggle.onclick = () => searchOpen(!$(".topbar").classList.contains("searching"));
search.addEventListener("blur", () => { if (!search.value) searchOpen(false); });
search.addEventListener("input", () => { if (onListPage()) applySearch(); });
search.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { search.value = ""; applySearch(); search.blur(); }
  // Typing never takes you anywhere; Enter on another page opens Discs, filtered.
  if (e.key === "Enter" && search.value.trim() && !onListPage()) location.hash = "#/discs";
});

/* ── unsaved settings ──
   Settings pages save with one button, so a change can be left behind by clicking
   away. The snapshot is taken when the page is wired; anything different from it
   is unsaved, and leaving asks first. */
let settingsSnapshot = null;
const settingsDirty = () => settingsSnapshot !== null
  && JSON.stringify(collectSettings()) !== settingsSnapshot;

function markDirty() {
  const bar = $("#save-bar");
  if (!bar) return;
  const dirty = settingsDirty();
  bar.classList.toggle("dirty", dirty);
  document.body.classList.toggle("has-savebar", dirty);
  $("#save-state").textContent = dirty ? "You have unsaved changes" : "No unsaved changes";
  $("#discard-settings").hidden = !dirty;
}

$("#content").addEventListener("input", markDirty);
$("#content").addEventListener("change", markDirty);

let currentHash = location.hash;
window.addEventListener("hashchange", () => {
  // A dialog belongs to the page it was opened on.
  document.querySelectorAll("dialog.disc-dlg[open]").forEach(d => { d.close(); d.remove(); });
  if (settingsDirty() && !confirm("You have unsaved changes on this page.\n\nLeave without saving them?")) {
    // Put the address back without routing: the page is still the one with the edits.
    history.replaceState(null, "", currentHash || "#/queue");
    return;
  }
  settingsSnapshot = null;
  currentHash = location.hash;
  window.scrollTo(0, 0);
  route();
});
window.addEventListener("beforeunload", (e) => {
  if (settingsDirty()) { e.preventDefault(); e.returnValue = ""; }
});
$("#logout").onclick = async (e) => {
  e.preventDefault();
  await api.post("/api/auth/logout");
  location.reload();
};

$("#gate-retry").onclick = () => location.reload();

/* ════════════════════ boot ════════════════════ */
/* The service takes a moment to answer after the box powers on, and the page is very
   often loaded during exactly that window. Treating a failed fetch as "sign in" is
   the most misleading answer available: a login form asserts that an account exists,
   which sends people off to reset a password they never set — or to reflash a card
   that was working perfectly. Wait, say so, and only then give up. */
function showWaiting(msg, { retry = false, spin = true } = {}) {
  $("#shell").classList.add("hidden");
  $("#wizard").classList.add("hidden");
  $("#gate").classList.remove("hidden");
  $("#login-form").classList.add("hidden");
  $("#gate-waiting").classList.remove("hidden");
  $("#gate-wait-msg").textContent = msg;
  $("#gate-spin").classList.toggle("hidden", !spin);
  $("#gate-retry").classList.toggle("hidden", !retry);
}

function hideWaiting() {
  $("#gate-waiting").classList.add("hidden");
  $("#login-form").classList.remove("hidden");
}

const showStarting = (attempt) => showWaiting(
  attempt < 3 ? "Starting up…"
              : "Still starting — this can take a minute after power-on.");

const showUnreachable = () => showWaiting(
  "Can't reach Riparr. It may still be starting; if this keeps happening, "
  + "check `docker logs riparr` on the server (or `journalctl -u riparr` without Docker).",
  { retry: true, spin: false });

/* Tabs at the bottom of a phone, where a thumb reaches, instead of a menu button in the
   top corner. More opens the same drawer the menu button did, with Settings and System
   in it, and carries the dot when something needs attention. Shown by CSS only in the
   new layout and only on narrow screens. */
const TABS = [["queue", "Queue", "play"], ["history", "History", "clock-rotate-left"],
              ["discs", "Discs", "compact-disc"]];
function renderTabs(section) {
  let bar = $("#tabs");
  if (!bar) {
    bar = document.createElement("nav");
    bar.id = "tabs";
    bar.className = "tabbar";
    bar.setAttribute("aria-label", "Sections");
    $("#shell").append(bar);
  }
  section = section || (location.hash.replace(/^#\//, "").split("/")[0] || "queue");
  const issues = problems(state.status).length;
  bar.innerHTML = TABS.map(([id, label, ic]) =>
    `<a href="#/${id}" class="tab${section === id ? " on" : ""}"${
      section === id ? ` aria-current="page"` : ""}>${icon(ic)}<span>${label}${
      id === "queue" && state.asking ? `<span class="sr-only">, needs you</span>` : ""}</span>${
      id === "queue" && state.asking ? `<i class="tab-dot ask" aria-hidden="true"></i>` : ""}</a>`).join("")
    + `<button type="button" class="tab${["settings", "system"].includes(section) ? " on" : ""}"
         id="tab-more" aria-controls="sidebar" aria-expanded="false" aria-haspopup="true"${
         ["settings", "system"].includes(section) ? ` aria-current="page"` : ""}>${icon("bars")}<span>More${
         issues ? `<span class="sr-only">, ${issues} need${issues === 1 ? "s" : ""} attention</span>` : ""}</span>${
         issues ? `<i class="tab-dot" aria-hidden="true"></i>` : ""}</button>`;
  paintIcons(bar);
  $("#tab-more").onclick = (e) => {
    e.stopPropagation();
    const open = $("#sidebar").classList.toggle("open");
    document.body.classList.toggle("nav-open", open);
    $("#tab-more").setAttribute("aria-expanded", String(open));
    syncDrawer();          // not inert any more, before focus goes in
    // Into the drawer, at its first item that isn't already a tab.
    if (open) {
      const first = $$("#sidebar a").find(a => a.offsetParent !== null);
      if (first) first.focus();
    }
  };
}

async function boot() {
  paintIcons();          // the static chrome in index.html
  let setup;
  for (let attempt = 0; ; attempt++) {
    try { setup = await api.get("/api/setup/state"); break; }
    catch (e) {
      // A real 401 already showed the gate and means something quite different.
      if (e.message === "Not signed in") return;
      if (attempt >= 8) { showUnreachable(); return; }
      showStarting(attempt);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  hideWaiting();
  // Before sign-in, so the sign-in page is drawn in it too.
  if (setup.theme) applyTheme(setup.theme);

  if (!setup.has_users) { wizard.step = 0; wizard.render(); return; }

  let me;
  try { me = await api.get("/api/auth/me"); } catch (e) { showGate(); return; }
  if (!me.username) { showGate(); return; }
  $("#menu-who").textContent = me.username;

  if (!setup.complete) {
    wizard.step = 1;                       // account exists; resume at MakeMKV
    wizard.render();
    return;
  }

  try { state.status = await api.get("/api/status"); }
  catch (e) { showGate(); return; }
  state.settings = await api.get("/api/settings");
  applyTheme(state.settings.theme || "servarr");
  document.body.classList.add("ui-new");
  renderTabs();

  $("#gate").classList.add("hidden");
  $("#wizard").classList.add("hidden");
  $("#shell").classList.remove("hidden");
  renderChrome();
  // A build started during setup outlives the wizard, and the queue page is where people
  // land afterwards wondering why Auto Rip is still greyed out.
  if (!location.hash) location.hash = "#/queue";
  route();
  showRenewalNotice();
}

boot();
