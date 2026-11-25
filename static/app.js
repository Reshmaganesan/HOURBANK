(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const state = { me: null, members: [], cats: [], type: "", cat: "", q: "", postType: "offer", tab: "market" };

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => (Math.round(n * 10) / 10).toString();
  const ago = (ts) => {
    const d = Math.max(1, Math.floor(Date.now() / 1000 - ts));
    if (d < 3600) return Math.ceil(d / 60) + " min ago";
    if (d < 86400) return Math.floor(d / 3600) + " h ago";
    return Math.floor(d / 86400) + " d ago";
  };

  async function api(path, opts = {}) {
    const res = await fetch("/api" + path, {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json" },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Something went wrong");
    return data;
  }

  let toastTimer;
  function toast(msg, isErr) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "toast show" + (isErr ? " err" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.className = "toast"), 3200);
  }
  const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };

  /* ---------- modal ---------- */
  function openModal(html) { $("#modalBox").innerHTML = html; $("#modal").hidden = false; }
  function closeModal() { $("#modal").hidden = true; }
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

  /* ---------- header / stats ---------- */
  async function loadStats() {
    const s = await api("/stats");
    state.cats = s.categories;
    $("#stats").innerHTML = [
      [s.members, "members"], [fmt(s.hours_exchanged), "hours exchanged"],
      [s.exchanges, "completed swaps"], [s.open_listings, "open listings"],
    ].map(([n, l]) => `<div class="stat"><b>${esc(n)}</b><span>${l}</span></div>`).join("");
  }

  async function loadMembers() {
    state.members = await api("/members");
    const saved = Number(localStorage.getItem("hb_me"));
    state.me = state.members.find((m) => m.id === saved)?.id || state.members[0].id;
    $("#me").innerHTML = state.members.map((m) => `<option value="${m.id}">${esc(m.emoji)} ${esc(m.name)}</option>`).join("");
    $("#me").value = state.me;
    updateBalance();
  }
  function updateBalance() {
    const m = state.members.find((x) => x.id === state.me);
    $("#balance").textContent = `⏳ ${fmt(m.balance)} h`;
  }
  async function refreshMembers() { state.members = await api("/members"); updateBalance(); }
  $("#me").addEventListener("change", (e) => {
    state.me = Number(e.target.value);
    localStorage.setItem("hb_me", state.me);
    updateBalance();
    render();
  });

  /* ---------- tabs ---------- */
  $("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    show(b.dataset.tab);
  });
  function show(tab) {
    state.tab = tab;
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== "tab-" + tab));
    render();
  }
  const render = guard(async () => {
    await ({ market: renderMarket, mine: renderMine, community: renderCommunity, post: renderPost })[state.tab]();
  });

  /* ---------- marketplace ---------- */
  function renderCats() {
    $("#cats").innerHTML = ["", ...state.cats].map((c) =>
      `<button data-cat="${esc(c)}" class="${c === state.cat ? "active" : ""}">${c || "All categories"}</button>`).join("");
  }
  $("#cats").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    state.cat = b.dataset.cat; renderMarket();
  });
  $("#typeSeg").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    state.type = b.dataset.type;
    document.querySelectorAll("#typeSeg button").forEach((x) => x.classList.toggle("active", x === b));
    renderMarket();
  });
  let searchTimer;
  $("#search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.q = e.target.value; renderMarket(); }, 250);
  });

  async function renderMarket() {
    renderCats();
    const p = new URLSearchParams({ type: state.type, category: state.cat, q: state.q });
    const list = await api("/listings?" + p);
    $("#listings").innerHTML = list.length ? list.map(listingCard).join("")
      : `<div class="empty" style="grid-column:1/-1">Nothing matches yet. Be the first to post one.</div>`;
  }
  function listingCard(l) {
    const mine = l.member_id === state.me;
    const verb = l.type === "offer" ? "Book this" : "I can help";
    return `<article class="card listing">
      <div class="meta"><span class="tag ${l.type}">${l.type === "offer" ? "Offering" : "Needs help"}</span><span class="hrs">${fmt(l.hours)} h</span></div>
      <h3>${esc(l.title)}</h3>
      <p>${esc(l.description)}</p>
      <div class="meta"><div class="owner"><span class="avatar">${esc(l.owner_emoji)}</span><span>${esc(l.owner_name)}<br><small>${esc(l.owner_city)} · ${esc(l.category)}</small></span></div>
      ${mine ? `<span class="pill">Your listing</span>` : `<button class="btn primary" data-accept="${l.id}" data-title="${esc(l.title)}" data-hours="${l.hours}" data-type="${l.type}" data-owner="${esc(l.owner_name)}">${verb}</button>`}</div>
    </article>`;
  }
  $("#listings").addEventListener("click", (e) => {
    const b = e.target.closest("[data-accept]"); if (!b) return;
    const d = b.dataset, offer = d.type === "offer";
    openModal(`<h2 style="margin:0">${offer ? "Book" : "Help with"} “${esc(d.title)}”?</h2>
      <p style="margin:0;color:var(--muted)">${offer
        ? `You will spend <b>${fmt(d.hours)} h</b> from your balance once you confirm you received the help.`
        : `You will earn <b>${fmt(d.hours)} h</b> after ${esc(d.owner)} confirms you helped.`}
        Arrange the time and place directly with ${esc(d.owner)}.</p>
      <div class="acts"><button class="btn" data-close>Not now</button><button class="btn primary" id="confirmAccept" data-id="${d.accept}">Confirm</button></div>`);
  });
  $("#modalBox").addEventListener("click", guard(async (e) => {
    if (e.target.closest("[data-close]")) return closeModal();
    const ok = e.target.closest("#confirmAccept");
    if (ok) {
      await api(`/listings/${ok.dataset.id}/accept`, { method: "POST", body: { member_id: state.me } });
      closeModal(); toast("Booked! Find it under My Hours."); await afterChange(); return;
    }
    const done = e.target.closest("#confirmDone");
    if (done) {
      await api(`/exchanges/${done.dataset.id}/complete`, { method: "POST", body: { member_id: state.me, thanks: $("#thanks").value } });
      closeModal(); toast("Hours transferred. Thank you!"); await afterChange();
    }
  }));
  async function afterChange() { await Promise.all([refreshMembers(), loadStats()]); render(); }

  /* ---------- my hours ---------- */
  async function renderMine() {
    const m = await api("/members/" + state.me);
    const pend = m.exchanges.filter((e) => e.status === "pending");
    const hist = m.exchanges.filter((e) => e.status === "completed");
    const given = hist.filter((e) => e.provider_id === m.id).reduce((a, e) => a + e.hours, 0);
    const got = hist.filter((e) => e.receiver_id === m.id).reduce((a, e) => a + e.hours, 0);
    const exRow = (e) => {
      const iProvide = e.provider_id === m.id;
      const other = iProvide ? `${e.receiver_emoji} ${e.receiver_name}` : `${e.provider_emoji} ${e.provider_name}`;
      const action = e.status === "pending"
        ? `<div class="actions">${!iProvide ? `<button class="btn primary" data-done="${e.id}" data-title="${esc(e.title)}">Mark received</button>` : `<span class="pill pending">Waiting for ${esc(e.receiver_name)}</span>`}<button class="btn danger" data-cancel="${e.id}">Cancel</button></div>`
        : `<span class="${iProvide ? "plus" : "minus"}">${iProvide ? "+" : "−"}${fmt(e.hours)} h</span>`;
      return `<div class="card rowcard"><div><b>${esc(e.title)}</b><br><small style="color:var(--muted)">${iProvide ? "You helped" : "Helped by"} ${esc(other)} · ${fmt(e.hours)} h · <span class="pill ${e.status}">${e.status}</span>${e.thanks ? `<br><i>“${esc(e.thanks)}”</i>` : ""}</small></div>${action}</div>`;
    };
    $("#tab-mine").innerHTML = `
      <div class="card big" style="margin-top:20px"><span class="avatar" style="width:64px;height:64px;font-size:2rem">${esc(m.emoji)}</span>
        <div><div class="num">${fmt(m.balance)} h</div><small>${esc(m.name)} · ${esc(m.city)}</small></div>
        <div style="margin-left:auto;text-align:right"><small>Given</small><b class="plus"> +${fmt(given)} h</b><br><small>Received</small><b class="minus"> −${fmt(got)} h</b></div></div>
      <h2>In progress</h2><div class="rows">${pend.map(exRow).join("") || `<div class="empty">No active swaps. Browse the marketplace to start one.</div>`}</div>
      <h2>Your listings</h2><div class="grid">${m.listings.filter((l) => l.status !== "done").map(listingCard).join("") || `<div class="empty" style="grid-column:1/-1">You have not posted anything yet.</div>`}</div>
      <h2>History</h2><div class="rows">${hist.map(exRow).join("") || `<div class="empty">Completed swaps will appear here.</div>`}</div>`;
  }
  $("#tab-mine").addEventListener("click", guard(async (e) => {
    const done = e.target.closest("[data-done]");
    if (done) {
      openModal(`<h2 style="margin:0">Confirm you received help</h2><p style="margin:0;color:var(--muted)">“${esc(done.dataset.title)}”. This transfers the hours.</p>
        <label style="font-weight:600">Say thanks (optional)<input id="thanks" maxlength="200" placeholder="It was great because…"></label>
        <div class="acts"><button class="btn" data-close>Back</button><button class="btn primary" id="confirmDone" data-id="${done.dataset.done}">Confirm & transfer</button></div>`);
      return;
    }
    const c = e.target.closest("[data-cancel]");
    if (c) { await api(`/exchanges/${c.dataset.cancel}/cancel`, { method: "POST", body: { member_id: state.me } }); toast("Swap cancelled."); await afterChange(); }
  }));

  /* ---------- community ---------- */
  async function renderCommunity() {
    const [members, act] = await Promise.all([api("/members"), api("/activity")]);
    const top = [...members].sort((a, b) => b.hours_given - a.hours_given).slice(0, 5);
    $("#leaders").innerHTML = top.map((m, i) => `<li><span class="rank">${i + 1}</span><span class="avatar">${esc(m.emoji)}</span><span class="grow"><b>${esc(m.name)}</b><br><small style="color:var(--muted)">${esc(m.city)}</small></span><span class="hrs">${fmt(m.hours_given)} h given</span></li>`).join("");
    $("#activity").innerHTML = act.map((e) => `<div class="card"><b>${esc(e.provider_emoji)} ${esc(e.provider_name)}</b> helped <b>${esc(e.receiver_emoji)} ${esc(e.receiver_name)}</b> with ${esc(e.title)} <span class="hrs">${fmt(e.hours)} h</span>${e.thanks ? `<q>${esc(e.thanks)}</q>` : ""}<small style="color:var(--muted)">${ago(e.completed_at)}</small></div>`).join("");
    $("#members").innerHTML = members.map((m) => `<div class="card"><div class="owner"><span class="avatar">${esc(m.emoji)}</span><b>${esc(m.name)}</b></div><small style="color:var(--muted)">${esc(m.city)}</small><p style="margin:8px 0 0;font-size:.92rem">${esc(m.bio)}</p></div>`).join("");
  }

  /* ---------- post ---------- */
  function renderPost() {
    $("#postCat").innerHTML = state.cats.map((c) => `<option>${esc(c)}</option>`).join("");
  }
  $("#postType").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    state.postType = b.dataset.type;
    document.querySelectorAll("#postType button").forEach((x) => x.classList.toggle("active", x === b));
  });
  $("#postForm").addEventListener("submit", guard(async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    await api("/listings", { method: "POST", body: { ...f, type: state.postType, member_id: state.me } });
    e.target.reset(); toast("Published!"); await loadStats(); show("market");
  }));

  /* ---------- boot ---------- */
  guard(async () => { await loadStats(); await loadMembers(); show("market"); })();
})();
