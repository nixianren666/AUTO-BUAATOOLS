/**
 * BUAA 课程签到 Pro v1.4.1 - Origin Web 前端核心交互引擎
 * 严谨金融级界面驱动：多学生并发、常规考勤守护、自动博雅套件、实时终端日志
 */

let appState = {
  authenticated: false,
  activeUsername: "",
  activeUser: null,
  accounts: [],
  mode: "direct",
  globalAutoCheckin: false,
  classes: [],
  currentCaptchaId: "",
  logsTimer: null,
  currentLogFilter: "",
  currentLogCategory: "all",
  currentMainView: "regular", // "regular" | "boya" | "logs"
  boyaTab: "all", // 默认聚焦全量选课池，方便快速查阅与抢课
  boyaCourses: [],
  boyaSelected: [],
  boyaStatistics: {},
  boyaCategoryFilter: "全部",
  boyaSelectedTimeFilter: "upcoming", // "upcoming" (未来及正在进行) | "past" (历史选课) | "all"
  boyaAutoSignOnly: false,
  boyaAvailableOnly: false,
  boyaSearchKeyword: "",
  boyaStatus: {
    boya_auto_select: false,
    boya_auto_sign: false,
    boya_require_auto_sign: true,
    boya_allow_offline: false,
    campus: "北京",
    scheduler_running: false,
  },
};

// Every management request is authenticated and bound to the captured account.
const nativeFetch = window.fetch.bind(window);
let managementSession = null;
let runtimeCapabilities = { mode: 'headless', autostart_supported: false, exit_behavior: 'management-session' };
let viewGeneration = 0;
// The first login waits for both independent startup responses. Never queue a
// second prompt after the user has deliberately closed the initial login card.
const firstLoginState = { disclaimerAccepted: false, accountsReady: false, prompted: false, accepting: false, commitmentText: '', commitmentVersion: '', noticeLoading: false, composing: false };
async function managementRequest(options = {}) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 12000);
  try { return await nativeFetch('/api/session', { ...options, credentials: 'same-origin', signal: controller.signal }); }
  finally { clearTimeout(timer); }
}
function useManagementSession(data) {
  if (typeof data.csrf !== 'string' || !data.csrf) throw new Error('管理会话响应无效');
  if (data.runtime) runtimeCapabilities = data.runtime;
  updateRuntimeControls();
  return data.csrf;
}
async function managementLogin(message, configured = true, reconnect = false) {
  // Do not steal the startup timeline's keyboard focus or trap its key guard.
  if (document.documentElement.classList.contains('startup-running')) {
    await new Promise(resolve => document.addEventListener('buaa:startupfinished', resolve, { once: true }));
  }
  const modal = document.getElementById('managementLoginModal'), form = document.getElementById('managementLoginForm');
  const input = document.getElementById('managementPassword'), submit = document.getElementById('managementLoginSubmit');
  const status = document.getElementById('managementLoginStatus'), workspace = document.querySelector('.origin-app-layout');
  if (!modal || !form) throw new Error('管理登录界面未加载，请刷新网页');
  const previousInert = workspace?.inert;
  if (workspace) workspace.inert = true;
  modal.classList.remove('hidden'); status.textContent = message;
  input.hidden = reconnect; input.required = !reconnect;
  submit.textContent = reconnect ? '重新连接' : '登录管理';
  input.disabled = !configured; submit.disabled = !configured;
  if (configured) input.focus();
  return new Promise(resolve => {
    let busy = false, retryAt = 0;
    form.onsubmit = async event => {
      event.preventDefault();
      if (!configured || busy || (!reconnect && !input.value)) return;
      if (Date.now() < retryAt) { status.textContent = '登录尝试较多，请稍后再试。'; return; }
      busy = true; submit.disabled = true; input.disabled = true; status.textContent = '正在验证管理密码…';
      let password = input.value; input.value = '';
      try {
        const response = await managementRequest(reconnect ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) });
        password = '';
        if (reconnect && response.status === 401) {
          const data = await response.json(); configured = data.configured !== false; reconnect = false;
          input.hidden = false; input.required = true; submit.textContent = '登录管理';
          if (!configured) throw new Error('服务尚未设置远程管理密码，请联系部署者配置并刷新网页。');
          throw new Error('此页面需要应用管理密码，请输入后登录。');
        }
        if (response.status === 429) {
          retryAt = Date.now() + Math.min(60, Math.max(1, Number(response.headers.get('Retry-After')) || 60)) * 1000;
          throw new Error('登录尝试较多，请等待一分钟再试。');
        }
        if (!response.ok) throw new Error(response.status === 401 ? '管理密码不正确，请重新输入。' : '管理登录暂时不可用，请稍后重试。');
        const csrf = useManagementSession(await response.json());
        modal.classList.add('hidden'); form.onsubmit = null; status.textContent = '';
        if (workspace) workspace.inert = previousInert;
        resolve(csrf);
      } catch (error) { status.textContent = error.name === 'AbortError' ? '连接超时，请检查网络后重试。' : error.message; }
      finally { password = ''; busy = false; submit.disabled = !configured; input.disabled = !configured; if (!modal.classList.contains('hidden')) (reconnect ? submit : input).focus(); }
    };
  });
}
async function establishManagementSession() {
  let response;
  try { response = await managementRequest(); }
  catch { return managementLogin('无法连接管理服务，请检查网络后重新连接。', true, true); }
  if (response.status === 401) {
    const data = await response.json().catch(() => ({}));
    return managementLogin(data.configured === false ? '服务尚未设置远程管理密码，请由部署者配置后刷新；不能用学校密码替代。' : '此页面需要应用管理密码。', data.configured !== false);
  }
  if (!response.ok) throw new Error('无法建立管理会话（' + response.status + '），请核对部署地址与访问权限');
  return useManagementSession(await response.json());
}
function ensureManagementSession() {
  if (!managementSession) managementSession = establishManagementSession().catch(error => { managementSession = null; throw error; });
  return managementSession;
}
function updateRuntimeControls() {
  const desktop = runtimeCapabilities.exit_behavior === 'application';
  const autostart = document.getElementById('autostartWidget');
  if (autostart) { autostart.hidden = !runtimeCapabilities.autostart_supported; autostart.classList.toggle('hidden', !runtimeCapabilities.autostart_supported); autostart.title = '本机开机自启；后台服务请使用部署工具管理'; }
  for (const button of document.querySelectorAll('[onclick="requestAppExit()"], [onclick="handleDisclaimerDecline()"]')) {
    button.title = desktop ? '退出应用并停止本机后台任务' : '仅退出本浏览器的管理会话，服务器任务继续运行';
    button.setAttribute('aria-label', desktop ? '退出应用' : '退出管理');
    if (button.matches('[onclick="handleDisclaimerDecline()"]')) button.textContent = desktop ? '退出软件' : '退出管理';
  }
}
async function apiFetch(input, options = {}) {
  const username = appState.activeUsername;
  const scoped = /^\/api\/(classes|signin|status|mode|logout|boya\/)/.test(String(input));
  const url = new URL(input, window.location.origin);
  if (url.origin !== window.location.origin) throw new Error("拒绝外部管理请求");
  const opts = { ...options, credentials: "same-origin", headers: { ...(options.headers || {}) } };
  if (username && scoped) {
    url.searchParams.set("username", username);
    if (opts.body) {
      const body = JSON.parse(opts.body);
      if (!Object.hasOwn(body, "username")) body.username = username;
      opts.body = JSON.stringify(body);
    }
  }
  const session = ensureManagementSession();
  const csrf = await session;
  if (opts.method && !["GET", "HEAD"].includes(opts.method.toUpperCase())) opts.headers["X-BUAA-CSRF"] = csrf;
  let response = await nativeFetch(url.pathname + url.search, opts);
  if (response.status === 401) {
    if (managementSession === session) managementSession = null;
    if (!['GET', 'HEAD'].includes((opts.method || 'GET').toUpperCase())) {
      // A failed write may have reached the backend: never replay it after login.
      void ensureManagementSession().catch(() => {});
      throw new Error('管理会话已过期，请重新登录后核对结果，再手动操作；没有自动重复提交。');
    }
    await ensureManagementSession();
    response = await nativeFetch(url.pathname + url.search, opts);
  }
  if (!response.ok) {
    if (response.status === 401) managementSession = null;
    if (url.pathname.startsWith('/api/td/')) {
      const failure = await response.json().catch(() => ({}));
      throw new Error(typeof failure.detail === 'string' ? failure.detail : 'TD 参数或请求无效，请核对设置');
    }
    throw new Error("应用请求未完成（" + response.status + "）");
  }
  return response;
}
function viewStillCurrent(username, generation) {
  return username === appState.activeUsername && generation === viewGeneration;
}
function actionAttributes(action, id, extra = "") {
  return `data-action="${action}" data-id="${escapeHtml(String(id))}" ${extra}`;
}
document.addEventListener("click", event => {
  const target = event.target.closest("[data-action]");
  if (!target || target.disabled) return;
  const action = target.dataset.action;
  const id = target.dataset.id;
  const handlers = { regularSign: () => manualSignIn(id), select: () => selectBoyaCourse(id), drop: () => dropBoyaCourse(id), sign: () => boyaSign(id, 1), signout: () => boyaSign(id, 2), switchAccount: () => switchStudentAccount(id), deleteAccount: () => deleteAccount(id) };
  if (handlers[action]) { event.preventDefault(); event.stopPropagation(); handlers[action](); }
});

// 页面生命周期初始化
document.addEventListener("DOMContentLoaded", () => {
  initClock();
  initAmbientCanvas();
  initGlassControls();
  checkDisclaimerStatus();
  initAutostartWidget();
  initModalBackdrops();
  fetchInitialState();
  startLogsPolling();
  startActiveViewAutoRefresh();
});

document.addEventListener('keydown', event => {
  const modal = document.getElementById('managementLoginModal');
  if (!modal || modal.classList.contains('hidden')) return;
  if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); }
  if (event.key === 'Tab') {
    const controls = [...modal.querySelectorAll('input,button')].filter(el => !el.disabled && !el.hidden && el.getClientRects().length);
    const first = controls[0], last = controls[controls.length - 1];
    if (first && (!modal.contains(document.activeElement) || (event.shiftKey ? document.activeElement === first : document.activeElement === last))) {
      event.preventDefault(); event.stopImmediatePropagation(); (event.shiftKey ? last : first).focus();
    }
  }
}, true);

// 模态弹窗蒙层点击与 ESC 快捷关闭
function setUISurface(id, visible) {
  if (window.BUAATDAccess?.blocksSurface(id, visible)) return false;
  if (window.BUAAUiSurfaces) return window.BUAAUiSurfaces.set(id, visible);
  // If optional motion fails to load, preserve exclusive, immediate controls.
  const ids = ["glassPopover", "updatePanel", "accountCardsModal", "loginModal", "manualSignModal", "tdSettingsModal", "tdCountModal", "tdGroupModal", "tdManualModal", "tdLicenseModal", "disclaimerModal"];
  const modal = document.getElementById("disclaimerModal");
  if (visible && id !== "disclaimerModal" && modal && !modal.classList.contains("hidden")) return false;
  ids.forEach(otherId => {
    const el = document.getElementById(otherId);
    if (el && (otherId === id || visible)) {
      const closed = otherId !== id || !visible;
      el.classList.toggle("hidden", closed);
      el.inert = closed;
      el.setAttribute("aria-hidden", String(closed));
      const triggerId = { glassPopover: "glassControlBtn", updatePanel: "updateCheckBtn" }[otherId];
      document.getElementById(triggerId)?.setAttribute("aria-expanded", String(!closed));
    }
  });
  return visible;
}

function initModalBackdrops() {
  const modalConfigs = [
    { id: "accountCardsModal", closeFn: closeAccountCardsModal },
    { id: "loginModal", closeFn: closeLoginModal },
    { id: "manualSignModal", closeFn: closeManualSignModal },
  ];
  modalConfigs.forEach(({ id, closeFn }) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("click", (e) => {
        if (e.target === el) {
          closeFn();
        }
      });
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const manualModal = document.getElementById("manualSignModal");
      if (manualModal && !manualModal.classList.contains("hidden")) {
        closeManualSignModal();
        return;
      }
      const loginModal = document.getElementById("loginModal");
      if (loginModal && !loginModal.classList.contains("hidden")) {
        closeLoginModal();
        return;
      }
      const cardsModal = document.getElementById("accountCardsModal");
      if (cardsModal && !cardsModal.classList.contains("hidden")) {
        closeAccountCardsModal();
        return;
      }
      const glassPopover = document.getElementById("glassPopover");
      if (glassPopover && !glassPopover.classList.contains("hidden")) {
        setUISurface("glassPopover", false);
        document.getElementById("glassControlBtn")?.focus();
      }
    }
  });
}

// 精密等宽时钟
function initClock() {
  const clockEl = document.querySelector("#liveClock .clock-time");
  function update() {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, "0");
    const m = String(now.getMinutes()).padStart(2, "0");
    const s = String(now.getSeconds()).padStart(2, "0");
    if (clockEl) clockEl.textContent = `${h}:${m}:${s}`;
  }
  update();
  setInterval(update, 1000);
}

// 主视图无缝切换 (Origin Left Rail)
function switchMainView(viewName) {
  if (viewName === 'td') {
    window.BUAATDAccess?.enter();
    return;
  }
  window.BUAATDAccess?.leave();
  showMainView(viewName);
}

function showMainView(viewName) {
  appState.currentMainView = viewName;

  // 更新导航激活状态
  document.querySelectorAll(".origin-nav-item").forEach(item => item.classList.remove("active"));
  const btnMap = {
    regular: "navBtnRegular",
    boya: "navBtnBoya",
    td: "navBtnTD",
    logs: "navBtnLogs",
  };
  const activeBtn = document.getElementById(btnMap[viewName]);
  if (activeBtn) activeBtn.classList.add("active");

  // 更新面包屑文本
  const breadcrumb = document.getElementById("topbarCurrentSection");
  if (breadcrumb) {
    if (viewName === "regular") breadcrumb.textContent = "常规课堂考勤";
    else if (viewName === "boya") breadcrumb.textContent = "自动博雅套件 / 学期博雅素养与选课";
    else if (viewName === "logs") breadcrumb.textContent = "实时终端监控 / 系统全局审计";
    else if (viewName === "td") breadcrumb.textContent = "自动 TD 守护 / 本人锻炼与学期进度";
  }

  // 显隐内容板块
  const vRegular = document.getElementById("viewRegular");
  const vBoya = document.getElementById("viewBoya");
  const vLogs = document.getElementById("viewLogs");

  if (vRegular) vRegular.classList.toggle("hidden", viewName !== "regular");
  if (vBoya) vBoya.classList.toggle("hidden", viewName !== "boya");
  if (vLogs) vLogs.classList.toggle("hidden", viewName !== "logs");
  document.getElementById('viewTD')?.classList.toggle('hidden', viewName !== 'td');
  document.dispatchEvent(new CustomEvent('buaa:mainview', { detail: { view: viewName } }));

  if (viewName === "boya") {
    fetchBoyaData(false);
  } else if (viewName === "logs") {
    fetchLogs();
  }
}

// 获取全系统初始状态
function maybeOpenFirstLogin() {
  if (!firstLoginState.disclaimerAccepted || !firstLoginState.accountsReady || firstLoginState.prompted ||
      appState.authenticated || appState.accounts.length > 0) return;
  const modal = document.getElementById("loginModal");
  if (modal && setUISurface("loginModal", true)) firstLoginState.prompted = true;
}

async function fetchInitialState() {
  const requestedUsername = appState.activeUsername;
  const requestedGeneration = viewGeneration;
  try {
    const [statusRes, accountsRes, configRes] = await Promise.all([
      apiFetch("/api/status").then(r => r.json()),
      apiFetch("/api/accounts").then(r => r.json()),
      apiFetch("/api/config").then(r => r.json()),
    ]);


    if (!viewStillCurrent(requestedUsername, requestedGeneration)) return;
    appState.accounts = accountsRes.accounts || [];
    firstLoginState.accountsReady = Array.isArray(accountsRes.accounts);
    appState.activeUsername = accountsRes.active_username || "";
    viewGeneration++;
    appState.activeUser = appState.accounts.find(a => a.username === appState.activeUsername) || null;

    appState.mode = statusRes.mode || "direct";
    appState.authenticated = statusRes.authenticated || false;
    appState.globalAutoCheckin = configRes.global_auto_checkin ?? false;

    updateUIElements();

    if (appState.authenticated || appState.accounts.length > 0) {
      fetchClasses();
      fetchBoyaData(false);
    } else if (appState.accounts.length === 0) {
      maybeOpenFirstLogin();
    }
  } catch (err) {
    console.error("fetchInitialState error:", err);
  }
}

// 刷新界面全局身份与状态元素
function updateUIElements() {
  const modeText = document.getElementById("modeText");
  const modeDot = document.getElementById("modeDot");
  if (modeText) modeText.textContent = appState.mode === "webvpn" ? "WebVPN 外网" : "校园网直连";
  if (modeDot) modeDot.className = `origin-status-dot ${appState.mode === "webvpn" ? "cyan" : "green"}`;

  const autoToggle = document.getElementById("autoCheckinToggle");
  if (autoToggle) autoToggle.checked = appState.globalAutoCheckin;
  const daemon = document.getElementById("regularDaemonStatus");
  const dot = document.getElementById("regularDaemonDot");
  const running = appState.globalAutoCheckin && !!appState.activeUser?.auto_checkin;
  if (daemon) daemon.textContent = !appState.activeUsername ? "尚未登录" : running ? "自动签到守护已启用" : "自动签到已暂停";
  if (dot) dot.className = "origin-status-dot " + (running ? "green" : "");
  const health = document.getElementById("regularHealthText");
  if (health) health.textContent = appState.regularStale ? "课表未同步，显示上次成功数据" : appState.regularLastSuccess ? "最近同步：" + appState.regularLastSuccess : "尚未完成课表同步";

  const badgeAccounts = document.getElementById("navBadgeAccounts");
  if (badgeAccounts) badgeAccounts.textContent = appState.accounts.length;

  // 用户卡片更新
  const sName = appState.activeUser ? (appState.activeUser.name || appState.activeUser.username) : "未登录";
  const sId = appState.activeUser ? appState.activeUser.username : "点击接入账号";
  const sInitial = sName ? sName.slice(0, 1) : "学";

  const sbName = document.getElementById("sidebarStudentName");
  const sbId = document.getElementById("sidebarStudentId");
  const sbAvatar = document.getElementById("sidebarAvatar");
  const heroName = document.getElementById("heroStudentName");
  const heroId = document.getElementById("heroStudentId");

  if (sbName) sbName.textContent = sName;
  if (sbId) sbId.textContent = sId;
  if (sbAvatar) sbAvatar.textContent = sInitial;
  if (heroName) heroName.textContent = sName;
  if (heroId) heroId.textContent = sId;

  // 博雅状态同步
  if (appState.activeUser) {
    const sSelect = document.getElementById("boyaAutoSelectToggle");
    const sSign = document.getElementById("boyaAutoSignToggle");
    const sCampus = document.getElementById("boyaCampusSelect");
    if (sSelect) sSelect.checked = !!appState.activeUser.boya_auto_select;
    if (sSign) sSign.checked = !!appState.activeUser.boya_auto_sign;
    if (sCampus) sCampus.value = appState.activeUser.campus || "北京";
    window.BUAAUiControls?.syncSelect(sCampus);
    const targets=appState.activeUser.boya_targets || {"德育":2,"劳育":2,"美育":1,"安全健康":1};
    for (const [category,id] of Object.entries({"德育":"Moral","劳育":"Labor","美育":"Art","安全健康":"Security"})) {
      const input=document.getElementById("boyaTarget"+id);
      if (input && document.activeElement !== input) input.value=targets[category];
    }
  }
  document.dispatchEvent(new CustomEvent('buaa:accountview'));
}

// ==================== 1. 常规课堂考勤逻辑 ====================

async function fetchClasses(isSilent = false) {
  const requestedUsername = appState.activeUsername;
  const requestedGeneration = viewGeneration;
  try {
    const res = await apiFetch("/api/classes");
    const data = await res.json();

    if (!viewStillCurrent(requestedUsername, requestedGeneration)) return;
    appState.regularStale = !!(data.stale || data.offline);
    if (!appState.regularStale && data.status === "success") appState.regularLastSuccess = new Date().toLocaleTimeString("zh-CN", {timeZone:"Asia/Shanghai"});
    updateUIElements();
    if (data.stale || data.offline) { if (!isSilent) showToast("课表未同步，显示上次成功数据", "info"); }
    if (data.classes) {
      appState.classes = data.classes;
      renderClassesList(data.classes);
    }
  } catch (e) {
    if (!isSilent) console.error("fetchClasses error:", e);
  }
}

function refreshCurrentStudentClasses() {
  showToast("正在拉取今日最新课堂日程...", "info");
  fetchClasses();
}

function renderClassesList(classes) {
  const container = document.getElementById("classesFeed");
  if (!container) return;

  const total = classes.length;
  const signed = classes.filter(c => c.signStatus === 1).length;
  const pending = classes.filter(c => c.signStatus === 0).length;

  const badgeEl = document.getElementById("navBadgeClasses");
  const mTotal = document.getElementById("metricTotalClasses");
  const mSigned = document.getElementById("metricSignedClasses");
  const mPending = document.getElementById("metricPendingClasses");

  if (badgeEl) badgeEl.textContent = total;
  if (mTotal) mTotal.textContent = total;
  if (mSigned) mSigned.textContent = signed;
  if (mPending) mPending.textContent = pending;

  if (!classes || classes.length === 0) {
    if (appState.regularStale) {
      container.innerHTML='<div class="origin-empty-state"><div class="empty-title">课表尚未同步</div><div class="empty-desc">尚未取得有效课表，请检查登录与连接状态。</div></div>';
      return;
    }
    container.innerHTML = `
      <div class="origin-empty-state">
        <div class="empty-icon">☕</div>
        <div class="empty-title">今日暂无课堂排课</div>
        <div class="empty-desc">当前学生账号今日无须签到的 iclass 课程，后台守护将持续为您轮询检测新排课。</div>
      </div>
    `;
    return;
  }

  container.innerHTML = classes.map(c => {
    const isSigned = c.signStatus === 1;
    const statusKnown = c.signStatus === 0 || c.signStatus === 1;
    const begins = parseIsoOrSpaceDate(c.classBeginTime);
    const ends = parseIsoOrSpaceDate(c.classEndTime);
    const endKnown = begins && ends && ends > begins;
    const deadline = endKnown ? ends : begins;
    const timestamp = Date.now();
    const canSign = statusKnown && !isSigned && begins && timestamp >= begins.getTime()-600000 && timestamp <= deadline.getTime();
    const signHint = !statusKnown ? "官方状态未知" : !begins ? "课程时间未核实" : timestamp > deadline.getTime() ? (endKnown ? "本节签到窗口已结束" : "下课时间未核实") : "尚未到课前10分钟";
    const courseName = c.courseName || "未知课程";
    const timeRange = `${c.startTime || "--"} - ${c.endTime || "--"}`;
    const room = c.classroom || c.roomName || "校内教室";
    const teacher = c.teacherName || c.teacher || "任课教师";
    const schedId = c.courseSchedId || c.id || "";

    return `
      <div class="feed-card ${isSigned ? 'status-signed' : 'status-pending'}">
        <div class="feed-card-header">
          <div class="feed-title-col">
            <h4 class="feed-title">${escapeHtml(courseName)}</h4>
            <div class="feed-meta-row">
              <span class="feed-badge ${isSigned ? 'badge-green' : 'badge-cyan'}">
                ${isSigned ? '✓ 已完成签到' : statusKnown ? '⏳ 待签到' : '状态未知'}
              </span>
              <span>ID: ${escapeHtml(schedId)}</span>
            </div>
          </div>
        </div>

        <div class="feed-card-body">
          <div class="feed-info-item">
            <span class="info-k">上课时段</span>
            <span class="info-v">${escapeHtml(timeRange)}</span>
          </div>
          <div class="feed-info-item">
            <span class="info-k">教学地点</span>
            <span class="info-v">${escapeHtml(room)}</span>
          </div>
          <div class="feed-info-item">
            <span class="info-k">授课教师</span>
            <span class="info-v">${escapeHtml(teacher)}</span>
          </div>
        </div>

        <div class="feed-card-footer">
          <span style="font-size:12px;color:var(--text-muted);">课前优先，下课前限次补签</span>
          ${isSigned ? `
            <button class="origin-btn origin-confirmed-status" disabled title="官方已确认签到">${confirmedCheckIcon()}已签到</button>
          ` : `
            <button class="origin-btn origin-btn-primary" ${actionAttributes("regularSign", schedId)} ${canSign ? '' : 'disabled'}>${canSign ? '立即打卡' : signHint}</button>
          `}
        </div>
      </div>
    `;
  }).join("");
}

async function manualSignIn(courseSchedId) {
  const requestedUsername=appState.activeUsername, requestedGeneration=viewGeneration;
  showToast(`正在提交排课 ID [${courseSchedId}] 签到请求...`, "info");
  try {
    const res = await apiFetch("/api/signin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: String(courseSchedId) }),
    });
    const data = await res.json();
    if (!viewStillCurrent(requestedUsername,requestedGeneration)) return;
    if (data.status === "success" || data.success) {
      showToast("常规课程签到成功！", "success");
      fetchClasses();
    } else {
      showToast(`签到反馈: ${data.message || "未能成功"}`, "error");
    }
  } catch (e) {
    if (!viewStillCurrent(requestedUsername,requestedGeneration)) return;
    showToast("签到通信异常，请检查网络通道", "error");
  }
}

async function toggleAutoCheckin(enabled) {
  try {
    const res = await apiFetch("/api/auto_checkin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: enabled }),
    });
    const data = await res.json();
    appState.globalAutoCheckin = data.enabled;
    updateUIElements();
    showToast(data.persisted === false ? "已暂停，但配置未保存；重启前请重新保存" : `常规课程自动签到已${data.enabled ? "启动守护" : "暂停"}`, data.persisted === false ? "warning" : "info");
  } catch (e) {
    updateUIElements();
    showToast("切换自动打卡状态失败", "error");
  }
}

// ==================== 2. 自动博雅全套逻辑 (四大门类与多维筛选) ====================

// 严格归一化为北航官方四大门类：美育、劳育、国家安全、德育
function normalizeBoyaCategory(c) {
  if (typeof c.category_key === "string" && c.category_key) return c.category_key;
  const raw=String(c.courseNewKind2?.kindName || c.courseKind || c.kindName || c.courseType || "").trim();
  if (raw.includes("安全") || raw.includes("健康")) return "安全健康";
  if (raw.includes("德育") || raw.includes("思政")) return "德育";
  if (raw.includes("劳育") || raw.includes("劳动")) return "劳育";
  if (raw.includes("美育") || raw.includes("艺术")) return "美育";
  return raw || "未分类";
}

// 严密解析博雅签到配置，准确识别线上自主打卡 vs 线下人工核验
function parseSignConfigPoints(c) {
  if (!c) return [];
  let cfg = c.courseSignConfig;
  if (!cfg) return [];
  if (typeof cfg === "string") {
    try {
      cfg = JSON.parse(cfg);
    } catch (e) {
      return [];
    }
  }
  if (cfg && Array.isArray(cfg.signPointList)) {
    return cfg.signPointList;
  }
  return [];
}

async function fetchBoyaData(isManual = false) {
  const requestedUsername = appState.activeUsername;
  const requestedGeneration = viewGeneration;
  if (isManual) showToast("正在同步博雅学分与最新课表...", "info");
  try {
    const [coursesRes, selectedRes, statusRes, statsRes] = await Promise.all([
      apiFetch("/api/boya/courses" + (isManual ? "?force=true" : "")).then(r => r.json()),
      apiFetch("/api/boya/selected" + (isManual ? "?force=true" : "")).then(r => r.json()),
      apiFetch("/api/boya/status").then(r => r.json()),
      apiFetch("/api/boya/statistics" + (isManual ? "?force=true" : "")).then(r => r.json()),
    ]);


    if (!viewStillCurrent(requestedUsername, requestedGeneration)) return;
    // 严密字段兼容读取
    appState.boyaCourses = coursesRes.courses || coursesRes.all_courses || [];
    appState.boyaSelected = selectedRes.selected || selectedRes.selected_courses || [];
    appState.boyaStatistics = statsRes.statistics || statsRes || {};

    if (statusRes && statusRes.status !== "error") {
      appState.boyaStatus = statusRes;
      const selToggle = document.getElementById("boyaAutoSelectToggle");
      const signToggle = document.getElementById("boyaAutoSignToggle");
      const campusSelect = document.getElementById("boyaCampusSelect");
      if (selToggle && statusRes.boya_auto_select !== undefined) selToggle.checked = !!statusRes.boya_auto_select;
      if (signToggle && statusRes.boya_auto_sign !== undefined) signToggle.checked = !!statusRes.boya_auto_sign;
      if (campusSelect && statusRes.campus) campusSelect.value = statusRes.campus;
      window.BUAAUiControls?.syncSelect(campusSelect);
    }

    const daemon = document.getElementById("boyaDaemonStatus");
    if (daemon) daemon.textContent = statusRes.boya_auto_select || statusRes.boya_auto_sign ? "博雅自动化已启用" : "博雅自动化已暂停";
    const health = document.getElementById("boyaHealthText");
    if (health) health.textContent = coursesRes.stale || selectedRes.stale || statsRes.stale ? "官方数据未完全同步，显示上次数据" : statusRes.health?.last_success ? "最近后台同步：" + statusRes.health.last_success : "页面已读取官方数据";
    appState.boyaDataStale = !!(coursesRes.stale || selectedRes.stale || statsRes.stale);
    renderBoyaStatistics(appState.boyaStatistics);
    switchBoyaTab(appState.boyaTab);
    if (isManual) showToast(coursesRes.stale || selectedRes.stale || statsRes.stale ? "博雅数据未完全同步，保留上次数据" : `博雅数据同步完成，共载入 ${appState.boyaCourses.length} 门课程`, coursesRes.stale || selectedRes.stale || statsRes.stale ? "info" : "success");
  } catch (e) {
    console.error("fetchBoyaData error:", e);
    if (isManual) showToast("博雅数据拉取异常", "error");
  }
}

// 考勤状态解析
function getCourseAttendanceInfo(c) {
  if (c.attendance_status && typeof c.attendance_status === "object") return { ...c.attendance_status, badge: c.attendance_status.passed === true ? "badge-green" : "badge-amber" };
  return { passed: c.checkin === 1 || c.checkin === "1" ? true : null, text: c.checkin === 1 || c.checkin === "1" ? "考勤通过" : "待官方考勤确认", badge: "badge-amber" };
}

function getCourseExamInfo(c) {
  if (c.exam_status && typeof c.exam_status === "object") return { ...c.exam_status, badge: c.exam_status.passed === true ? "badge-green" : "badge-amber" };
  return { passed: c.pass === 1 || c.pass === "1" ? true : (c.pass === 0 || c.pass === "0" ? false : null), text: c.pass === 1 || c.pass === "1" ? "考核通过" : "待官方考核确认", badge: "badge-amber" };
}

function isCourseFinalPassed(c) {
  const att = getCourseAttendanceInfo(c);
  const exam = getCourseExamInfo(c);
  return att.passed === true && exam.passed === true;
}

function renderBoyaStatistics(stats) {
  // Backend uses the shared official-calendar/attendance contract. Never recount
  // with guessed dates or signInfo strings in a second, divergent implementation.
  const known = stats.semester_known === true;
  const count = key => known && Number.isFinite(Number(stats[key])) ? Math.max(0,Number(stats[key])) : 0;
  const moral=count("moral_completed"),labor=count("labor_completed"),art=count("art_completed"),sec=count("security_health_completed");

  // 四大类学期达标基准：德育 2, 劳育 2, 美育 1, 安全健康 1 (总基准 6 门)
  const reqMoral = 2;
  const reqLabor = 2;
  const reqArt = 1;
  const reqSec = 1;
  const totalReq = 6;

  const effMoral = Math.min(moral, reqMoral);
  const effLabor = Math.min(labor, reqLabor);
  const effArt = Math.min(art, reqArt);
  const effSec = Math.min(sec, reqSec);
  const totalPassed = effMoral + effLabor + effArt + effSec;

  const navProgress = document.getElementById("navBadgeBoya");
  if (navProgress) {
    navProgress.textContent = known ? `${totalPassed}/${totalReq}` : `—/${totalReq}`;
    navProgress.title = known ? `本学期达标 ${totalPassed}/${totalReq} 门（按类别上限计入）${appState.boyaDataStale ? "；上次核实数据" : ""}` : "官方校历或进度待同步";
  }

  const rate = Math.min(100, Math.round((totalPassed / totalReq) * 100));

  const elEarned = document.getElementById("boyaEarnedCredits");
  const elRate = document.getElementById("boyaCompletionRate");
  const elFill = document.getElementById("boyaProgressFill");
  const elDenom = document.getElementById("boyaSemesterDenominator");

  if (elEarned) elEarned.textContent = known ? `${totalPassed}` : "—";
  if (elRate) elRate.textContent = known ? `学期达标完成度 ${rate}%` : "官方校历未同步，不能计算学期达标";
  if (elFill) elFill.style.width = `${rate}%`;
  if (elDenom) {
    const sShort = known ? String(stats.semester_name || "当前学期").replace(/（.*）/, "").trim() : "学期未知";
    elDenom.textContent = known ? `/ 6 门 ${sShort} · 默认类别指标` : "学期未知 · 默认类别指标为6门";
    elDenom.title = known ? `官方校历: ${stats.semester_start} 至 ${stats.semester_end}；缺日期课程不计入` : "请同步学校官方校历";
  }

  const pMoral = document.getElementById("pillMoral");
  const pLabor = document.getElementById("pillLabor");
  const pArt = document.getElementById("pillArt");
  const pSec = document.getElementById("pillSec");

  if (pMoral) {
    pMoral.textContent = known ? `${moral} / ${reqMoral} 门` : `— / ${reqMoral} 门`;
    const wrap = document.getElementById("pillMoralWrap");
    if (wrap) wrap.classList.toggle("status-done", moral >= reqMoral);
  }
  if (pLabor) {
    pLabor.textContent = known ? `${labor} / ${reqLabor} 门` : `— / ${reqLabor} 门`;
    const wrap = document.getElementById("pillLaborWrap");
    if (wrap) wrap.classList.toggle("status-done", labor >= reqLabor);
  }
  if (pArt) {
    pArt.textContent = known ? `${art} / ${reqArt} 门` : `— / ${reqArt} 门`;
    const wrap = document.getElementById("pillArtWrap");
    if (wrap) wrap.classList.toggle("status-done", art >= reqArt);
  }
  if (pSec) {
    pSec.textContent = known ? `${sec} / ${reqSec} 门` : `— / ${reqSec} 门`;
    const wrap = document.getElementById("pillSecWrap");
    if (wrap) wrap.classList.toggle("status-done", sec >= reqSec);
  }
}

function parseIsoOrSpaceDate(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  let text = value.trim().replaceAll("/", "-").replace(" ", "T");
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += "T00:00:00";
  if (!/(Z|[+-]\d{2}:?\d{2})$/.test(text)) text += "+08:00";
  const dt = new Date(text);
  return Number.isNaN(dt.getTime()) ? null : dt;
}
function getCourseEndDateTime(c) {
  if (!c.courseEndDate) return null;
  const date = String(c.courseEndDate).trim();
  if (/T| /.test(date)) return parseIsoOrSpaceDate(date);
  if (!c.courseEndTime) return null;
  return parseIsoOrSpaceDate(date + " " + String(c.courseEndTime));
}

function isCourseEnded(c) {
  if (!c) return false;
  if (c.is_ended === true) return true;

  // 1. 显式状态判断
  const statusStr = String(c.courseStatus || c.status || c.courseState || "");
  if (statusStr.includes("结课") || statusStr.includes("结束")) {
    return true;
  }

  // 2. 课程结束时间优先；签到窗口结束不代表课程结束。
  const endDt = getCourseEndDateTime(c);
  if (endDt) return new Date() > endDt;

  // 3. 缺少课程结束时间时，仅使用签退截止时间，不使用签到截止时间。
  let cfg = c.courseSignConfig;
  if (typeof cfg === "string") {
    try { cfg = JSON.parse(cfg); } catch (e) { cfg = null; }
  }
  if (cfg && typeof cfg === "object") {
    const signOutEnd = cfg.signOutEndDate;
    if (signOutEnd) {
      const dtSignOut = parseIsoOrSpaceDate(signOutEnd);
      if (dtSignOut && new Date() > dtSignOut) {
        return true;
      }
    }
  }

  return false;
}

function isCourseOngoingOrUpcoming(c) {
  return !isCourseEnded(c);
}

function isCoursePast(c) {
  return isCourseEnded(c);
}

function filterSelectedTime(mode, btn) {
  appState.boyaSelectedTimeFilter = mode;
  document.querySelectorAll("#selectedTimeFilterStrip .filter-pill").forEach(p => p.classList.remove("active"));
  if (btn) btn.classList.add("active");
  renderBoyaFeed();
}

function switchBoyaTab(tab) {
  appState.boyaTab = tab;
  document.getElementById("tabBoyaSelected").classList.toggle("active", tab === "selected");
  document.getElementById("tabBoyaAll").classList.toggle("active", tab === "all");

  const timeStrip = document.getElementById("selectedTimeFilterStrip");
  const matrix = document.getElementById("boyaFilterMatrix");
  if (timeStrip) timeStrip.classList.toggle("hidden", tab !== "selected");
  if (matrix) matrix.classList.toggle("hidden", tab !== "all");

  renderBoyaFeed();
}

function filterBoyaCategory(cat, btn) {
  appState.boyaCategoryFilter = cat;
  document.querySelectorAll(".filter-category-group .filter-pill").forEach(p => p.classList.remove("active"));
  if (btn) btn.classList.add("active");
  renderBoyaFeed();
}

function toggleFilterAutoSign(btn) {
  appState.boyaAutoSignOnly = !appState.boyaAutoSignOnly;
  if (btn) btn.classList.toggle("active", appState.boyaAutoSignOnly);
  renderBoyaFeed();
}

function toggleFilterAvailable(btn) {
  appState.boyaAvailableOnly = !appState.boyaAvailableOnly;
  if (btn) btn.classList.toggle("active", appState.boyaAvailableOnly);
  renderBoyaFeed();
}

function handleBoyaSearch(val) {
  appState.boyaSearchKeyword = (val || "").trim().toLowerCase();
  renderBoyaFeed();
}

function renderBoyaFeed() {
  const container = document.getElementById("boyaCoursesFeed");
  if (!container) return;

  const countSel = document.getElementById("countBoyaSelected");
  const countAll = document.getElementById("countBoyaAll");
  if (countSel) countSel.textContent = appState.boyaSelected.length;
  if (countAll) countAll.textContent = appState.boyaCourses.length;

  const sourceList = appState.boyaTab === "selected" ? appState.boyaSelected : appState.boyaCourses;
  let list = sourceList;

  // 0. 已选修课程的时间状态筛选 (未来及正在进行 vs 历史选课)
  if (appState.boyaTab === "selected") {
    if (appState.boyaSelectedTimeFilter === "upcoming") {
      list = list.filter(c => isCourseOngoingOrUpcoming(c));
    } else if (appState.boyaSelectedTimeFilter === "past") {
      list = list.filter(c => isCoursePast(c));
    }
  }

  // 1. 关键词搜索 (课程名、教师、地点、课程 ID)
  if (appState.boyaSearchKeyword) {
    list = list.filter(c => {
      const name = String(c.courseName || c.name || "").toLowerCase();
      const teacher = String(c.speaker || c.teacherName || c.courseTeacher || "").toLowerCase();
      const pos = String(c.coursePosition || c.courseAddress || "").toLowerCase();
      const cid = String(c.id || c.courseId || "");
      return name.includes(appState.boyaSearchKeyword) || teacher.includes(appState.boyaSearchKeyword) || pos.includes(appState.boyaSearchKeyword) || cid.includes(appState.boyaSearchKeyword);
    });
  }

  // 课池专属条件不能隐藏已选课程；切页保留选择，仅在对应控件可见的课池应用。
  if (appState.boyaTab === "all") {
    if (appState.boyaCategoryFilter !== "全部") {
      list = list.filter(c => normalizeBoyaCategory(c) === appState.boyaCategoryFilter);
    }
    if (appState.boyaAutoSignOnly) {
      list = list.filter(c => c.autonomous_config_valid === true);
    }
    if (appState.boyaAvailableOnly) {
      list = list.filter(c => c.capacity_available === true);
    }
  }

  if (list.length === 0) {
    if (appState.boyaDataStale && sourceList.length === 0) {
      container.innerHTML='<div class="origin-empty-state"><div class="empty-title">博雅数据尚未同步</div><div class="empty-desc">请检查账号认证与连接；暂无数据不等于学校没有课程。</div></div>';
      return;
    }
    const selectedHasCourses = appState.boyaTab === "selected" && appState.boyaSelected.length > 0;
    container.innerHTML = `
      <div class="origin-empty-state">
        <div class="empty-icon">🎯</div>
        <div class="empty-title">${appState.boyaTab === "selected" ? (selectedHasCourses ? "当前条件下暂无匹配的已选课程" : "暂无已选修课程") : "选课池中暂无匹配课程"}</div>
        <div class="empty-desc">${appState.boyaTab === "selected" ? (selectedHasCourses ? "已有选课记录；请切换至【全部已选】或调整上方搜索词查看。" : "可切换至上方【全量选课池】挑选心仪的博雅课程立即抢选。") : "未找到符合当前多维筛选条件的课程，请调整类别、取消过滤器或更换搜索词。"}</div>
      </div>
    `;
    return;
  }

  container.innerHTML = list.map(c => {
    const isSelected = appState.boyaTab === "selected";
    const courseId = c.id || c.courseId || "";
    const name = c.courseName || c.name || "博雅课程";
    const category = normalizeBoyaCategory(c);
    const speaker = c.speaker || c.teacherName || c.courseTeacher || "主讲学者";
    const startDate = c.courseStartDate && c.courseStartTime && String(c.courseStartDate).length === 10 ? parseIsoOrSpaceDate(c.courseStartDate + " " + c.courseStartTime) : parseIsoOrSpaceDate(c.courseStartDate);
    const endDate = getCourseEndDateTime(c);
    const formatDate = date => date.toLocaleString("zh-CN", {timeZone:"Asia/Shanghai",hour12:false});
    const time = startDate && endDate ? formatDate(startDate) + " — " + formatDate(endDate) : "课程起止时间待官方补全";
    const location = c.coursePosition || c.courseAddress || "校内教室";
    const points = parseSignConfigPoints(c);
    const hasAutonomousSign = c.autonomous_config_valid === true;
    const rawCapacity = c.capacity_maximum;
    const capacity = Number.isInteger(rawCapacity) && rawCapacity > 0 ? rawCapacity : null;
    const rawCurrent = c.capacity_current;
    const current = Number.isInteger(rawCurrent) && rawCurrent >= 0 ? rawCurrent : null;
    const isFull = capacity === null || current === null || current >= capacity;
    const isPast = isCoursePast(c);
    const isSigned = c.signed_in === true;
    const isSignedOut = c.signed_out === true;
    const attInfo = getCourseAttendanceInfo(c);
    const examInfo = getCourseExamInfo(c);
    const finalPassed = isCourseFinalPassed(c);

    return `
      <div class="feed-card ${hasAutonomousSign ? 'status-boya-auto' : ''}">
        <div class="feed-card-header">
          <div class="feed-title-col">
            <h4 class="feed-title">${escapeHtml(name)}</h4>
            <div class="feed-meta-row">
              <span class="feed-badge ${hasAutonomousSign ? 'badge-green' : 'badge-amber'}">
                ${hasAutonomousSign ? '🛰️ 自主考勤配置完整' : '🏫 需现场核验/配置待确认'}
              </span>
              <span class="feed-badge badge-purple">${escapeHtml(category)}</span>
              ${!isSelected ? `<span class="quota-text ${isFull ? 'full' : ''}">名额: ${current ?? "未知"}/${capacity ?? "未知"}${capacity !== null && current !== null ? ' (余'+Math.max(0,capacity-current)+')' : ''}</span>` : ''}
            </div>
          </div>
        </div>

        <div class="feed-card-body">
          <div class="feed-info-item">
            <span class="info-k">上课时间</span>
            <span class="info-v">${escapeHtml(time)}</span>
          </div>
          <div class="feed-info-item">
            <span class="info-k">课程地点</span>
            <span class="info-v">${escapeHtml(location)}</span>
          </div>
          <div class="feed-info-item">
            <span class="info-k">主讲嘉宾</span>
            <span class="info-v">${escapeHtml(speaker)}</span>
          </div>
        </div>

        <div class="feed-card-footer">
          ${isSelected ? (
            (isPast && !c.can_sign_in && !c.can_sign_out) ? `
              <div class="history-outcome-row" style="display:flex;justify-content:space-between;align-items:center;width:100%;flex-wrap:wrap;gap:6px;">
                <div style="display:flex;gap:6px;align-items:center;">
                  <span class="feed-badge ${attInfo.badge}">${escapeHtml(attInfo.text)}</span>
                  <span class="feed-badge ${examInfo.badge}">${escapeHtml(examInfo.text)}</span>
                </div>
                <div>
                  <span class="feed-badge ${finalPassed ? 'badge-green' : 'badge-amber'}" style="font-weight:600;">
                    ${finalPassed ? '🌟 最终考核达标' : '⏳ 考核待评定/未达标'}
                  </span>
                </div>
              </div>
            ` : `
              <div style="display:flex;gap:8px;width:100%;justify-content:flex-end;align-items:center;">
                ${c.can_drop !== true ? `
                  <button class="origin-btn origin-btn-danger-ghost" disabled style="opacity:0.35;cursor:not-allowed;" title="已有考勤、已通过、已结束或时间未知的课程不可退选">退选</button>
                ` : `
                  <button class="origin-btn origin-btn-danger-ghost" ${actionAttributes("drop", courseId)}>退选</button>
                `}

                ${isSignedOut ? `
                  <button class="origin-btn origin-confirmed-status" disabled title="北航SSO已确认签退">${confirmedCheckIcon()}已签退</button>
                ` : `
                  <button class="origin-btn origin-btn-secondary" ${c.can_sign_out === true ? "" : "disabled"} ${actionAttributes("signout", courseId)}>定位签退</button>
                `}

                ${isSigned ? `
                  <button class="origin-btn origin-confirmed-status" disabled title="北航SSO已确认签到">${confirmedCheckIcon()}已签到</button>
                ` : `
                  <button class="origin-btn origin-btn-primary" ${c.can_sign_in === true ? "" : "disabled"} ${actionAttributes("sign", courseId)}>定位签到</button>
                `}
              </div>
            `
          ) : (() => {
            const isAlreadyChosen = appState.boyaSelected && appState.boyaSelected.some(sc => String(sc.id || sc.courseId) === String(courseId));
            const remaining = Math.max(0, capacity - current);
            const now = new Date();
            const selStart = c.courseSelectStartDate ? parseIsoOrSpaceDate(c.courseSelectStartDate) : null;
            const selEnd = c.courseSelectEndDate ? parseIsoOrSpaceDate(c.courseSelectEndDate) : null;
            const isBeforeWindow = selStart && now < selStart;
            const isAfterWindow = selEnd && now > selEnd;

            let btnHtml = "";
            if (isAlreadyChosen) {
              btnHtml = `<button class="origin-btn origin-btn-ghost" disabled style="opacity:0.6;cursor:default;">已选修此课</button>`;
            } else if (!selStart || !selEnd) {
              btnHtml = `<button class="origin-btn origin-btn-ghost" disabled>选课窗口未知</button>`;
            } else if (isBeforeWindow) {
              btnHtml = `<button class="origin-btn origin-btn-ghost" disabled style="opacity:0.5;cursor:not-allowed;" title="选课开放时间: ${escapeHtml(c.courseSelectStartDate)}">⏳ 选课未开放</button>`;
            } else if (isAfterWindow) {
              btnHtml = `<button class="origin-btn origin-btn-ghost" disabled style="opacity:0.4;cursor:not-allowed;">选课已截止</button>`;
            } else if (capacity === null || current === null) {
              btnHtml = `<button class="origin-btn origin-btn-ghost" disabled>名额未核实</button>`;
            } else if (isFull) {
              btnHtml = `<button class="origin-btn origin-btn-ghost" disabled style="opacity:0.45;">⚠️ 名额已满</button>`;
            } else if (hasAutonomousSign) {
              btnHtml = `<button class="origin-btn origin-btn-primary" ${actionAttributes("select", courseId)}>立即抢课</button>`;
            } else {
              btnHtml = `<button class="origin-btn origin-btn-secondary" ${actionAttributes("select", courseId)} title="自主考勤配置未核实，请先查看学校要求；仅允许手动选择">选课 (需核实考勤)</button>`;
            }

            return `
              <div style="display:flex;justify-content:space-between;align-items:center;width:100%;">
                <span style="font-size:12px;color:var(--text-muted);">${capacity === null || current === null ? '名额数据待同步' : isFull ? '⚠️ 名额已满' : `✅ 名额可用 (余 ${remaining} 空位)`}</span>
                ${btnHtml}
              </div>
            `;
          })()}
        </div>
      </div>
    `;
  }).join("");
}

function courseActionId(value) {
  const text=String(value);
  const number=Number(text);
  if (!/^[1-9][0-9]*$/.test(text) || !Number.isSafeInteger(number)) throw new Error("课程ID未核实");
  return number;
}

async function selectBoyaCourse(id) {
  const requestedUsername=appState.activeUsername, requestedGeneration=viewGeneration;
  showToast(`正在发送抢选请求: [ID:${id}]...`, "info");
  try {
    const res = await apiFetch("/api/boya/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: courseActionId(id) }),
    });
    const d = await res.json();
    if (!viewStillCurrent(requestedUsername,requestedGeneration)) return;
    if (d.status === "ok" || d.status === "success" || d.code === 0 || d.code === "0") {
      showToast(d.pending_verification ? "选课请求已处理，官方已选记录待同步；不会重复提交" : "官方已选记录已确认", d.pending_verification ? "info" : "success");
      fetchBoyaData();
    } else {
      showToast(`抢选提示: ${d.message || d.msg || "未能选上"}`, "error");
    }
  } catch (e) {
    if (!viewStillCurrent(requestedUsername,requestedGeneration)) return;
    showToast("抢课通信请求异常", "error");
  }
}

async function dropBoyaCourse(id) {
  const requestedUsername=appState.activeUsername, requestedGeneration=viewGeneration;
  if (!confirm("确定要退选该博雅课程吗？")) return;
  showToast(`正在发送退选请求: [ID:${id}]...`, "info");
  try {
    const res = await apiFetch("/api/boya/drop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: courseActionId(id) }),
    });
    const d = await res.json();
    if (!viewStillCurrent(requestedUsername,requestedGeneration)) return;
    if (d.status === "ok" || d.status === "success" || d.code === 0 || d.code === "0") {
      showToast(d.pending_verification ? "退选请求已处理，官方状态待同步；不会重复提交" : "官方退选状态已确认", d.pending_verification ? "info" : "success");
      fetchBoyaData();
    } else {
      showToast(`退选失败: ${d.message || d.msg || ""}`, "error");
    }
  } catch (e) {
    if (!viewStillCurrent(requestedUsername,requestedGeneration)) return;
    showToast("退选通信请求异常", "error");
  }
}

async function boyaSign(id, signType) {
  const requestedUsername=appState.activeUsername, requestedGeneration=viewGeneration;
  const typeText = signType === 1 ? "签到" : "签退";
  showToast(`正在核对官方窗口并提交${typeText}...`, "info");
  try {
    const res = await apiFetch("/api/boya/sign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: courseActionId(id), sign_type: signType }),
    });
    const d = await res.json();
    if (!viewStillCurrent(requestedUsername,requestedGeneration)) return;
    if (d.status === "ok" || d.status === "success" || d.code === 0 || d.code === "0") {
      showToast(d.pending_verification ? `博雅${typeText}请求已处理，官方考勤待同步；不会重复提交` : `官方${typeText}记录已确认，最终考核以学校为准`, d.pending_verification ? "info" : "success");
      fetchBoyaData();
    } else {
      showToast(`打卡提示: ${d.message || d.msg || "未成功"}`, "error");
    }
  } catch (e) {
    if (!viewStillCurrent(requestedUsername,requestedGeneration)) return;
    showToast("打卡通信异常", "error");
  }
}

async function updateBoyaPreferences(body) {
  const username = appState.activeUsername, generation = viewGeneration;
  try {
    const res = await apiFetch("/api/boya/toggle_auto", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const data = await res.json();
    if (!viewStillCurrent(username,generation)) return;
    if (!res.ok || data.status !== "ok") throw new Error("配置未保存");
    if (appState.activeUser) Object.assign(appState.activeUser, data);
    updateUIElements();
    showToast(data.persisted === false ? "已暂停，但配置未保存；重启前请重新保存" : "博雅配置已保存", data.persisted === false ? "warning" : "success");
    fetchBoyaData();
  } catch (error) {
    if (!viewStillCurrent(username,generation)) return;
    updateUIElements();
    showToast("博雅配置未保存，请检查登录与连接状态", "error");
  }
}
async function toggleBoyaAutoSelect(enabled) { await updateBoyaPreferences({auto_select:enabled}); }
async function toggleBoyaAutoSign(enabled) { await updateBoyaPreferences({auto_sign:enabled}); }
async function changeBoyaCampus(campus) { await updateBoyaPreferences({campus}); }
async function saveBoyaTargets(event) {
  event.preventDefault();
  const targets = {};
  for (const [category,id] of Object.entries({"德育":"Moral","劳育":"Labor","美育":"Art","安全健康":"Security"})) targets[category] = Number(document.getElementById("boyaTarget"+id).value);
  await updateBoyaPreferences({targets});
}

// ==================== 3. 运行终端日志逻辑 ====================

function setLogCategory(cat) {
  appState.currentLogCategory = cat;
  const btnAll = document.getElementById("logCatAll");
  const btnReg = document.getElementById("logCatRegular");
  const btnBoya = document.getElementById("logCatBoya");
  if (btnAll) btnAll.classList.toggle("active", cat === "all");
  if (btnReg) btnReg.classList.toggle("active", cat === "regular");
  if (btnBoya) btnBoya.classList.toggle("active", cat === "boya");
  document.getElementById('logCatTD')?.classList.toggle('active', cat === 'td');
  fetchLogs();
}

function startLogsPolling() {
  if (appState.logsTimer) clearInterval(appState.logsTimer);
  fetchLogs();
  appState.logsTimer = setInterval(fetchLogs, 2500);
}

async function fetchLogs() {
  const requestedUsername = appState.activeUsername;
  const requestedGeneration = viewGeneration;
  const container = document.getElementById("logsContainer");
  if (!container) return;

  // 更新终端标题，显示当前绑定的学生与分类
  const titleEl = document.getElementById("logTerminalTitle");
  if (titleEl) {
    const studentName = appState.activeUser ? (appState.activeUser.name || appState.activeUser.username) : "系统全部";
    const catLabel = appState.currentLogCategory === 'td' ? '自动 TD' : appState.currentLogCategory === "boya" ? "自动博雅" : (appState.currentLogCategory === "regular" ? "常规课程" : "总日志");
    titleEl.textContent = `运行审计日志 · 当前学生: ${studentName} [${catLabel}]`;
  }

  try {
    const params = new URLSearchParams();
    if (appState.activeUsername) {
      params.append("username", appState.activeUsername);
    }
    if (appState.currentLogCategory && appState.currentLogCategory !== "all") {
      params.append("category", appState.currentLogCategory);
    } else {
      params.append("category", "all");
    }
    const url = `/api/logs?${params.toString()}`;
    const res = await apiFetch(url);
    const data = await res.json();
    if (!viewStillCurrent(requestedUsername, requestedGeneration)) return;

    const logs = data.logs || [];

    const isAtBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 40;

    container.innerHTML = logs.map(l => {
      const time = l.time || "--:--:--";
      const user = l.user_name || l.username || "";
      const msg = l.message || "";
      const level = l.level || "info";

      return `
        <div class="log-row log-${level}">
          <span class="l-time">[${time}]</span>
          ${user ? `<span class="l-user">@${escapeHtml(user)}</span>` : ''}
          <span class="l-msg">${escapeHtml(msg)}</span>
        </div>
      `;
    }).join("");

    if (isAtBottom) {
      container.scrollTop = container.scrollHeight;
    }

    // 事件驱动即时刷新：一旦检测到签到/签退/选课/退课等关键动作成功日志，即刻拉取最新课表与博雅状态
    if (logs.length > 0) {
      const topLog = logs[logs.length - 1];
      const topSig = `${topLog.time}_${topLog.message}`;
      if (topSig !== appState.lastSeenLogSig) {
        appState.lastSeenLogSig = topSig;
        const msg = topLog.message || "";
        if (msg.includes("签到成功") || msg.includes("签退成功")) {
          fetchClasses(true);
          fetchBoyaData(false);
        } else if (msg.includes("抢中") || msg.includes("退选成功") || msg.includes("已退选")) {
          fetchBoyaData(false);
        }
      }
    }
  } catch (e) {}
}

// 活跃视板块静默保活自动同步（25秒周期与窗口切回自适应）
function startActiveViewAutoRefresh() {
  setInterval(() => {
    if (appState.currentMainView === "regular") {
      fetchClasses(true);
    } else if (appState.currentMainView === "boya") {
      fetchBoyaData(false);
    }
  }, 25000);

  window.addEventListener("focus", () => {
    if (appState.currentMainView === "regular") {
      fetchClasses(true);
    } else if (appState.currentMainView === "boya") {
      fetchBoyaData(false);
    }
  });
}

async function clearLogs() {
  try {
    const params = new URLSearchParams();
    if (appState.activeUsername) {
      params.append("username", appState.activeUsername);
    }
    if (appState.currentLogCategory && appState.currentLogCategory !== "all") {
      params.append("category", appState.currentLogCategory);
    } else {
      params.append("category", "all");
    }
    const url = `/api/logs/clear?${params.toString()}`;
    await apiFetch(url, { method: "POST" });
    const c = document.getElementById("logsContainer");
    if (c) c.innerHTML = "";
    showToast("当前视板块日志已清空", "info");
    fetchLogs();
  } catch (e) {}
}

// ==================== 4. 学生账号管理模态框 ====================

function openAccountCardsModal() {
  renderAccountsModal();
  const modal = document.getElementById("accountCardsModal");
  if (modal) setUISurface("accountCardsModal", true);
}

function closeAccountCardsModal() {
  const modal = document.getElementById("accountCardsModal");
  if (modal) setUISurface("accountCardsModal", false);
}

function renderAccountsModal() {
  const container = document.getElementById("accountsModalList");
  if (!container) return;

  container.innerHTML = appState.accounts.map(acc => {
    const isActive = acc.username === appState.activeUsername;
    const initial = (acc.name || acc.username).slice(0, 1);

    return `
      <div class="origin-user-capsule" style="padding:12px;margin-bottom:8px;border-color:${isActive ? 'var(--accent-cyan)' : 'var(--border)'}" ${actionAttributes("switchAccount", acc.username)}>
        <div class="origin-avatar">${escapeHtml(initial)}</div>
        <div class="origin-user-info">
          <div class="origin-user-name">${escapeHtml(acc.name || acc.username)} ${isActive ? '<span class="origin-tag">当前活跃</span>' : ''}</div>
          <div class="origin-user-id">学号: ${escapeHtml(acc.username)} · 模式: ${acc.mode === 'webvpn' ? 'WebVPN' : '直连'}</div>
        </div>
        <div>
          <button class="origin-btn origin-btn-danger-ghost" ${actionAttributes("deleteAccount", acc.username)}>删除</button>
        </div>
      </div>
    `;
  }).join("");
}

async function switchStudentAccount(username) {
  const switchGeneration = ++viewGeneration;
  try {
    appState.activeUsername = username;
    appState.activeUser = appState.accounts.find(a => a.username === username);
    appState.classes = [];
    appState.boyaCourses = [];
    appState.boyaSelected = [];
    appState.boyaStatistics = {};
    renderBoyaFeed();
    renderBoyaStatistics({});
    updateUIElements();
    closeAccountCardsModal();

    // 立即向用户展示切换中视觉反馈，杜绝旧数据残留或误显“今天没有课”
    const container = document.getElementById("classesFeed");
    if (container) {
      container.innerHTML = `
        <div class="origin-empty-state" style="padding:40px;text-align:center;">
          <div style="font-size:14px;color:var(--text-secondary);margin-bottom:8px;">🔄 正在切换并载入【${escapeHtml(appState.activeUser ? appState.activeUser.name : username)}】今日课表...</div>
          <div style="font-size:12px;color:var(--text-muted);">自动同步北航课堂系统与博雅数据中</div>
        </div>
      `;
    }

    const res = await apiFetch("/api/accounts/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username }),
    });
    const d = await res.json();
    if (viewGeneration !== switchGeneration || appState.activeUsername !== username) return;
    if (d.status === "ok") {
      if (d.classes && d.classes.length > 0) {
        appState.classes = d.classes;
        renderClassesList(d.classes);
      }
      if (d.boya_courses) appState.boyaCourses = d.boya_courses;
      if (d.boya_selected) appState.boyaSelected = d.boya_selected;
      if (d.boya_statistics) {
        appState.boyaStatistics = d.boya_statistics;
        renderBoyaStatistics(appState.boyaStatistics);
      }

      await Promise.all([
        fetchClasses(),
        fetchBoyaData(false),
        fetchLogs(),
      ]);
      showToast(`已成功切换至学生: ${appState.activeUser ? (appState.activeUser.name || username) : username}`, "success");
    }
  } catch (e) {
    showToast("切换学生账号失败", "error");
  }
}

async function deleteAccount(username) {
  if (!confirm(`确定删除学号 ${username} 的账号配置吗？`)) return;
  try {
    const res = await apiFetch(`/api/accounts/${encodeURIComponent(username)}`, { method: "DELETE" });
    const data = await res.json().catch(() => ({}));
    appState.accounts = appState.accounts.filter(a => a.username !== username);
    if (appState.activeUsername === username) {
      viewGeneration++;
      appState.classes = []; appState.boyaCourses = []; appState.boyaSelected = []; appState.boyaStatistics = {};
      appState.activeUsername = data.active_username || (appState.accounts.length > 0 ? appState.accounts[0].username : "");
      appState.activeUser = appState.accounts.find(a => a.username === appState.activeUsername) || null;
      renderBoyaStatistics({});
      fetchClasses();
      fetchBoyaData();
      fetchLogs();
    }
    renderAccountsModal();
    updateUIElements();
    showToast("账号已移除", "info");
  } catch (e) {
    showToast("删除账号失败: " + e.message, "error");
  }
}

function openLoginModalFromCenter() {
  closeAccountCardsModal();
  openLoginModal();
}

function openLoginModal() {
  const m = document.getElementById("loginModal");
  if (m) setUISurface("loginModal", true);
}

function closeLoginModal() {
  const m = document.getElementById("loginModal");
  if (m) setUISurface("loginModal", false);
}

let loginInFlight = false;
let loginCaptchaContext = '';
function resetLoginCaptcha() {
  appState.currentCaptchaId = ''; loginCaptchaContext = '';
  const group = document.getElementById('loginCaptchaGroup');
  group?.classList.add('hidden');
  const input = document.getElementById('loginCaptchaInput');
  if (input) { input.value = ''; input.required = false; }
  document.getElementById('loginCaptchaImage')?.removeAttribute('src');
}
function refreshLoginCaptcha() {
  if (loginInFlight) return;
  resetLoginCaptcha();
  handleLogin({ preventDefault() {} });
}
for (const id of ['loginUsername','loginPassword','loginModeSelect']) {
  document.getElementById(id)?.addEventListener(id === 'loginModeSelect' ? 'change' : 'input', resetLoginCaptcha);
}
async function handleLogin(e) {
  e.preventDefault();
  if (loginInFlight) return;
  const u = document.getElementById('loginUsername').value.trim();
  const p = document.getElementById('loginPassword').value;
  const m = document.getElementById('loginModeSelect').value;
  const rem = document.getElementById('rememberMe').checked;
  if (!u || !p) return;
  const context = JSON.stringify([u,m]);
  const captcha = loginCaptchaContext === context ? document.getElementById('loginCaptchaInput')?.value.trim() || '' : '';
  loginInFlight = true;
  const submit = document.getElementById('loginSubmitBtn');
  if (submit) { submit.disabled = true; submit.textContent = '正在认证...'; }
  try {
    const res = await apiFetch('/api/login', { method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ username:u,password:p,mode:m,remember:rem,captcha,captcha_id:captcha ? appState.currentCaptchaId : '' }) });
    const data = await res.json();
    // A challenge arriving after editing the identity must never bind to new fields.
    if (document.getElementById('loginUsername').value.trim() !== u || document.getElementById('loginModeSelect').value !== m || document.getElementById('loginPassword').value !== p) return;
    if (data.status === 'captcha_required') {
      const challengeMode = ['direct','webvpn'].includes(data.mode) ? data.mode : m;
      const modeSelect = document.getElementById('loginModeSelect');
      modeSelect.value = challengeMode; window.BUAAUiControls?.syncSelect(modeSelect);
      appState.currentCaptchaId = data.captcha_id || ''; loginCaptchaContext = JSON.stringify([u,challengeMode]);
      document.getElementById('loginCaptchaGroup')?.classList.remove('hidden');
      const image = document.getElementById('loginCaptchaImage');
      const hasImage = /^data:image\/(png|jpe?g|gif|webp);base64,/i.test(data.captcha_image || '');
      if (image) { image.hidden = !hasImage; if (hasImage) image.src = data.captcha_image; else image.removeAttribute('src'); }
      const input = document.getElementById('loginCaptchaInput');
      if (input) { input.value = ''; input.required = hasImage; if (hasImage) input.focus(); }
      const hint = document.getElementById('loginCaptchaHint');
      if (hint) hint.textContent = data.message || '请完成学校验证码后再次提交';
      showToast(data.message || '请填写学校验证码', 'info');
    } else if (data.status === 'success' && data.authenticated) {
      resetLoginCaptcha();
      showToast(data.iclass_ready && data.boya_ready ? '身份认证及课表、博雅连接已完成' : '身份已确认，部分业务尚未就绪，请查看同步状态', data.iclass_ready && data.boya_ready ? 'success' : 'info');
      closeLoginModal(); fetchInitialState();
    } else {
      resetLoginCaptcha();
      showToast(`登录失败: ${data.message || '认证未完成，请重试'}`, 'error');
    }
  } catch (err) { showToast('登录通信未完成，请检查网络通道后重试', 'error'); }
  finally { loginInFlight = false; if (submit) { submit.disabled = false; submit.textContent = '确认登录并接入守护'; } }
}

// 手动排课 ID 签到模态框
function openManualSignModal() {
  const m = document.getElementById("manualSignModal");
  if (m) setUISurface("manualSignModal", true);
}

function closeManualSignModal() {
  const m = document.getElementById("manualSignModal");
  if (m) setUISurface("manualSignModal", false);
}

async function handleManualSignSubmit(e) {
  e.preventDefault();
  const id = document.getElementById("manualCourseId").value.trim();
  if (!id) return;
  closeManualSignModal();
  manualSignIn(id);
}

// 切换网络模式 (直连 vs WebVPN)
async function toggleMode() {
  const username = appState.activeUsername, generation = ++viewGeneration;
  const nextMode = appState.mode === "direct" ? "webvpn" : "direct";
  showToast(`正在切换至 ${nextMode === "webvpn" ? "WebVPN 外网" : "校园网直连"}...`, "info");
  try {
    const res = await apiFetch("/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: nextMode }),
    });
    const data = await res.json();
    if (!viewStillCurrent(username, generation)) return;
    if (!res.ok || data.status !== "ok") throw new Error("模式切换失败");
    appState.mode = data.mode;
    updateUIElements();
    showToast(`已切换至${data.mode === "webvpn" ? "WebVPN 外网通道" : "校园网直连"}，${data.reconnecting ? "正在重新认证" : "请确认登录状态"}`, "info");
  } catch (e) {
    showToast("切换网络通道失败", "error");
  }
}

// ==================== 5. 免责声明与开机自启 ====================

async function checkDisclaimerStatus() {
  if (firstLoginState.noticeLoading || firstLoginState.accepting) return;
  firstLoginState.noticeLoading = true;
  const input = document.getElementById('disclaimerCommitmentInput');
  if (input && !input.dataset.compositionBound) {
    input.addEventListener('compositionstart', () => handleDisclaimerComposition(true));
    input.addEventListener('compositionend', () => handleDisclaimerComposition(false));
    input.dataset.compositionBound = 'true';
  }
  const retry = document.getElementById('disclaimerRetryBtn');
  if (input) input.disabled = true;
  if (retry) retry.disabled = true;
  handleDisclaimerCheckChange();
  try {
    const res = await apiFetch("/api/system/disclaimer");
    const data = await res.json();
    if (typeof data.accepted !== "boolean" || typeof data.commitment_text !== 'string' ||
        !data.commitment_text || typeof data.commitment_version !== 'string' || !data.commitment_version) throw new Error("免责声明状态未确认");
    if (firstLoginState.commitmentVersion !== data.commitment_version) {
      firstLoginState.composing = false;
      if (input) input.value = '';
      const checkbox = document.getElementById('disclaimerCheck');
      if (checkbox) checkbox.checked = false;
    }
    firstLoginState.commitmentText = data.commitment_text;
    firstLoginState.commitmentVersion = data.commitment_version;
    const reference = document.getElementById('disclaimerCommitmentText');
    if (reference) reference.textContent = data.commitment_text;
    retry?.classList.add('hidden');
    if (input) input.disabled = false;
    firstLoginState.disclaimerAccepted = data.accepted;
    const modal = document.getElementById("disclaimerModal");
    if (modal) {
      if (!data.accepted) {
        setUISurface("disclaimerModal", true);
      } else {
        setUISurface("disclaimerModal", false);
      }
    }
    maybeOpenFirstLogin();
  } catch (e) {
    firstLoginState.commitmentText = ''; firstLoginState.commitmentVersion = '';
    firstLoginState.disclaimerAccepted = false;
    retry?.classList.remove('hidden');
    const reference = document.getElementById('disclaimerCommitmentText');
    if (reference) reference.textContent = '承诺内容暂时无法加载，请重新加载后确认。';
    // An unavailable status must not silently bypass the first-use notice.
    setUISurface("disclaimerModal", true);
    showToast("免责声明状态暂未确认，请阅读后重试确认", "error");
  } finally {
    firstLoginState.noticeLoading = false;
    if (retry) retry.disabled = false;
    handleDisclaimerCheckChange();
  }
}

function disclaimerCommitmentMatches() {
  const input = document.getElementById('disclaimerCommitmentInput');
  const normalize = value => value.replace(/[ \t\r\n\u3000]/g, '');
  return !!firstLoginState.commitmentText && !!firstLoginState.commitmentVersion && !!input &&
    !firstLoginState.composing && normalize(input.value) === normalize(firstLoginState.commitmentText);
}

function handleDisclaimerComposition(composing) {
  firstLoginState.composing = composing;
  handleDisclaimerCheckChange();
}

function handleDisclaimerCheckChange() {
  const checkbox = document.getElementById('disclaimerCheck');
  const matched = disclaimerCommitmentMatches();
  const btn = document.getElementById("disclaimerAgreeBtn");
  if (btn) btn.disabled = !checkbox?.checked || !matched || firstLoginState.accepting || firstLoginState.noticeLoading;
  const hint = document.getElementById('disclaimerCommitmentHint');
  if (hint) hint.textContent = !firstLoginState.commitmentText ? '条款尚未加载，请重新加载后确认。' :
    matched ? '承诺内容已完整核对；勾选条例一后可确认。' : '请完整输入承诺，标点保持一致；空格与换行不影响核对。';
}

async function handleDisclaimerAccept() {
  const checkbox = document.getElementById("disclaimerCheck");
  handleDisclaimerCheckChange();
  if (firstLoginState.accepting || firstLoginState.noticeLoading || !checkbox?.checked || !disclaimerCommitmentMatches()) return;
  firstLoginState.accepting = true;
  handleDisclaimerCheckChange(checkbox);
  const modal = document.getElementById("disclaimerModal");
  try {
    const res = await apiFetch("/api/system/disclaimer/accept", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      agreed: checkbox.checked, commitment: document.getElementById('disclaimerCommitmentInput').value,
      commitment_version: firstLoginState.commitmentVersion
    }) });
    const data = await res.json();
    if (data.status !== "ok" || data.accepted !== true || data.commitment_version !== firstLoginState.commitmentVersion) throw new Error("免责声明未确认保存");
    firstLoginState.disclaimerAccepted = true;
    if (modal) setUISurface("disclaimerModal", false);
    maybeOpenFirstLogin();
    showToast("欢迎使用 BUAA 课程独立签到助手！", "success");
  } catch (e) {
    showToast("保存免责声明状态失败", "error");
  } finally {
    firstLoginState.accepting = false;
    handleDisclaimerCheckChange(checkbox);
  }
}

function handleDisclaimerDecline() {
  requestAppExit();
}

async function initAutostartWidget() {
  try {
    const res = await apiFetch("/api/system/autostart");
    const data = await res.json();
    const checkbox = document.getElementById("autostartCheckbox");
    if (checkbox) checkbox.checked = !!data.enabled;
  } catch (e) {}
}

async function toggleAutostart(enabled) {
  try {
    const res = await apiFetch("/api/system/autostart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: enabled }),
    });
    const data = await res.json();
    const checkbox = document.getElementById("autostartCheckbox");
    if (checkbox) checkbox.checked = !!data.enabled;
    if (data.status !== "ok") { showToast("系统未确认自启修改，已恢复实际状态", "error"); return; }
    showToast(data.persisted === false ? "系统自启状态已更新，但配置保存失败" : data.enabled ? "开机自启已开启 (开机静默常驻托盘)" : "开机自启已关闭", data.persisted === false ? "warning" : "info");
  } catch (e) {
    showToast("切换开机自启动失败", "error");
  }
}

// 安全退出软件
async function requestAppExit() {
  if (runtimeCapabilities.exit_behavior !== 'application') {
    if (!confirm('仅退出当前浏览器管理会话？\n服务器后台任务继续运行。')) return;
    try {
      await apiFetch('/api/session', { method: 'DELETE' });
      // A reload would immediately create a new loopback session when the
      // local headless service has no password. Clear the entire document and
      // its polling instead, without terminating the shared application.
      window.location.replace('about:blank');
    } catch { showToast('退出管理未完成，请检查连接后重试', 'error'); }
    return;
  }
  if (!confirm("确定彻底退出 BUAA 课程独立签到助手吗？\n退出后后台所有学生的自动签到及博雅守护将停止。")) {
    return;
  }
  showToast("正在安全关闭后台服务进程...", "info");
  try {
    await apiFetch("/api/exit", { method: "POST" });
  } catch (e) {}
  setTimeout(() => {
    window.close();
  }, 400);
}

// 消息提示 (Origin Toast)
function confirmedCheckIcon() {
  return '<svg class="confirmed-check" viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.4"/><path d="m6.2 10 2.5 2.6 5.1-5.3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
}

function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `origin-toast ${type}`;
  toast.innerHTML = `
    ${type === 'success' ? `<span class="toast-confirmed-mark">${confirmedCheckIcon()}</span>` : `<span class="origin-status-dot ${type === 'error' ? 'amber' : 'cyan'}"></span>`}
    <span>${escapeHtml(message)}</span>
  `;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(30px)";
    toast.style.transition = "opacity 0.25s ease, transform 0.25s ease";
    setTimeout(() => toast.remove(), 250);
  }, 3200);
}

function escapeHtml(text) {
  if (!text) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}


// ==================== 6. Gemini iOS 极光与星尘粒子引擎 & 毛玻璃材质控制器 ====================

let ambientAnimFrameId = null;

function initAmbientCanvas() {
  const canvas = document.getElementById("ambientParticlesCanvas");
  if (!canvas) return;
  try {
    window.BuaaStitchAmbient?.start(canvas);
  } catch {
    // A visual renderer failure must not interrupt account/API initialization.
    canvas.dataset.renderer = "css";
  }
}

// ==================== 毛玻璃材质单滑杆透光度控制器 ====================

function initGlassControls() {
  let savedOpacity = "65";
  try { savedOpacity = localStorage.getItem("origin_glass_opacity") || "65"; } catch { /* Optional preference. */ }
  updateGlassOpacity(savedOpacity, false);

  const opacitySlider = document.getElementById("glassOpacitySlider");
  if (opacitySlider) opacitySlider.value = document.getElementById("opacityValLabel").textContent.replace("%", "");

  // 点击外部关闭弹窗
  document.addEventListener("click", (e) => {
    if (window.BUAAUiSurfaces) return;
    const wrapper = document.getElementById("glassControlWrapper");
    const popover = document.getElementById("glassPopover");
    if (popover && !popover.classList.contains("hidden")) {
      if (wrapper && !wrapper.contains(e.target)) {
        setUISurface("glassPopover", false);
      }
    }
  });
}

function toggleGlassPopover(event) {
  if (event) event.stopPropagation();
  const popover = document.getElementById("glassPopover");
  if (popover) {
    setUISurface("glassPopover", popover.classList.contains("hidden"));
  }
}

function updateGlassOpacity(val, save = true) {
  const parsed = Number(val);
  const numVal = Number.isFinite(parsed) ? Math.max(1, Math.min(90, Math.round(parsed))) : 65;
  const opacityDecimal = (numVal / 100).toFixed(2);
  // Extend the same visual curve down to1%; preserve the existing65% default.
  const blurPx = Math.round(18 + (numVal / 100) * 32);

  document.documentElement.style.setProperty("--glass-opacity", opacityDecimal);
  document.documentElement.style.setProperty("--glass-blur", `${blurPx}px`);

  const label = document.getElementById("opacityValLabel");
  const pillText = document.getElementById("glassPercentText");
  if (label) label.textContent = `${numVal}%`;
  if (pillText) pillText.textContent = `透光 ${numVal}%`;
  const slider = document.getElementById("glassOpacitySlider");
  if (slider) slider.value = String(numVal);

  if (save) {
    try { localStorage.setItem("origin_glass_opacity", numVal.toString()); } catch { /* Session appearance still works. */ }
  }
}
