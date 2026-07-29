/* global fetch */
const $ = (id) => document.getElementById(id);

const PAGE_TITLE = {
  home: "总览",
  courses: "盯课",
  settings: "设置",
  logs: "日志",
};

let state = {
  courses: [],
  capacity: {},
  formLoaded: false,
  page: "home",
};

function toast(msg, isErr = false) {
  const el = $("toast");
  el.hidden = false;
  el.textContent = msg;
  el.classList.toggle("err", !!isErr);
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.hidden = true;
  }, 5000);
}

function escapeAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}
function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
  } catch (e) {
    throw new Error("面板未启动：运行 start_panel.bat → http://127.0.0.1:18730/");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || data.message || "请求失败");
  return data;
}

/* —— Pages —— */
function showPage(name) {
  state.page = name;
  document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
  const page = $("page-" + name);
  if (page) page.classList.add("active");
  const nav = document.querySelector(`.nav-item[data-page="${name}"]`);
  if (nav) nav.classList.add("active");
  $("pageTitle").textContent = PAGE_TITLE[name] || name;
  closeSidebar();
  if (name === "home") refresh(true);
  if (name === "logs") loadLogs();
}

function openSidebar() {
  $("sidebar").classList.add("open");
  $("scrim").hidden = false;
  $("scrim").classList.add("show");
}
function closeSidebar() {
  $("sidebar").classList.remove("open");
  $("scrim").classList.remove("show");
  $("scrim").hidden = true;
}

/* —— Render —— */
function setHero(cardId, valueId, subId, value, sub, cls) {
  $(valueId).textContent = value;
  if (subId) $(subId).textContent = sub || "";
  const card = $(cardId);
  card.classList.remove("on", "off", "warn", "bad", "alert");
  if (cls) card.classList.add(cls);
}

function renderHomeSeats() {
  const box = $("homeCourseList");
  box.innerHTML = "";
  if (!state.courses.length) {
    box.innerHTML = `<p class="muted">还没有盯课。请打开左侧「盯课」添加。</p>`;
    return;
  }
  // 有空位置前
  const rows = state.courses.map((c) => {
    const tid = c.teaching_class_id || "";
    const cap = state.capacity[tid];
    let rank = 2;
    let badge = `<span class="seat-badge unk">未查</span>`;
    let hasRoom = false;
    if (cap) {
      if (cap.error) {
        badge = `<span class="seat-badge err">失败</span>`;
        rank = 1;
      } else if (cap.has_room) {
        badge = `<span class="seat-badge open">有空 ${cap.selected}/${cap.capacity}</span>`;
        hasRoom = true;
        rank = 0;
      } else {
        badge = `<span class="seat-badge full">满 ${cap.selected}/${cap.capacity}</span>`;
        rank = 2;
      }
    }
    return { c, tid, badge, hasRoom, rank };
  });
  rows.sort((a, b) => a.rank - b.rank);

  rows.forEach(({ c, tid, badge, hasRoom }) => {
    const el = document.createElement("div");
    el.className = "seat-item" + (hasRoom ? " has-room" : "");
    el.innerHTML = `
      <div>
        <div class="seat-name">${escapeHtml(c.name || tid || "未命名")}</div>
        <div class="seat-id">${escapeHtml(tid)}</div>
      </div>
      ${badge}
    `;
    box.appendChild(el);
  });
}

function renderCourseEditors() {
  const box = $("courseCards");
  box.innerHTML = "";
  if (!state.courses.length) {
    box.innerHTML = `<p class="muted">列表为空。下方搜索或手动加班号。</p>`;
    return;
  }
  state.courses.forEach((c, idx) => {
    const row = document.createElement("div");
    row.className = "course-edit";
    row.innerHTML = `
      <input data-i="${idx}" data-f="name" value="${escapeAttr(c.name || "")}" placeholder="备注名" />
      <div class="row">
        <input data-i="${idx}" data-f="teaching_class_id" class="mono" value="${escapeAttr(c.teaching_class_id || "")}" placeholder="教学班号" />
        <button type="button" class="linkish" data-del="${idx}">移除</button>
      </div>
    `;
    box.appendChild(row);
  });
  box.querySelectorAll("input[data-f]").forEach((inp) => {
    inp.addEventListener("input", () => {
      state.courses[+inp.dataset.i][inp.dataset.f] = inp.value;
    });
  });
  box.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.courses.splice(+btn.dataset.del, 1);
      renderCourseEditors();
      renderHomeSeats();
    });
  });
}

function collectForm() {
  document.querySelectorAll("input[data-f]").forEach((inp) => {
    if (state.courses[+inp.dataset.i]) {
      state.courses[+inp.dataset.i][inp.dataset.f] = inp.value.trim();
    }
  });
  const from = $("mailFrom").value.trim();
  return {
    account: $("account").value.trim(),
    password: $("password").value,
    courses: state.courses
      .map((c) => ({
        name: (c.name || "").trim(),
        teaching_class_id: (c.teaching_class_id || "").trim(),
      }))
      .filter((c) => c.teaching_class_id),
    poll_interval_sec: +$("pollInterval").value || 20,
    alert_cooldown_sec: +$("cooldown").value || 600,
    mail: {
      enabled: true,
      provider: $("mailProvider").value,
      from_addr: from,
      to_addr: $("mailTo").value.trim() || from,
      password: $("mailPassword").value,
    },
  };
}

function fillForm(cfg) {
  $("account").value = cfg.account || "";
  $("password").value = "";
  const mail = cfg.mail || {};
  $("mailProvider").value = mail.provider || "qq";
  $("mailFrom").value = mail.from_addr || "";
  $("mailTo").value = mail.to_addr || mail.from_addr || "";
  $("mailPassword").value = "";
  $("pollInterval").value = cfg.poll_interval_sec ?? 20;
  $("cooldown").value = cfg.alert_cooldown_sec ?? 600;
  state.courses = (cfg.courses || []).map((c) => ({ ...c }));
  renderCourseEditors();
  renderHomeSeats();
}

function applyCapacity(cap) {
  if (!cap?.courses) return;
  state.capacity = {};
  cap.courses.forEach((c) => {
    state.capacity[c.teaching_class_id] = c;
  });
  const t = cap.checked_at ? `· ${cap.checked_at}` : "";
  $("capMeta").textContent = t;
  renderHomeSeats();
}

function applyStatus(data) {
  $("serverTime").textContent = data.server_time || "";

  const mon = data.monitor || {};
  if (mon.running) {
    setHero("heroMon", "stMonitor", "stMonitorSub", "开", mon.pids?.length ? `PID ${mon.pids.join(",")}` : "后台运行中", "on");
  } else {
    setHero("heroMon", "stMonitor", "stMonitorSub", "关", "未在监控", "off");
  }

  const sess = data.session || {};
  if (sess.alive) {
    setHero("heroSess", "stSession", "stSessionSub", "已登录", sess.student_code ? `学号 ${sess.student_code}` : "", "on");
  } else if (sess.has_token) {
    setHero("heroSess", "stSession", "stSessionSub", "过期", "请重新登录", "warn");
  } else {
    setHero("heroSess", "stSession", "stSessionSub", "未登录", "先到设置保存账号", "bad");
  }

  if (data.config && !state.formLoaded) {
    fillForm(data.config);
    state.formLoaded = true;
  } else if (data.config?.courses && state.formLoaded) {
    // keep editors; only sync home list ids from server if courses empty locally? skip to avoid clobber
  }

  // sync course names from config on first status if needed
  if (data.config?.courses && state.courses.length === 0) {
    state.courses = data.config.courses.map((c) => ({ ...c }));
    renderCourseEditors();
  }

  if (data.capacity?.ok) applyCapacity(data.capacity);
  else renderHomeSeats();

  const openN = Object.values(state.capacity).filter((c) => c && c.has_room && !c.error).length;
  const line = $("focusLine");
  line.classList.remove("ready", "alert");

  if (openN > 0) {
    line.textContent = `${openN} 门课当前有空位 — 快去选课系统`;
    line.classList.add("alert");
    $("heroMon").classList.add("alert");
  } else if (mon.running) {
    line.textContent = "监控中 · 目前都满 · 有退课会发邮件";
    line.classList.add("ready");
  } else if (sess.alive && (data.config?.courses || []).length) {
    line.textContent = "已登录且有盯课 · 点「开始监控」";
  } else if (!sess.alive) {
    line.textContent = "请先到「设置」保存账号并登录选课";
  } else {
    line.textContent = "请到「盯课」添加课程";
  }

  $("btnStart").disabled = !!mon.running || !sess.alive;
  $("logView").textContent = (data.log_tail || []).join("\n") || "暂无日志";
}

async function refresh(withCap = false) {
  try {
    const data = await api("/api/status" + (withCap ? "?with_capacity=1" : ""));
    applyStatus(data);
    const b = document.getElementById("offlineBanner");
    if (b) b.hidden = true;
    refresh._off = false;
  } catch (e) {
    let b = document.getElementById("offlineBanner");
    if (!b) {
      b = document.createElement("div");
      b.id = "offlineBanner";
      b.className = "offline-banner";
      document.body.prepend(b);
    }
    b.hidden = false;
    b.textContent = e.message;
    if (!refresh._off) {
      toast(e.message, true);
      refresh._off = true;
    }
  }
}

async function saveSilent() {
  const body = collectForm();
  await api("/api/config", { method: "POST", body: JSON.stringify(body) });
  $("password").value = "";
  $("mailPassword").value = "";
  state.courses = body.courses.map((c) => ({ ...c }));
  renderCourseEditors();
  renderHomeSeats();
}

async function saveSettings() {
  try {
    await saveSilent();
    toast("设置已保存");
    await refresh(false);
  } catch (e) {
    toast(e.message, true);
  }
}

async function saveCourses() {
  try {
    await saveSilent();
    toast("盯课已保存");
    await refresh(true);
  } catch (e) {
    toast(e.message, true);
  }
}

async function doLogin() {
  try {
    await saveSilent();
    toast("登录中…");
    const data = await api("/api/login", { method: "POST", body: "{}" });
    toast(data.ok ? `登录成功 ${data.student_code || ""}` : data.error || "失败", !data.ok);
    await refresh(true);
  } catch (e) {
    toast(e.message, true);
  }
}

async function doMail() {
  try {
    await saveSilent();
    const data = await api("/api/mail/test", { method: "POST", body: "{}" });
    toast(data.ok ? `已发送 → ${data.to}` : data.error || "失败", !data.ok);
  } catch (e) {
    toast(e.message, true);
  }
}

async function doCap() {
  try {
    const data = await api("/api/capacity", { method: "POST", body: "{}" });
    if (!data.ok) {
      toast(data.error || "查询失败", true);
      return;
    }
    applyCapacity(data);
    const open = (data.courses || []).filter((c) => c.has_room).length;
    toast(open ? `${open} 门有空位` : "目前都满");
    // update focus line roughly
    await refresh(false);
    applyCapacity(data);
  } catch (e) {
    toast(e.message, true);
  }
}

async function monStart() {
  try {
    await saveSilent();
    const data = await api("/api/monitor/start", { method: "POST", body: "{}" });
    toast(data.message || (data.ok ? "已开始" : "失败"), !data.ok);
    await refresh(true);
  } catch (e) {
    toast(e.message, true);
  }
}

async function monStop() {
  try {
    const data = await api("/api/monitor/stop", { method: "POST", body: "{}" });
    toast(data.message || "已停止");
    await refresh(false);
  } catch (e) {
    toast(e.message, true);
  }
}

async function loadLogs() {
  try {
    const data = await api("/api/logs?n=200");
    $("logView").textContent = (data.lines || []).join("\n") || "暂无日志";
  } catch (e) {
    toast(e.message, true);
  }
}

async function searchCatalog() {
  const q = $("catalogQ").value.trim();
  const box = $("catalogBox");
  box.innerHTML = `<p class="muted">搜索中…</p>`;
  try {
    const data = await api(`/api/catalog?q=${encodeURIComponent(q)}&limit=40`);
    if (!data.ready) {
      box.innerHTML = `<p class="muted">无课表缓存，请手动加班号。</p>`;
      return;
    }
    const items = data.items || [];
    if (!items.length) {
      box.innerHTML = `<p class="muted">无结果</p>`;
      return;
    }
    box.innerHTML = "";
    items.forEach((it) => {
      const row = document.createElement("div");
      row.className = "cat-item";
      row.innerHTML = `
        <div>
          <div>${escapeHtml(it.course_name || "")} · ${escapeHtml(it.teacher || "")}</div>
          <div class="d">${escapeHtml(it.place || "")}</div>
          <div class="id">${escapeHtml(it.teaching_class_id || "")}</div>
        </div>
        <button type="button" class="btn sm">加入</button>
      `;
      row.querySelector("button").onclick = () => {
        if (state.courses.some((c) => c.teaching_class_id === it.teaching_class_id)) {
          toast("已在列表中");
          return;
        }
        state.courses.push({
          name: `${it.course_name || ""} · ${it.teacher || ""}`.trim(),
          teaching_class_id: it.teaching_class_id,
        });
        renderCourseEditors();
        renderHomeSeats();
        toast("已加入，请点「保存盯课」");
      };
      box.appendChild(row);
    });
  } catch (e) {
    box.innerHTML = `<p class="muted">${escapeHtml(e.message)}</p>`;
  }
}

/* bind */
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => showPage(btn.dataset.page));
});
$("btnMenu").onclick = openSidebar;
$("scrim").onclick = closeSidebar;
$("btnRefresh").onclick = () => refresh(true);
$("btnSave").onclick = saveSettings;
$("btnSaveCourses").onclick = saveCourses;
$("btnLogin").onclick = doLogin;
$("btnMail").onclick = doMail;
$("btnCap").onclick = doCap;
$("btnStart").onclick = monStart;
$("btnStop").onclick = monStop;
$("btnLogs").onclick = loadLogs;
$("btnSearch").onclick = searchCatalog;
$("btnAddBlank").onclick = () => {
  state.courses.push({ name: "", teaching_class_id: "" });
  renderCourseEditors();
};
$("catalogQ").addEventListener("keydown", (e) => {
  if (e.key === "Enter") searchCatalog();
});
$("mailFrom").addEventListener("blur", () => {
  if (!$("mailTo").value.trim()) $("mailTo").value = $("mailFrom").value.trim();
});

showPage("home");
refresh(true);
setInterval(() => {
  if (state.page === "home") refresh(false);
}, 15000);
