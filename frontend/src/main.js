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
  tickets: null,
  ashFilter: "",
  ticketNo: "",
  cleaner: "",
  formKettleId: "",
  err: "",
  username: "admin",
  password: "123456",
};

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false });
}

async function refreshBoard() {
  state.board = await api("/api/board");
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || state.picked;
  }
}

async function refreshTickets() {
  const qs = state.ashFilter ? `?kettle_id=${encodeURIComponent(state.ashFilter)}` : "";
  const data = await api(`/api/ash-tickets${qs}`);
  state.tickets = data.tickets;
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
    <h1>${state.board.workshop}</h1>
    <nav class="topbar">
      <button data-v="board" class="${state.view === "board" ? "active" : ""}">锅位作业台</button>
      <button data-v="ash" class="${state.view === "ash" ? "active" : ""}">灶膛清灰单</button>
      <button id="logout" class="ghost">退出</button>
    </nav>
    <div class="view"></div>
    <p class="err">${state.err}</p>
  </div>`);
  box.querySelectorAll(".topbar [data-v]").forEach((b) => {
    b.onclick = async () => {
      state.view = b.dataset.v;
      state.err = "";
      if (state.view === "ash" && state.tickets === null) {
        try {
          await refreshTickets();
        } catch (ex) {
          state.err = ex.message;
        }
      }
      render();
    };
  });
  box.querySelector("#logout").onclick = () => {
    localStorage.removeItem(TOKEN_KEY);
    state.ready = false;
    state.board = null;
    state.tickets = null;
    render();
  };
  const view = box.querySelector(".view");
  if (state.view === "ash") {
    renderAsh(view);
  } else {
    renderBoard(view);
  }
  app.append(box);
}

function renderLogin() {
  const box = el(`<div class="wrap">
    <h1>骨巷熬胶坊</h1>
    <p>一排熬锅作业台，原生页面，无前端框架。</p>
    <form autocomplete="off">
      <label>用户名
        <input name="u" autocomplete="off" value="${state.username}" />
      </label>
      <label>密码
        <input name="p" type="password" autocomplete="off" value="${state.password}" />
      </label>
      <p class="hint">已预填 admin / 123456，另有 worker / 123456</p>
      <button>登录</button>
    </form>
    <p class="err">${state.err}</p>
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

function renderBoard(view) {
  view.append(el(`<p>${state.board.alley} · 点锅登记峰值；冷锅改熬煮中须挂未核销清灰单；出胶须最近峰值 ≥ 90℃</p>`));
  const row = el(`<div class="row"></div>`);
  state.board.kettles.forEach((k) => {
    const mark = k.openAshTicket ? `<em class="ticketmark">单</em>` : "";
    const btn = el(`<button class="kettle ${k.status}">${mark}<strong>${k.code}</strong><span>${LABELS[k.status]}</span></button>`);
    btn.onclick = () => {
      state.picked = k;
      render();
    };
    row.append(btn);
  });
  view.append(row);
  if (state.picked) {
    view.append(renderDrawer());
  }
}

function renderDrawer() {
  const k = state.picked;
  const t = k.openAshTicket;
  const ticketLine = t
    ? `<p class="open-ticket">未核销清灰单：单号 ${t.ticketNo} · 清灰人 ${t.cleaner || "—"} · ${fmtTime(t.cleanedAt)}</p>`
    : `<p class="no-ticket">该锅当前无未核销清灰单，冷锅不能改成熬煮中</p>`;
  const d = el(`<section class="drawer">
    <h3>${k.code} · ${LABELS[k.status]}</h3>
    <p>最近峰值：${k.latestPeakC ?? "无"} ℃ · ${k.cookCount} 次</p>
    ${ticketLine}
    <input id="peak" value="${state.peak}" />
    <button id="log">登记峰值</button>
    <div>
      <button data-s="cold">冷锅</button>
      <button data-s="boiling">熬煮中</button>
      <button data-s="drawn">已出胶</button>
    </div>
  </section>`);
  d.querySelector("#log").onclick = async () => {
    state.err = "";
    state.peak = d.querySelector("#peak").value;
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
      try {
        state.picked = await api(`/api/kettles/${k.id}/status`, {
          method: "POST",
          body: JSON.stringify({ status: b.dataset.s }),
        });
        // 状态变化会影响未核销单/锅位展示，一并刷新清灰单列表。
        await Promise.all([refreshBoard(), state.tickets !== null ? refreshTickets() : Promise.resolve()]);
        render();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
  });
  return d;
}

function kettleOptions(selected) {
  return state.board.kettles
    .map((k) => `<option value="${k.id}" ${String(k.id) === String(selected) ? "selected" : ""}>${k.code}（${LABELS[k.status]}）</option>`)
    .join("");
}

function renderAsh(view) {
  const wrap = el(`<section class="ashpage">
    <h3>灶膛清灰单</h3>
    <p class="hint">同一锅同时最多挂一张未核销单；冷锅改熬煮中时必须有未核销单。</p>
    <form class="ash-form" autocomplete="off">
      <label>锅
        <select name="kettleId">${kettleOptions(state.formKettleId || state.board.kettles[0].id)}</select>
      </label>
      <label>单号（正整数）
        <input name="ticketNo" inputmode="numeric" value="${state.ticketNo}" placeholder="如 1001" />
      </label>
      <label>清灰人
        <input name="cleaner" value="${state.cleaner}" placeholder="留空取当前操作工" />
      </label>
      <button id="open-ticket">开单</button>
    </form>
    <div class="ash-filter">
      <label>按锅筛选
        <select id="ashFilter">
          <option value="">全部锅</option>
          ${kettleOptions(state.ashFilter)}
        </select>
      </label>
    </div>
    <div class="ticket-list"><p class="hint">载入中…</p></div>
  </section>`);

  wrap.querySelector(".ash-form").onsubmit = async (e) => {
    e.preventDefault();
    state.err = "";
    const f = e.currentTarget;
    const payload = {
      kettleId: Number(f.kettleId.value),
      ticketNo: Number(f.ticketNo.value),
      cleaner: f.cleaner.value.trim(),
    };
    if (!Number.isInteger(payload.ticketNo) || payload.ticketNo <= 0) {
      state.err = "单号须为正整数";
      render();
      return;
    }
    try {
      await api("/api/ash-tickets", { method: "POST", body: JSON.stringify(payload) });
      state.ticketNo = "";
      state.cleaner = "";
      state.formKettleId = f.kettleId.value;
      await Promise.all([refreshBoard(), refreshTickets()]);
      render();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };

  wrap.querySelector("#ashFilter").onchange = async (e) => {
    state.err = "";
    state.ashFilter = e.target.value;
    try {
      await refreshTickets();
      render();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };

  const list = wrap.querySelector(".ticket-list");
  if (!state.tickets) {
    list.innerHTML = `<p class="hint">载入中…</p>`;
  } else if (state.tickets.length === 0) {
    list.innerHTML = `<p class="hint">暂无未核销清灰单</p>`;
  } else {
    state.tickets.forEach((t) => {
      const rowEl = el(`<div class="ticket-row">
        <span class="tk-kettle">${t.kettleCode || `锅#${t.kettleId}`}</span>
        <span class="tk-no">单号 ${t.ticketNo}</span>
        <span class="tk-who">清灰人 ${t.cleaner || "—"}</span>
        <span class="tk-time">${fmtTime(t.cleanedAt)}</span>
        <button class="redeem">核销</button>
      </div>`);
      rowEl.querySelector(".redeem").onclick = async () => {
        state.err = "";
        try {
          await api(`/api/ash-tickets/${t.id}/redeem`, { method: "POST" });
          await Promise.all([refreshBoard(), refreshTickets()]);
          render();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
      list.append(rowEl);
    });
  }
  view.append(wrap);
}

if (state.ready) {
  refreshBoard()
    .then(() => render())
    .catch((e) => {
      state.err = e.message;
      render();
    });
} else {
  render();
}
