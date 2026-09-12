/**
 * BUAA 课程签到 Pro v1.2.0 - Origin Web 前端核心交互引擎
 * 严谨金融级界面驱动：多学生并发、常规考勤守护、自动博雅套件、实时终端日志
 */

let appState = {
  authenticated: false,
  activeUsername: "",
  activeUser: null,
  accounts: [],
  mode: "direct",
  globalAutoCheckin: true,
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
    campus: "北京",
    scheduler_running: false,
  },
};

// 页面生命周期初始化
document.addEventListener("DOMContentLoaded", () => {
  initClock();
  initAmbientCanvas();
  initGlassControls();
  checkDisclaimerStatus();
  initAutostartWidget();
  fetchInitialState();
  startLogsPolling();
});

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
  appState.currentMainView = viewName;
  
  // 更新导航激活状态
  document.querySelectorAll(".origin-nav-item").forEach(item => item.classList.remove("active"));
  const btnMap = {
    regular: "navBtnRegular",
    boya: "navBtnBoya",
    logs: "navBtnLogs",
  };
  const activeBtn = document.getElementById(btnMap[viewName]);
  if (activeBtn) activeBtn.classList.add("active");

  // 更新面包屑文本
  const breadcrumb = document.getElementById("topbarCurrentSection");
  if (breadcrumb) {
    if (viewName === "regular") breadcrumb.textContent = "常规课堂考勤";
    else if (viewName === "boya") breadcrumb.textContent = "自动博雅套件 / 毕业学分与选课";
    else if (viewName === "logs") breadcrumb.textContent = "实时终端监控 / 系统全局审计";
  }

  // 显隐内容板块
  const vRegular = document.getElementById("viewRegular");
  const vBoya = document.getElementById("viewBoya");
  const vLogs = document.getElementById("viewLogs");

  if (vRegular) vRegular.classList.toggle("hidden", viewName !== "regular");
  if (vBoya) vBoya.classList.toggle("hidden", viewName !== "boya");
  if (vLogs) vLogs.classList.toggle("hidden", viewName !== "logs");

  if (viewName === "boya") {
    fetchBoyaData(false);
  } else if (viewName === "logs") {
    fetchLogs();
  }
}

// 获取全系统初始状态
async function fetchInitialState() {
  try {
    const [statusRes, accountsRes, configRes] = await Promise.all([
      fetch("/api/status").then(r => r.json()),
      fetch("/api/accounts").then(r => r.json()),
      fetch("/api/config").then(r => r.json()),
    ]);

    appState.accounts = accountsRes.accounts || [];
    appState.activeUsername = accountsRes.active_username || "";
    appState.activeUser = appState.accounts.find(a => a.username === appState.activeUsername) || null;

    appState.mode = statusRes.mode || "direct";
    appState.authenticated = statusRes.authenticated || false;
    appState.globalAutoCheckin = configRes.global_auto_checkin ?? true;

    updateUIElements();

    if (appState.authenticated || appState.accounts.length > 0) {
      fetchClasses();
      fetchBoyaData(false);
    } else if (appState.accounts.length === 0) {
      openLoginModal();
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
  }
}

// ==================== 1. 常规课堂考勤逻辑 ====================

async function fetchClasses() {
  try {
    const res = await fetch("/api/classes");
    const data = await res.json();
    if (data.classes) {
      appState.classes = data.classes;
      renderClassesList(data.classes);
    }
  } catch (e) {
    console.error("fetchClasses error:", e);
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
  const pending = total - signed;

  const badgeEl = document.getElementById("navBadgeClasses");
  const mTotal = document.getElementById("metricTotalClasses");
  const mSigned = document.getElementById("metricSignedClasses");
  const mPending = document.getElementById("metricPendingClasses");

  if (badgeEl) badgeEl.textContent = total;
  if (mTotal) mTotal.textContent = total;
  if (mSigned) mSigned.textContent = signed;
  if (mPending) mPending.textContent = pending;

  if (!classes || classes.length === 0) {
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
                ${isSigned ? '✓ 已完成签到' : '⏳ 待签到'}
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
          <span style="font-size:12px;color:var(--text-muted);">上课前10分钟自动签到</span>
          ${isSigned ? `
            <button class="origin-btn origin-btn-ghost" disabled style="opacity:0.6;">已签到</button>
          ` : `
            <button class="origin-btn origin-btn-primary" onclick="manualSignIn('${schedId}')">立即打卡</button>
          `}
        </div>
      </div>
    `;
  }).join("");
}

async function manualSignIn(courseSchedId) {
  showToast(`正在提交排课 ID [${courseSchedId}] 签到请求...`, "info");
  try {
    const res = await fetch("/api/signin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: String(courseSchedId) }),
    });
    const data = await res.json();
    if (data.status === "success" || data.success) {
      showToast("常规课程签到成功！", "success");
      fetchClasses();
    } else {
      showToast(`签到反馈: ${data.message || "未能成功"}`, "error");
    }
  } catch (e) {
    showToast("签到通信异常，请检查网络通道", "error");
  }
}

async function toggleAutoCheckin(enabled) {
  try {
    await fetch("/api/auto_checkin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: enabled }),
    });
    appState.globalAutoCheckin = enabled;
    showToast(`常规课程自动签到已${enabled ? "启动守护" : "暂停"}`, "info");
  } catch (e) {
    showToast("切换自动打卡状态失败", "error");
  }
}

// ==================== 2. 自动博雅全套逻辑 (四大门类与多维筛选) ====================

// 严格归一化为北航官方四大门类：美育、劳育、国家安全、德育
function normalizeBoyaCategory(c) {
  const raw = [
    c.courseKind,
    c.kindName,
    c.courseType,
    (c.courseNewKind2 && c.courseNewKind2.kindName),
    c.courseName
  ].filter(Boolean).join(" ");

  if (raw.includes("美育") || raw.includes("艺术") || raw.includes("音乐") || raw.includes("书画") || raw.includes("审美")) return "美育";
  if (raw.includes("劳育") || raw.includes("劳动") || raw.includes("工程实践") || raw.includes("实训") || raw.includes("制造")) return "劳育";
  if (raw.includes("安全") || raw.includes("国家安全") || raw.includes("国防") || raw.includes("保密") || raw.includes("网安")) return "国家安全";
  if (raw.includes("德育") || raw.includes("思政") || raw.includes("精神") || raw.includes("道德") || raw.includes("诚信") || raw.includes("报国")) return "德育";
  return "美育"; // 默认规范归类
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
  if (isManual) showToast("正在同步博雅学分与最新课表...", "info");
  try {
    const [coursesRes, selectedRes, statusRes, statsRes] = await Promise.all([
      fetch("/api/boya/courses").then(r => r.json()).catch(() => ({ courses: [] })),
      fetch("/api/boya/selected").then(r => r.json()).catch(() => ({ selected: [] })),
      fetch("/api/boya/status").then(r => r.json()).catch(() => ({})),
      fetch("/api/boya/statistics").then(r => r.json()).catch(() => ({ statistics: {} })),
    ]);

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
    }

    renderBoyaStatistics(appState.boyaStatistics);
    renderBoyaFeed();
    if (isManual) showToast(`博雅数据同步完成，共载入 ${appState.boyaCourses.length} 门课程`, "success");
  } catch (e) {
    console.error("fetchBoyaData error:", e);
    if (isManual) showToast("博雅数据拉取异常", "error");
  }
}

function renderBoyaStatistics(stats) {
  const earned = stats.total_credits ?? stats.totalCredit ?? 0.0;
  const target = stats.total_required ?? stats.requiredCredit ?? 4.0;
  const rate = Math.min(100, Math.round((earned / target) * 100));

  const elEarned = document.getElementById("boyaEarnedCredits");
  const elRate = document.getElementById("boyaCompletionRate");
  const elFill = document.getElementById("boyaProgressFill");

  if (elEarned) elEarned.textContent = Number(earned).toFixed(1);
  if (elRate) elRate.textContent = `达成度 ${rate}%`;
  if (elFill) elFill.style.width = `${rate}%`;

  // 从后端统计或已选课程中动态核算四大官方类别
  let art = stats.art_courses_count ?? stats.artCount ?? 0;
  let labor = stats.labor_courses_count ?? stats.laborCount ?? 0;
  let sec = stats.security_courses_count ?? stats.securityCount ?? 0;
  let moral = stats.moral_courses_count ?? stats.moralCount ?? 0;

  for (const c of appState.boyaSelected) {
    const cat = normalizeBoyaCategory(c);
    if (cat === "美育") art = Math.max(art, 1);
    else if (cat === "劳育") labor = Math.max(labor, 1);
    else if (cat === "国家安全") sec = Math.max(sec, 1);
    else if (cat === "德育") moral = Math.max(moral, 1);
  }

  const pArt = document.getElementById("pillArt");
  const pLabor = document.getElementById("pillLabor");
  const pSec = document.getElementById("pillSec");
  const pMoral = document.getElementById("pillMoral");

  if (pArt) pArt.textContent = `${art} 门`;
  if (pLabor) pLabor.textContent = `${labor} 门`;
  if (pSec) pSec.textContent = `${sec} 门`;
  if (pMoral) pMoral.textContent = `${moral} 门`;
}


// 时间范围解析判定 (未来及正在进行 vs 历史选课)
function getCourseEndDateTime(c) {
  const endDate = c.courseEndDate || c.courseStartDate;
  const endTime = c.courseEndTime || c.courseStartTime || "23:59";
  if (!endDate) return null;
  const cleanDate = endDate.trim().slice(0, 10);
  const cleanTime = endTime.trim().slice(0, 5);
  const dt = new Date(`${cleanDate}T${cleanTime}:00`);
  return isNaN(dt.getTime()) ? null : dt;
}

function isCourseOngoingOrUpcoming(c) {
  const endDt = getCourseEndDateTime(c);
  if (!endDt) return true;
  return new Date() <= endDt;
}

function isCoursePast(c) {
  const endDt = getCourseEndDateTime(c);
  if (!endDt) return false;
  return new Date() > endDt;
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

  let list = appState.boyaTab === "selected" ? appState.boyaSelected : appState.boyaCourses;

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
      const name = (c.courseName || c.name || "").toLowerCase();
      const teacher = (c.speaker || c.teacherName || c.courseTeacher || "").toLowerCase();
      const pos = (c.coursePosition || c.courseAddress || "").toLowerCase();
      const cid = String(c.id || c.courseId || "");
      return name.includes(appState.boyaSearchKeyword) || teacher.includes(appState.boyaSearchKeyword) || pos.includes(appState.boyaSearchKeyword) || cid.includes(appState.boyaSearchKeyword);
    });
  }

  // 2. 官方四大类别筛选
  if (appState.boyaCategoryFilter !== "全部") {
    list = list.filter(c => normalizeBoyaCategory(c) === appState.boyaCategoryFilter);
  }

  // 3. 仅显示支持线上自主打卡 (过滤掉线下人工核验课)
  if (appState.boyaAutoSignOnly) {
    list = list.filter(c => parseSignConfigPoints(c).length > 0);
  }

  // 4. 仅显示尚有名额
  if (appState.boyaAvailableOnly) {
    list = list.filter(c => {
      const cap = c.courseMaxCount ?? c.courseMaxNum ?? 0;
      const cur = c.courseCurrentCount ?? c.courseCurrentNum ?? 0;
      return cap === 0 || cur < cap;
    });
  }

  if (list.length === 0) {
    container.innerHTML = `
      <div class="origin-empty-state">
        <div class="empty-icon">🎯</div>
        <div class="empty-title">${appState.boyaTab === "selected" ? "暂无已选修课程" : "选课池中暂无匹配课程"}</div>
        <div class="empty-desc">${appState.boyaTab === "selected" ? "可切换至上方【全量选课池】挑选心仪的博雅课程立即抢选。" : "未找到符合当前多维筛选条件的课程，请调整类别、取消过滤器或更换搜索词。"}</div>
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
    const time = `${c.courseStartDate || ""} ${c.courseStartTime || ""}`.trim() || c.courseTime || "--";
    const location = c.coursePosition || c.courseAddress || "校内教室";
    const points = parseSignConfigPoints(c);
    const hasAutonomousSign = points.length > 0;
    const capacity = c.courseMaxCount ?? c.courseMaxNum ?? 0;
    const current = c.courseCurrentCount ?? c.courseCurrentNum ?? 0;
    const isFull = capacity > 0 && current >= capacity;
    const isPast = isCoursePast(c);

    return `
      <div class="feed-card ${hasAutonomousSign ? 'status-boya-auto' : ''}">
        <div class="feed-card-header">
          <div class="feed-title-col">
            <h4 class="feed-title">${escapeHtml(name)}</h4>
            <div class="feed-meta-row">
              <span class="feed-badge ${hasAutonomousSign ? 'badge-green' : 'badge-amber'}">
                ${hasAutonomousSign ? '🛰️ 线上自主打卡' : '⚠️ 线下人工核验 (不可自动选)'}
              </span>
              <span class="feed-badge badge-purple">${category}</span>
              ${!isSelected ? `<span class="quota-text ${isFull ? 'full' : ''}">名额: ${current}/${capacity}</span>` : ''}
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
            isPast ? `
              <div style="display:flex;justify-content:space-between;align-items:center;width:100%;">
                <span style="font-size:12px;color:var(--text-muted);">📜 该课程已结课</span>
                <span class="feed-badge badge-green">已完成归档</span>
              </div>
            ` : `
              <div style="display:flex;gap:8px;width:100%;justify-content:flex-end;">
                <button class="origin-btn origin-btn-danger-ghost" onclick="dropBoyaCourse('${courseId}')">退选</button>
                <button class="origin-btn origin-btn-secondary" onclick="boyaSign('${courseId}', 2)">定位签退</button>
                <button class="origin-btn origin-btn-primary" onclick="boyaSign('${courseId}', 1)">定位签到</button>
              </div>
            `
          ) : `
            <div style="display:flex;justify-content:space-between;align-items:center;width:100%;">
              <span style="font-size:12px;color:var(--text-muted);">${isFull ? '⚠️ 名额已满' : '✅ 名额充裕'}</span>
              ${hasAutonomousSign && !isFull ? `
                <button class="origin-btn origin-btn-primary" onclick="selectBoyaCourse('${courseId}')">立即抢课</button>
              ` : `
                <button class="origin-btn origin-btn-ghost" disabled style="opacity:0.45;">
                  ${!hasAutonomousSign ? '线下核验课不可选' : '名额已满'}
                </button>
              `}
            </div>
          `}
        </div>
      </div>
    `;
  }).join("");
}

async function selectBoyaCourse(id) {
  showToast(`正在发送抢选请求: [ID:${id}]...`, "info");
  try {
    const res = await fetch("/api/boya/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: parseInt(id, 10) || id }),
    });
    const d = await res.json();
    if (d.status === "ok" || d.status === "success" || d.code === 0 || d.code === "0") {
      showToast("抢课成功！已加入已选修课表", "success");
      fetchBoyaData();
    } else {
      showToast(`抢选提示: ${d.message || d.msg || "未能选上"}`, "error");
    }
  } catch (e) {
    showToast("抢课通信请求异常", "error");
  }
}

async function dropBoyaCourse(id) {
  if (!confirm("确定要退选该博雅课程吗？")) return;
  showToast(`正在发送退选请求: [ID:${id}]...`, "info");
  try {
    const res = await fetch("/api/boya/drop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: parseInt(id, 10) || id }),
    });
    const d = await res.json();
    if (d.status === "ok" || d.status === "success" || d.code === 0 || d.code === "0") {
      showToast("已成功退选该课程", "success");
      fetchBoyaData();
    } else {
      showToast(`退选失败: ${d.message || d.msg || ""}`, "error");
    }
  } catch (e) {
    showToast("退选通信请求异常", "error");
  }
}

async function boyaSign(id, signType) {
  const typeText = signType === 1 ? "签到" : "签退";
  showToast(`正在执行高斯微扰定位${typeText}...`, "info");
  try {
    const res = await fetch("/api/boya/sign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: parseInt(id, 10) || id, sign_type: signType }),
    });
    const d = await res.json();
    if (d.status === "ok" || d.status === "success" || d.code === 0 || d.code === "0") {
      showToast(`博雅${typeText}成功！`, "success");
      fetchBoyaData();
    } else {
      showToast(`打卡提示: ${d.message || d.msg || "未成功"}`, "error");
    }
  } catch (e) {
    showToast("打卡通信异常", "error");
  }
}

async function toggleBoyaAutoSelect(enabled) {
  try {
    await fetch("/api/boya/toggle_auto", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_select: enabled }),
    });
    showToast(`博雅自动秒抢已${enabled ? "开启守护" : "关闭"}`, "info");
  } catch (e) {}
}

async function toggleBoyaAutoSign(enabled) {
  try {
    await fetch("/api/boya/toggle_auto", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_sign: enabled }),
    });
    showToast(`博雅微扰自动打卡已${enabled ? "开启守护" : "关闭"}`, "info");
  } catch (e) {}
}

async function changeBoyaCampus(campus) {
  try {
    await fetch("/api/boya/toggle_auto", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ campus: campus }),
    });
    showToast(`生源校区偏好已更新为: ${campus}`, "info");
    fetchBoyaData();
  } catch (e) {}
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
  fetchLogs();
}

function startLogsPolling() {
  if (appState.logsTimer) clearInterval(appState.logsTimer);
  fetchLogs();
  appState.logsTimer = setInterval(fetchLogs, 2500);
}

async function fetchLogs() {
  const container = document.getElementById("logsContainer");
  if (!container) return;

  // 更新终端标题，显示当前绑定的学生与分类
  const titleEl = document.getElementById("logTerminalTitle");
  if (titleEl) {
    const studentName = appState.activeUser ? (appState.activeUser.name || appState.activeUser.username) : "系统全部";
    const catLabel = appState.currentLogCategory === "boya" ? "自动博雅" : (appState.currentLogCategory === "regular" ? "常规课程" : "总日志");
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
    const res = await fetch(url);
    const data = await res.json();
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
  } catch (e) {}
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
    await fetch(url, { method: "POST" });
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
  if (modal) modal.classList.remove("hidden");
}

function closeAccountCardsModal() {
  const modal = document.getElementById("accountCardsModal");
  if (modal) modal.classList.add("hidden");
}

function renderAccountsModal() {
  const container = document.getElementById("accountsModalList");
  if (!container) return;

  container.innerHTML = appState.accounts.map(acc => {
    const isActive = acc.username === appState.activeUsername;
    const initial = (acc.name || acc.username).slice(0, 1);

    return `
      <div class="origin-user-capsule" style="padding:12px;margin-bottom:8px;border-color:${isActive ? 'var(--accent-cyan)' : 'var(--border)'}" onclick="switchStudentAccount('${acc.username}')">
        <div class="origin-avatar">${escapeHtml(initial)}</div>
        <div class="origin-user-info">
          <div class="origin-user-name">${escapeHtml(acc.name || acc.username)} ${isActive ? '<span class="origin-tag">当前活跃</span>' : ''}</div>
          <div class="origin-user-id">学号: ${escapeHtml(acc.username)} · 模式: ${acc.mode === 'webvpn' ? 'WebVPN' : '直连'}</div>
        </div>
        <div>
          <button class="origin-btn origin-btn-danger-ghost" onclick="event.stopPropagation(); deleteAccount('${acc.username}')">删除</button>
        </div>
      </div>
    `;
  }).join("");
}

async function switchStudentAccount(username) {
  try {
    const res = await fetch("/api/accounts/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username }),
    });
    const d = await res.json();
    if (d.status === "ok") {
      appState.activeUsername = username;
      appState.activeUser = appState.accounts.find(a => a.username === username);
      updateUIElements();
      closeAccountCardsModal();
      fetchClasses();
      fetchBoyaData();
      fetchLogs();
      showToast(`已切换至学生: ${appState.activeUser ? appState.activeUser.name : username}`, "success");
    }
  } catch (e) {}
}

async function deleteAccount(username) {
  if (!confirm(`确定删除学号 ${username} 的账号配置吗？`)) return;
  try {
    await fetch(`/api/accounts/${username}`, { method: "DELETE" });
    appState.accounts = appState.accounts.filter(a => a.username !== username);
    renderAccountsModal();
    updateUIElements();
    showToast("账号已移除", "info");
  } catch (e) {}
}

function openLoginModalFromCenter() {
  closeAccountCardsModal();
  openLoginModal();
}

function openLoginModal() {
  const m = document.getElementById("loginModal");
  if (m) m.classList.remove("hidden");
}

function closeLoginModal() {
  const m = document.getElementById("loginModal");
  if (m) m.classList.add("hidden");
}

async function handleLogin(e) {
  e.preventDefault();
  const u = document.getElementById("loginUsername").value.trim();
  const p = document.getElementById("loginPassword").value.trim();
  const m = document.getElementById("loginModeSelect").value;
  const rem = document.getElementById("rememberMe").checked;

  if (!u || !p) return;
  showToast("正在连接北航统一身份认证...", "info");

  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: u, password: p, mode: m, remember: rem }),
    });
    const data = await res.json();
    if (data.status === "success" || data.authenticated) {
      showToast("身份认证成功，已接入后台考勤守护", "success");
      closeLoginModal();
      fetchInitialState();
    } else {
      showToast(`登录失败: ${data.message || "账号密码错误"}`, "error");
    }
  } catch (err) {
    showToast("登录请求失败，请检查网络通道", "error");
  }
}

// 手动排课 ID 签到模态框
function openManualSignModal() {
  const m = document.getElementById("manualSignModal");
  if (m) m.classList.remove("hidden");
}

function closeManualSignModal() {
  const m = document.getElementById("manualSignModal");
  if (m) m.classList.add("hidden");
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
  const nextMode = appState.mode === "direct" ? "webvpn" : "direct";
  showToast(`正在切换至 ${nextMode === "webvpn" ? "WebVPN 外网" : "校园网直连"}...`, "info");
  try {
    const res = await fetch("/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: nextMode }),
    });
    const data = await res.json();
    appState.mode = data.mode;
    updateUIElements();
    showToast(`已成功切换至: ${data.mode === "webvpn" ? "WebVPN 外网通道" : "校园网直连"}`, "success");
  } catch (e) {
    showToast("切换网络通道失败", "error");
  }
}

// ==================== 5. 免责声明与开机自启 ====================

async function checkDisclaimerStatus() {
  try {
    const res = await fetch("/api/system/disclaimer");
    const data = await res.json();
    const modal = document.getElementById("disclaimerModal");
    if (modal) {
      if (!data.accepted) {
        modal.classList.remove("hidden");
      } else {
        modal.classList.add("hidden");
      }
    }
  } catch (e) {}
}

function handleDisclaimerCheckChange(checkbox) {
  const btn = document.getElementById("disclaimerAgreeBtn");
  if (btn) btn.disabled = !checkbox.checked;
}

async function handleDisclaimerAccept() {
  try {
    const res = await fetch("/api/system/disclaimer/accept", { method: "POST" });
    const data = await res.json();
    if (data.accepted) {
      const modal = document.getElementById("disclaimerModal");
      if (modal) modal.classList.add("hidden");
      showToast("欢迎使用 BUAA 课程独立签到助手！", "success");
    }
  } catch (e) {
    showToast("保存免责声明状态失败", "error");
  }
}

function handleDisclaimerDecline() {
  requestAppExit();
}

async function initAutostartWidget() {
  try {
    const res = await fetch("/api/system/autostart");
    const data = await res.json();
    const checkbox = document.getElementById("autostartCheckbox");
    if (checkbox) checkbox.checked = !!data.enabled;
  } catch (e) {}
}

async function toggleAutostart(enabled) {
  try {
    const res = await fetch("/api/system/autostart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: enabled }),
    });
    const data = await res.json();
    const checkbox = document.getElementById("autostartCheckbox");
    if (checkbox) checkbox.checked = !!data.enabled;
    showToast(data.enabled ? "开机自启已开启 (开机静默常驻托盘)" : "开机自启已关闭", "info");
  } catch (e) {
    showToast("切换开机自启动失败", "error");
  }
}

// 安全退出软件
async function requestAppExit() {
  if (!confirm("确定彻底退出 BUAA 课程独立签到助手吗？\n退出后后台所有学生的自动签到及博雅守护将停止。")) {
    return;
  }
  showToast("正在安全关闭后台服务进程...", "info");
  try {
    await fetch("/api/exit", { method: "POST" });
  } catch (e) {}
  setTimeout(() => {
    window.close();
  }, 400);
}

// 消息提示 (Origin Toast)
function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `origin-toast ${type}`;
  toast.innerHTML = `
    <span class="origin-status-dot ${type === 'success' ? 'green' : type === 'error' ? 'amber' : 'cyan'}"></span>
    <span>${escapeHtml(message)}</span>
  `;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(30px)";
    toast.style.transition = "all 0.25s ease";
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
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  let width = 0;
  let height = 0;
  let dpr = Math.min(window.devicePixelRatio || 1, 2);

  function resize() {
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);
  }
  resize();
  window.addEventListener("resize", () => {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    resize();
  });

  // 1. 流动极光光斑定义 (仿 Gemini App 多彩绚烂流光)
  const orbs = [
    { x: width * 0.25, y: height * 0.3, r: 380, color: "rgba(56, 189, 248, 0.26)", angle: 0, speed: 0.0006, rx: 140, ry: 90 },
    { x: width * 0.75, y: height * 0.25, r: 420, color: "rgba(168, 85, 247, 0.24)", angle: 2.1, speed: 0.0005, rx: 160, ry: 110 },
    { x: width * 0.5, y: height * 0.75, r: 440, color: "rgba(59, 130, 246, 0.28)", angle: 4.2, speed: 0.0007, rx: 120, ry: 130 },
    { x: width * 0.15, y: height * 0.8, r: 350, color: "rgba(16, 185, 129, 0.18)", angle: 1.2, speed: 0.0008, rx: 100, ry: 80 },
    { x: width * 0.85, y: height * 0.7, r: 360, color: "rgba(244, 114, 182, 0.16)", angle: 3.5, speed: 0.0006, rx: 110, ry: 95 }
  ];

  // 2. 悬浮星尘颗粒群
  const PARTICLE_COUNT = 65;
  const particles = [];
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    particles.push({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.35,
      vy: (Math.random() - 0.5) * 0.35 - 0.1, // 微微向上浮动
      size: Math.random() * 1.8 + 0.8,
      alpha: Math.random() * 0.6 + 0.2,
      baseAlpha: Math.random() * 0.6 + 0.2,
      pulseSpeed: Math.random() * 0.02 + 0.008,
      pulsePhase: Math.random() * Math.PI * 2,
      color: i % 4 === 0 ? "rgba(125, 211, 252, " : (i % 4 === 1 ? "rgba(192, 132, 252, " : "rgba(255, 255, 255, ")
    });
  }

  // 鼠标交互微阻尼
  let mouse = { x: width / 2, y: height / 2, targetX: width / 2, targetY: height / 2 };
  window.addEventListener("mousemove", (e) => {
    mouse.targetX = e.clientX;
    mouse.targetY = e.clientY;
  });

  let lastTime = performance.now();

  function render(now) {
    const dt = Math.min(now - lastTime, 50);
    lastTime = now;

    // 缓动鼠标跟踪
    mouse.x += (mouse.targetX - mouse.x) * 0.04;
    mouse.y += (mouse.targetY - mouse.y) * 0.04;
    const mxShift = (mouse.x - width / 2) * 0.03;
    const myShift = (mouse.y - height / 2) * 0.03;

    ctx.clearRect(0, 0, width, height);

    // 绘制底层流动极光光斑
    ctx.save();
    ctx.globalCompositeOperation = "screen";
    for (const orb of orbs) {
      orb.angle += orb.speed * dt;
      const curX = orb.x + Math.cos(orb.angle) * orb.rx + mxShift;
      const curY = orb.y + Math.sin(orb.angle) * orb.ry + myShift;

      const grad = ctx.createRadialGradient(curX, curY, 0, curX, curY, orb.r);
      grad.addColorStop(0, orb.color);
      grad.addColorStop(0.5, orb.color.replace(/[\d\.]+\)$/, "0.08)"));
      grad.addColorStop(1, "rgba(0, 0, 0, 0)");

      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(curX, curY, orb.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();

    // 绘制微光星尘颗粒
    ctx.save();
    for (const p of particles) {
      p.x += p.vx;
      p.y += p.vy;

      // 屏幕环绕
      if (p.x < -10) p.x = width + 10;
      else if (p.x > width + 10) p.x = -10;
      if (p.y < -10) p.y = height + 10;
      else if (p.y > height + 10) p.y = -10;

      // 呼吸闪烁
      p.pulsePhase += p.pulseSpeed;
      const curAlpha = p.baseAlpha * (0.65 + 0.35 * Math.sin(p.pulsePhase));

      ctx.fillStyle = p.color + curAlpha + ")";
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();

    ambientAnimFrameId = requestAnimationFrame(render);
  }

  ambientAnimFrameId = requestAnimationFrame(render);
}

// ==================== 毛玻璃材质单滑杆透光度控制器 ====================

function initGlassControls() {
  const savedOpacity = localStorage.getItem("origin_glass_opacity") || "65";
  updateGlassOpacity(savedOpacity, false);

  const opacitySlider = document.getElementById("glassOpacitySlider");
  if (opacitySlider) opacitySlider.value = savedOpacity;

  // 点击外部关闭弹窗
  document.addEventListener("click", (e) => {
    const wrapper = document.getElementById("glassControlWrapper");
    const popover = document.getElementById("glassPopover");
    if (popover && !popover.classList.contains("hidden")) {
      if (wrapper && !wrapper.contains(e.target)) {
        popover.classList.add("hidden");
      }
    }
  });
}

function toggleGlassPopover(event) {
  if (event) event.stopPropagation();
  const popover = document.getElementById("glassPopover");
  if (popover) {
    popover.classList.toggle("hidden");
  }
}

function updateGlassOpacity(val, save = true) {
  const numVal = parseInt(val, 10);
  const opacityDecimal = (numVal / 100).toFixed(2);
  // 单一滑杆联动自动优化背景景深模糊度 (20% -> 24px, 65% -> 39px, 90% -> 47px)
  const blurPx = Math.round(18 + (numVal / 100) * 32);

  document.documentElement.style.setProperty("--glass-opacity", opacityDecimal);
  document.documentElement.style.setProperty("--glass-blur", `${blurPx}px`);

  const label = document.getElementById("opacityValLabel");
  const pillText = document.getElementById("glassPercentText");
  if (label) label.textContent = `${numVal}%`;
  if (pillText) pillText.textContent = `透光 ${numVal}%`;

  if (save) {
    localStorage.setItem("origin_glass_opacity", numVal.toString());
  }
}

