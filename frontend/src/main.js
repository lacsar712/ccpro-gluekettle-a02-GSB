import "./style.css";

const TOKEN_KEY = "gluekettle_token";
const LABELS = { cold: "冷锅", boiling: "熬煮中", drawn: "已出胶" };

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

const app = document.getElementById("app");
const state = {
  ready: Boolean(localStorage.getItem(TOKEN_KEY)),
  view: "board",
  board: null,
  picked: null,
  peak: "96",
  err: "",
  ok: "",
  username: "admin",
  password: "123456",
  ash: { tickets: null, kettleFilter: "", formKettle: "", ticketNo: "", err: "" },
};

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("zh-CN", { hour12: false });
}

async function refreshBoard() {
  state.board = await api("/api/board");
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || null;
  }
}

async function refreshAsh() {
  const qs = state.ash.kettleFilter ? `?kettle_id=${encodeURIComponent(state.ash.kettleFilter)}` : "";
  const data = await api(`/api/ash-tickets${qs}`);
  state.ash.tickets = data.tickets;
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    renderLogin();
    return;
  }
  if (!state.board) {
    app.append(el(`<div class="wrap">${state.err || "装载锅位…"}</div>`));
    return;
  }
  const box = el(`<div class="wrap">
    <nav class="topnav">
      <span class="brand">🫕 ${esc(state.board.workshop)}</span>
      <button class="navbtn" data-view="board">锅位作业台</button>
      <button class="navbtn" data-view="ash">清灰单</button>
    </nav>
    <p class="${state.err ? "err" : "ok"}">${esc(state.err || state.ok)}</p>
    <div class="view"></div>
  </div>`);
  box.querySelectorAll(".navbtn").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === state.view);
    b.onclick = async () => {
      state.view = b.dataset.view;
      state.err = "";
      state.ok = "";
      try {
        if (state.view === "ash" && state.ash.tickets === null) await refreshAsh();
        render();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
  });
  const view = box.querySelector(".view");
  if (state.view === "ash") view.append(buildAshPage());
  else view.append(buildBoardPage());
  app.append(box);
}

function renderLogin() {
  const box = el(`<div class="wrap">
    <h1>骨巷熬胶坊</h1>
    <p>一排熬锅作业台，原生页面，无前端框架。</p>
    <form autocomplete="off">
      <label>用户名
        <input name="u" autocomplete="off" value="${esc(state.username)}" />
      </label>
      <label>密码
        <input name="p" type="password" autocomplete="off" value="${esc(state.password)}" />
      </label>
      <p class="hint">已预填 admin / 123456，另有 worker / 123456</p>
      <button>登录</button>
    </form>
    <p class="err">${esc(state.err)}</p>
  </div>`);
  box.querySelector("form").onsubmit = async (e) => {
    e.preventDefault();
    state.err = "";
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: box.querySelector("[name=u]").value,
          password: box.querySelector("[name=p]").value,
        }),
      });
      localStorage.setItem(TOKEN_KEY, data.access_token);
      state.ready = true;
      await refreshBoard();
      render();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  app.append(box);
}

function buildBoardPage() {
  const page = el(`<div>
    <p>${esc(state.board.alley)} · 点锅登记峰值；冷锅改熬煮中须先有未核销清灰单；出胶只看最近峰值 ≥ 90℃</p>
    <div class="row"></div>
    <section class="drawer"></section>
  </div>`);
  const row = page.querySelector(".row");
  state.board.kettles.forEach((k) => {
    const btn = el(`<button class="kettle ${k.status}${state.picked && state.picked.id === k.id ? " picked" : ""}"><strong>${esc(k.code)}</strong><span>${LABELS[k.status]}</span></button>`);
    btn.onclick = () => {
      state.picked = k;
      render();
    };
    row.append(btn);
  });
  const d = page.querySelector(".drawer");
  if (!state.picked) {
    d.innerHTML = `<p class="hint">点上方锅位查看作业抽屉。</p>`;
    return page;
  }
  const k = state.picked;
  d.innerHTML = `<h3>${esc(k.code)} · ${LABELS[k.status]}</h3>
    <p>最近峰值：${k.latestPeakC ?? "无"} ℃ · ${k.cookCount} 次</p>
    <input id="peak" value="${esc(state.peak)}" />
    <button id="log">登记峰值</button>
    <div>
      <button data-s="cold">冷锅</button>
      <button data-s="boiling">熬煮中</button>
      <button data-s="drawn">已出胶</button>
    </div>`;
  d.querySelector("#log").onclick = async () => {
    state.peak = d.querySelector("#peak").value;
    state.err = "";
    state.ok = "";
    try {
      state.picked = await api(`/api/kettles/${k.id}/cooks`, {
        method: "POST",
        body: JSON.stringify({ peakTempC: Number(state.peak) }),
      });
      await refreshBoard();
      render();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  d.querySelectorAll("[data-s]").forEach((b) => {
    b.onclick = async () => {
      state.err = "";
      state.ok = "";
      try {
        state.picked = await api(`/api/kettles/${k.id}/status`, {
          method: "POST",
          body: JSON.stringify({ status: b.dataset.s }),
        });
        state.ok = `${k.code} 已改为${LABELS[b.dataset.s]}`;
        await refreshBoard();
        render();
      } catch (ex) {
        // 无未核销清灰单时由服务端中文挡下，直接展示。
        state.err = ex.message;
        render();
      }
    };
  });
  return page;
}

function buildAshPage() {
  const options = state.board.kettles
    .map((k) => `<option value="${k.id}" ${String(k.id) === state.ash.formKettle ? "selected" : ""}>${esc(k.code)}（${LABELS[k.status]}）</option>`)
    .join("");
  const filterOptions =
    `<option value="">全部锅</option>` +
    state.board.kettles
      .map((k) => `<option value="${k.id}" ${String(k.id) === state.ash.kettleFilter ? "selected" : ""}>${esc(k.code)}</option>`)
      .join("");
  const page = el(`<div class="ash">
    <h3>灶膛清灰单</h3>
    <p class="hint">同一锅同时只能挂一张未核销单；冷锅改熬煮中时会读取该单。</p>
    <form class="ash-form" autocomplete="off">
      <label>锅
        <select name="kettle">${options}</select>
      </label>
      <label>单号（正整数）
        <input name="no" type="number" min="1" step="1" value="${esc(state.ash.ticketNo)}" />
      </label>
      <button>开单</button>
    </form>
    <div class="ash-filter">
      <label>按锅筛选
        <select name="filter">${filterOptions}</select>
      </label>
    </div>
    <p class="err">${esc(state.ash.err)}</p>
    <div class="ticket-list"></div>
  </div>`);

  const formKettleSel = page.querySelector(".ash-form [name=kettle]");
  state.ash.formKettle = state.ash.formKettle || formKettleSel.value;
  formKettleSel.value = state.ash.formKettle;

  page.querySelector(".ash-form").onsubmit = async (e) => {
    e.preventDefault();
    state.ash.err = "";
    const kettleId = formKettleSel.value;
    const rawNo = page.querySelector(".ash-form [name=no]").value.trim();
    const ticketNo = Number(rawNo);
    if (!/^\d+$/.test(rawNo) || !Number.isInteger(ticketNo) || ticketNo <= 0) {
      state.ash.err = "单号必须为正整数";
      render();
      return;
    }
    state.ash.formKettle = kettleId;
    state.ash.ticketNo = rawNo;
    try {
      await api(`/api/kettles/${kettleId}/ash-tickets`, {
        method: "POST",
        body: JSON.stringify({ ticketNo }),
      });
      state.ash.kettleFilter = "";
      state.ash.ticketNo = "";
      await refreshAsh();
      render();
    } catch (ex) {
      state.ash.err = ex.message;
      render();
    }
  };

  const filterSel = page.querySelector(".ash-filter [name=filter]");
  filterSel.value = state.ash.kettleFilter;
  filterSel.onchange = async () => {
    state.ash.kettleFilter = filterSel.value;
    state.ash.err = "";
    try {
      await refreshAsh();
      render();
    } catch (ex) {
      state.ash.err = ex.message;
      render();
    }
  };

  const list = page.querySelector(".ticket-list");
  const tickets = state.ash.tickets || [];
  if (tickets.length === 0) {
    list.innerHTML = `<p class="hint">当前没有未核销清灰单。</p>`;
    return page;
  }
  tickets.forEach((t) => {
    const rowEl = el(`<div class="ticket">
      <span class="t-kettle">${esc(t.kettleCode)}</span>
      <span>单号 #${t.ticketNo}</span>
      <span>清灰人：${esc(t.cleanedBy)}</span>
      <span>清灰时刻：${fmtTime(t.cleanedAt)}</span>
      <button data-id="${t.id}">核销</button>
    </div>`);
    rowEl.querySelector("button").onclick = async () => {
      state.ash.err = "";
      try {
        await api(`/api/ash-tickets/${t.id}/redeem`, { method: "POST" });
        await refreshAsh();
        render();
      } catch (ex) {
        state.ash.err = ex.message;
        render();
      }
    };
    list.append(rowEl);
  });
  return page;
}

async function boot() {
  if (!state.ready) {
    render();
    return;
  }
  try {
    await refreshBoard();
    render();
  } catch (e) {
    state.err = e.message;
    render();
  }
}

boot();
