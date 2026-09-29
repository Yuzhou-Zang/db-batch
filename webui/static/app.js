const state = {
  accounts: [],
  tasks: [],
  loginSessionId: null,
  loginPlatform: "doubao",
  enabledPlatforms: ["doubao"],
  platformSettingsLoaded: false,
  platformSettingsSaving: false,
  accountBulkSaving: false,
  showHiddenTasks: false,
  runtime: null,
  selectedRunId: null,
  viewingDirectRun: false,
  runFilter: "unprocessed",
  draggedRunId: null,
  runtimeLogCursor: 0,
  runtimeLogTimer: null,
  activeView: location.hash === "#tasks" ? "tasks" : "accounts",
};

const $ = (selector) => document.querySelector(selector);

function platformLabel(platform) {
  return platform === "dola" ? "Dola" : "豆包";
}

function availableAccountCount(platform) {
  return state.accounts.filter((account) =>
    (account.platform || "doubao") === platform
    && account.enabled
    && account.cookie_exists
    && !account.quota_exhausted_today
  ).length;
}

function renderPlatformSettings() {
  document.querySelectorAll(".runtime-platform").forEach((checkbox) => {
    checkbox.checked = state.enabledPlatforms.includes(checkbox.value);
    const runtimeBusy = Boolean(
      state.runtime?.queue_running
      || state.runtime?.active_run_id
      || state.runtime?.direct_active
    );
    checkbox.disabled = state.platformSettingsSaving || runtimeBusy;
  });
  $("#doubao-account-count").textContent = `${availableAccountCount("doubao")}个可用`;
  $("#dola-account-count").textContent = `${availableAccountCount("dola")}个可用`;
}

async function loadPlatformSettings() {
  const settings = await api("/api/settings/platforms");
  state.enabledPlatforms = settings.enabled_platforms;
  state.platformSettingsLoaded = true;
  renderPlatformSettings();
}

async function savePlatformSettings(event) {
  const enabledPlatforms = [...document.querySelectorAll(".runtime-platform:checked")]
    .map((checkbox) => checkbox.value);
  if (enabledPlatforms.length === 0) {
    event.target.checked = true;
    return showNotice("至少选择一个运行平台。", true);
  }

  state.platformSettingsSaving = true;
  renderPlatformSettings();
  try {
    const settings = await api("/api/settings/platforms", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled_platforms: enabledPlatforms }),
    });
    state.enabledPlatforms = settings.enabled_platforms;
    showNotice(`运行平台已更新：${state.enabledPlatforms.map(platformLabel).join("、")}。`);
  } catch (error) {
    showNotice(error.message, true);
    await loadPlatformSettings();
  } finally {
    state.platformSettingsSaving = false;
    renderPlatformSettings();
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showNotice(message, error = false) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.classList.toggle("error", error);
  notice.hidden = false;
  clearTimeout(showNotice.timer);
  showNotice.timer = setTimeout(() => { notice.hidden = true; }, 5000);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let body = {};
  try { body = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(body.error || `请求失败：${response.status}`);
  return body;
}

function setView(name) {
  state.activeView = name;
  location.hash = name;
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  $(`#${name}-view`).classList.add("active");
}

async function loadAccounts() {
  state.accounts = await api("/api/accounts");
  renderAccounts();
  renderPlatformSettings();
}

function accountRow(account, index) {
  return `
    <tr>
      <td class="account-index">${index + 1}</td>
      <td>${escapeHtml(account.name)}</td>
      <td class="path"><code>${escapeHtml(account.cookie_path)}</code>${account.cookie_exists ? "" : "<br><span class='status failed'>文件不存在</span>"}</td>
      <td>${account.quota_exhausted_today
        ? "<span class='quota-badge'>今日额度已用完</span>"
        : "<span class='hint'>—</span>"}</td>
      <td><input type="checkbox" class="account-enabled" data-id="${account.id}" ${account.enabled ? "checked" : ""} aria-label="启用 ${escapeHtml(account.name)}"></td>
      <td class="actions">
        <button class="link edit-account" data-id="${account.id}">编辑</button>
        <button class="link danger-link delete-account" data-id="${account.id}">删除</button>
      </td>
    </tr>`;
}

function renderAccountGroup(platform, bodySelector) {
  const accounts = state.accounts.filter((account) =>
    (account.platform || "doubao") === platform
  );
  $(bodySelector).innerHTML = accounts.length
    ? accounts.map(accountRow).join("")
    : `<tr><td colspan="6" class="account-group-empty">暂无${platformLabel(platform)}账号</td></tr>`;
}

function renderAccountSummaries() {
  for (const platform of ["doubao", "dola"]) {
    const accounts = state.accounts.filter((account) =>
      (account.platform || "doubao") === platform
    );
    const enabledCount = accounts.filter((account) => account.enabled).length;
    $(`#${platform}-enabled-summary`).textContent = `${enabledCount}/${accounts.length}`;
  }
  $("#enable-all-accounts").disabled = state.accountBulkSaving || state.accounts.length === 0;
  $("#disable-all-accounts").disabled = state.accountBulkSaving || state.accounts.length === 0;
}

function renderAccounts() {
  renderAccountGroup("doubao", "#doubao-accounts-body");
  renderAccountGroup("dola", "#dola-accounts-body");
  $("#accounts-empty").hidden = state.accounts.length > 0;
  $("#account-tables").hidden = state.accounts.length === 0;
  renderAccountSummaries();
}

async function setAllAccountsEnabled(enabled) {
  if (state.accountBulkSaving || state.accounts.length === 0) return;
  state.accountBulkSaving = true;
  renderAccountSummaries();
  try {
    state.accounts = await api("/api/accounts/enabled", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    renderAccounts();
    renderPlatformSettings();
    showNotice(enabled ? "已启用全部账号。" : "已停用全部账号。");
  } catch (error) {
    showNotice(error.message, true);
    await loadAccounts();
  } finally {
    state.accountBulkSaving = false;
    renderAccountSummaries();
  }
}

function resetLoginDialog() {
  state.loginSessionId = null;
  state.loginPlatform = "doubao";
  $("#account-platform").value = "doubao";
  $("#account-name").value = "";
  $("#login-start-step").hidden = false;
  $("#login-save-step").hidden = true;
  $("#start-login").disabled = false;
  updateLoginPlatformCopy();
}

function updateLoginPlatformCopy() {
  const platform = $("#account-platform").value;
  const label = platformLabel(platform);
  $("#account-name").placeholder = `例如：${label}1号`;
  $("#account-login-hint").textContent = `点击后会打开${label}浏览器窗口，请在窗口中登录。`;
  $("#account-login-tip").textContent = `${label}窗口已打开。完成登录后，不需要等待检测，直接点击下面的保存按钮。`;
}

async function startLogin() {
  const name = $("#account-name").value.trim();
  const platform = $("#account-platform").value;
  if (!name) return showNotice("请先填写账号备注名。", true);
  $("#start-login").disabled = true;
  try {
    const result = await api("/api/accounts/login/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, platform }),
    });
    state.loginSessionId = result.session_id;
    state.loginPlatform = result.platform;
    $("#login-start-step").hidden = true;
    $("#login-save-step").hidden = false;
  } catch (error) {
    $("#start-login").disabled = false;
    showNotice(error.message, true);
  }
}

async function saveLogin() {
  if (!state.loginSessionId) return;
  $("#save-login").disabled = true;
  try {
    await api(`/api/accounts/login/${state.loginSessionId}/save`, { method: "POST" });
    $("#account-dialog").close();
    resetLoginDialog();
    await loadAccounts();
    showNotice("账号已保存。程序没有执行自动登录检测。")
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    $("#save-login").disabled = false;
  }
}

async function cancelLogin() {
  if (state.loginSessionId) {
    try { await api(`/api/accounts/login/${state.loginSessionId}/cancel`, { method: "POST" }); }
    catch (_) {}
  }
  $("#account-dialog").close();
  resetLoginDialog();
}

function scheduleLabel(task) {
  if (task.schedule_type === "once") {
    return task.schedule_pending
      ? `定时：${escapeHtml(task.scheduled_at.replace("T", " "))}`
      : "定时已执行";
  }
  return "手动运行";
}

async function loadTasks() {
  state.tasks = await api("/api/tasks");
  renderTasks();
}

function renderTasks() {
  const hiddenCount = state.tasks.filter((task) => task.hidden).length;
  const visibleTasks = state.showHiddenTasks
    ? state.tasks
    : state.tasks.filter((task) => !task.hidden);
  const body = $("#tasks-body");
  body.innerHTML = visibleTasks.map((task) => `
    <tr class="${task.hidden ? "hidden-task" : ""}">
      <td>${escapeHtml(task.name)}${task.hidden ? "<br><span class='hint'>已隐藏</span>" : ""}</td>
      <td><div class="prompt-preview">${escapeHtml(task.prompt.slice(0, 90))}${task.prompt.length > 90 ? "…" : ""}</div></td>
      <td>${task.images.length} 张<br><span class="hint">${escapeHtml(task.image_names.join("、"))}</span></td>
      <td>${task.count}</td>
      <td>${scheduleLabel(task)}</td>
      <td class="actions">
        <button class="link direct-task-control run-task" data-id="${task.id}" aria-label="立即运行 ${escapeHtml(task.name)}">▶&nbsp; 立即运行</button>
        <button class="link queue-task" data-id="${task.id}" aria-label="加入队列 ${escapeHtml(task.name)}">＋ 加入队列</button>
        <button class="link edit-task" data-id="${task.id}">编辑</button>
        <button class="link hide-task" data-id="${task.id}">${task.hidden ? "取消隐藏" : "隐藏"}</button>
        <button class="link danger-link delete-task" data-id="${task.id}">删除</button>
      </td>
    </tr>`).join("");
  $("#tasks-empty").hidden = visibleTasks.length > 0;
  $("#tasks-empty").textContent = state.tasks.length
    ? "当前任务都已隐藏，点击“全部显示”可以查看。"
    : "还没有任务，点击“新建任务”保存第一套提示词和参考图。";
  const showAllButton = $("#show-all-tasks");
  showAllButton.disabled = hiddenCount === 0;
  showAllButton.textContent = state.showHiddenTasks
    ? "只显示未隐藏"
    : `全部显示${hiddenCount ? `（隐藏 ${hiddenCount}）` : ""}`;
  if (state.runtime) updateImmediateRunButtons(state.runtime);
}

function openTaskDialog(task = null) {
  $("#task-form").reset();
  $("#task-blur").checked = true;
  $("#task-model").value = "Seedance 2.0 Fast";
  $("#task-count").value = 1;
  $("#task-retries").value = 3;
  $("#task-id").value = task?.id || "";
  $("#task-dialog-title").textContent = task ? "编辑任务" : "新建任务";
  $("#existing-images").textContent = task
    ? `已保存：${task.image_names.join("、")}。不重新选择图片将继续使用这些图片。`
    : "图片保存到任务文件夹，下次运行不需要重新上传。";
  if (task) {
    $("#task-name").value = task.name;
    $("#task-count").value = task.count;
    $("#task-prompt").value = task.prompt;
    $("#task-ratio").value = task.ratio;
    $("#task-model").value = task.model;
    $("#task-retries").value = task.max_retries;
    $("#task-output").value = task.output_dir;
    $("#schedule-type").value = task.schedule_type;
    $("#scheduled-at").value = task.scheduled_at || "";
    $("#task-blur").checked = Boolean(task.enable_blur);
    $("#task-headless").checked = Boolean(task.headless);
  }
  toggleScheduleField();
  $("#task-dialog").showModal();
}

function toggleScheduleField() {
  const isOnce = $("#schedule-type").value === "once";
  $("#scheduled-at-wrap").hidden = !isOnce;
  $("#scheduled-at").required = isOnce;
}

async function saveTask(event) {
  event.preventDefault();
  const taskId = $("#task-id").value;
  if (!taskId && $("#task-images").files.length === 0) {
    return showNotice("新建任务至少需要选择一张参考图片。", true);
  }
  const form = new FormData(event.currentTarget);
  const url = taskId ? `/api/tasks/${taskId}` : "/api/tasks";
  const method = taskId ? "PUT" : "POST";
  const submit = event.currentTarget.querySelector("button[type='submit']");
  submit.disabled = true;
  try {
    await api(url, { method, body: form });
    $("#task-dialog").close();
    await loadTasks();
    showNotice(taskId ? "任务已更新。" : "任务和参考图已保存。")
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    submit.disabled = false;
  }
}

async function submitTask(taskId, autoStart) {
  try {
    const action = autoStart ? "run" : "queue";
    const queued = await api(`/api/tasks/${taskId}/${action}`, { method: "POST" });
    state.viewingDirectRun = false;
    state.runFilter = "unprocessed";
    state.selectedRunId = queued.run_id;
    await loadRuntime();
  } catch (error) {
    showNotice(error.message, true);
  }
}

const statusNames = {
  idle: "空闲", queued: "排队中", running: "运行中", generating: "生成中",
  waiting: "等待中", completed: "已完成", completed_with_errors: "完成但有失败",
  failed: "失败", stopped: "已停止", cancelled: "已停止", cancelling: "正在停止",
  interrupted: "上次运行中断", waiting_for_account: "等待可用账号",
};

const statusIcons = {
  queued: "…", running: "▶", generating: "▶", waiting: "…",
  completed: "✓", completed_with_errors: "!", failed: "×",
  stopped: "■", cancelled: "■", cancelling: "■", interrupted: "!",
  waiting_for_account: "!", idle: "○",
};

const statusTitles = {
  queued: "任务等待运行", running: "任务运行中", generating: "正在生成视频",
  completed: "任务已完成", completed_with_errors: "任务完成但有失败",
  failed: "任务失败", stopped: "任务已停止", cancelled: "任务已停止", cancelling: "正在停止任务",
  interrupted: "任务运行中断", waiting_for_account: "正在等待可用账号",
};

const processedRunStatuses = new Set([
  "completed", "completed_with_errors", "failed", "cancelled", "interrupted",
  "waiting_for_account",
]);

function isProcessedRun(run) {
  return processedRunStatuses.has(run.status);
}

function filteredRuns(runtime, filter = state.runFilter) {
  const runs = runtime.queue_runs || [];
  if (filter === "processed") {
    return runs.filter(isProcessedRun).reverse();
  }
  return runs.filter((run) => !isProcessedRun(run));
}

function renderRunQueue(runtime) {
  const allRuns = runtime.queue_runs || [];
  const unprocessed = allRuns.filter((run) => !isProcessedRun(run));
  const processed = allRuns.filter(isProcessedRun);
  const runs = filteredRuns(runtime);
  $("#queue-count").textContent = allRuns.length;
  $("#unprocessed-count").textContent = unprocessed.length;
  $("#processed-count").textContent = processed.length;
  document.querySelectorAll(".run-filter").forEach((button) => {
    const active = button.dataset.runFilter === state.runFilter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $("#queue-empty").hidden = runs.length > 0;
  $("#queue-empty").textContent = state.runFilter === "processed"
    ? "还没有已处理的任务记录。"
    : "还没有未处理任务，请从上方立即运行或加入队列。";

  $("#run-queue").innerHTML = runs.map((run, index) => {
    const isStartAction = run.status === "stopped";
    const isStopAction = ["queued", "running", "cancelling"].includes(run.status);
    const actionEnabled = isStartAction || isStopAction;
    const movable = state.runFilter === "unprocessed"
      && ["queued", "stopped"].includes(run.status);
    return `
    <div class="queue-item ${run.run_id === state.selectedRunId ? "selected" : ""} ${movable ? "movable" : ""}"
         data-run-id="${run.run_id}" data-movable="${movable}" draggable="${movable}">
      <span class="drag-handle" title="拖拽调整顺序">⠿</span>
      <span class="queue-number">${index + 1}</span>
      <span class="queue-copy">
        <strong>${escapeHtml(run.task_name || "未命名任务")}</strong>
      </span>
      <span class="queue-state status ${run.status}">${statusNames[run.status] || escapeHtml(run.status)}</span>
      <span class="queue-actions">
        ${actionEnabled ? `<button type="button" class="queue-action toggle ${isStartAction ? "start" : "stop"}"
          data-toggle-run="${run.run_id}" data-action="${isStartAction ? "start" : "stop"}"
          title="${isStartAction ? "恢复排队" : run.status === "running" ? "停止当前任务并暂停队列" : "停止排队"}"
          aria-label="${isStartAction ? "恢复排队" : "停止"}">${isStartAction ? "▶" : "■"}</button>` : ""}
        <button type="button" class="queue-action delete" data-delete-run="${run.run_id}">删除</button>
      </span>
    </div>`;
  }).join("");
}

function updateImmediateRunButtons(runtime) {
  const running = Boolean(runtime.queue_running) || Boolean(runtime.active_run_id);
  document.querySelectorAll(".direct-task-control").forEach((button) => {
    button.classList.add("run-task");
    button.classList.remove("stop-direct-task");
    button.innerHTML = "▶&nbsp; 立即运行";
    button.disabled = running;
    button.title = running ? "当前有任务正在运行" : "立即运行这一项，完成后暂停队列";
    button.setAttribute("aria-label", "立即运行任务");
  });
}

function renderRunDetail(run, isDirect = false) {
  $("#detail-empty").hidden = Boolean(run);
  $("#runtime-detail").hidden = !run;
  if (!run) return;

  const status = run.status || "idle";
  $("#run-status-icon").textContent = statusIcons[status] || "?";
  $("#run-status-icon").className = `status-icon ${status}`;
  const title = statusTitles[status] || statusNames[status] || status;
  $("#run-status-title").textContent = title;
  $("#runtime-message").textContent = run.message || "等待状态更新。";
  $("#run-task-name").textContent = run.task_name || "—";
  $("#run-status").textContent = statusNames[status] || status;
  $("#run-status").className = `status ${status}`;
  $("#run-progress").textContent = `${run.completed_count || 0} / ${run.total_count || 0}`;
  $("#run-output-dir").textContent = run.output_dir || "—";

  const jobs = run.jobs || [];
  $("#jobs-table").hidden = jobs.length === 0;
  $("#jobs-empty").hidden = jobs.length > 0;
  $("#jobs-body").innerHTML = jobs.map((job) => {
    const detail = job.output_path
      ? `<code class="path">${escapeHtml(job.output_path)}</code>${job.warning ? `<br><span class="status waiting">${escapeHtml(job.warning)}</span>` : ""}`
      : escapeHtml(job.error || "—");
    return `<tr>
      <td>${job.index}</td>
      <td><span class="status ${job.status}">${statusNames[job.status] || escapeHtml(job.status)}</span></td>
      <td>${job.account_name ? `${platformLabel(job.platform)} / ${escapeHtml(job.account_name)}` : "—"}</td>
      <td class="path">${detail}</td>
    </tr>`;
  }).join("");
}

async function loadRuntime() {
  try {
    const runtime = await api("/api/runtime");
    state.runtime = runtime;
    $("#service-status").textContent = "服务已连接";
    $("#service-status").classList.remove("offline");
    const runs = runtime.queue_runs || [];
    const allRuns = [...runs];
    const selectedExists = allRuns.some((run) => run.run_id === state.selectedRunId);
    if (!selectedExists) {
      const preferredRun = filteredRuns(runtime)[0] || null;
      state.selectedRunId = preferredRun?.run_id || null;
    }
    const selectedRun = allRuns.find((run) => run.run_id === state.selectedRunId);
    if (selectedRun) {
      state.runFilter = isProcessedRun(selectedRun) ? "processed" : "unprocessed";
    }
    state.viewingDirectRun = false;
    if (!state.draggedRunId) renderRunQueue(runtime);
    renderRunDetail(selectedRun || null);

    const hasWaiting = runs.some((run) => run.status === "queued");
    const hasActiveTask = Boolean(runtime.active_run_id);
    $("#start-run").disabled = Boolean(runtime.queue_running) || hasActiveTask || !hasWaiting;
    $("#stop-run").disabled = !runtime.queue_running && !hasActiveTask;
    updateImmediateRunButtons(runtime);
    renderPlatformSettings();
  } catch (_) {
    $("#service-status").textContent = "服务已断开";
    $("#service-status").classList.add("offline");
  }
}

function formatLogTimestamp(value) {
  if (!value) return "--:--:--";
  const timePart = String(value).split("T")[1] || String(value);
  return timePart.slice(0, 12);
}

function runtimeLogContext(entry) {
  const tags = [];
  if (entry.task_name) tags.push(`任务:${entry.task_name}`);
  if (entry.job) tags.push(`视频:${entry.job}`);
  if (entry.platform) tags.push(`平台:${platformLabel(entry.platform)}`);
  if (entry.account_name) tags.push(`账号:${entry.account_name}`);
  return tags.map((tag) => `[${tag}]`).join("");
}

function appendRuntimeLogEntries(entries) {
  const container = $("#runtime-log-content");
  container.querySelector(".runtime-log-empty")?.remove();
  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = `runtime-log-line level-${String(entry.level || "info").toLowerCase()}`;

    const time = document.createElement("span");
    time.className = "runtime-log-time";
    time.textContent = formatLogTimestamp(entry.timestamp);

    const context = document.createElement("span");
    context.className = "runtime-log-context";
    context.textContent = runtimeLogContext(entry);

    const message = document.createElement("span");
    message.className = "runtime-log-message";
    message.textContent = entry.message;

    row.append(time, context, message);
    container.append(row);
  }
  if ($("#runtime-log-autoscroll").checked && entries.length) {
    container.scrollTop = container.scrollHeight;
  }
}

async function loadRuntimeLogs(reset = false) {
  if (!$("#runtime-log-dialog").open) return;
  if (reset) {
    state.runtimeLogCursor = 0;
    $("#runtime-log-content").innerHTML = '<div class="runtime-log-empty">正在读取日志……</div>';
  }
  try {
    const result = await api(`/api/runtime/logs?after=${state.runtimeLogCursor}`);
    const startedAt = String(result.session_started_at || "").replace("T", " ").slice(0, 19);
    $("#runtime-log-session").textContent = startedAt
      ? `本次服务启动时间：${startedAt}`
      : "显示本次服务启动以来的全部日志";
    appendRuntimeLogEntries(result.entries || []);
    state.runtimeLogCursor = result.latest_id || state.runtimeLogCursor;
    if (state.runtimeLogCursor === 0) {
      $("#runtime-log-content").innerHTML = '<div class="runtime-log-empty">本次服务启动后暂无日志。</div>';
    }
  } catch (error) {
    $("#runtime-log-content").innerHTML = `<div class="runtime-log-empty">日志读取失败：${escapeHtml(error.message)}</div>`;
  }
}

function stopRuntimeLogPolling() {
  if (state.runtimeLogTimer) clearInterval(state.runtimeLogTimer);
  state.runtimeLogTimer = null;
}

function openRuntimeLog() {
  const dialog = $("#runtime-log-dialog");
  dialog.showModal();
  loadRuntimeLogs(true);
  stopRuntimeLogPolling();
  state.runtimeLogTimer = setInterval(() => loadRuntimeLogs(false), 1000);
}

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

document.querySelectorAll("[data-close]").forEach((button) => {
  button.addEventListener("click", () => {
    const dialog = document.getElementById(button.dataset.close);
    if (dialog.id === "account-dialog" && state.loginSessionId) cancelLogin();
    else dialog.close();
  });
});

$("#add-account").addEventListener("click", () => {
  resetLoginDialog();
  $("#account-dialog").showModal();
});
$("#start-login").addEventListener("click", startLogin);
$("#save-login").addEventListener("click", saveLogin);
$("#cancel-login").addEventListener("click", cancelLogin);
$("#account-platform").addEventListener("change", updateLoginPlatformCopy);
$("#enable-all-accounts").addEventListener("click", () => setAllAccountsEnabled(true));
$("#disable-all-accounts").addEventListener("click", () => setAllAccountsEnabled(false));
document.querySelectorAll(".runtime-platform").forEach((checkbox) => {
  checkbox.addEventListener("change", savePlatformSettings);
});

$("#account-tables").addEventListener("change", async (event) => {
  if (!event.target.matches(".account-enabled")) return;
  try {
    const updated = await api(`/api/accounts/${event.target.dataset.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: event.target.checked }),
    });
    const index = state.accounts.findIndex((account) => account.id === updated.id);
    if (index >= 0) state.accounts[index] = { ...state.accounts[index], ...updated };
    renderAccountSummaries();
    renderPlatformSettings();
  } catch (error) { showNotice(error.message, true); await loadAccounts(); }
});

$("#account-tables").addEventListener("click", async (event) => {
  const id = event.target.dataset.id;
  if (!id) return;
  const account = state.accounts.find((item) => item.id === id);
  if (event.target.matches(".edit-account")) {
    const name = prompt("修改账号备注名", account.name);
    if (!name?.trim()) return;
    try {
      await api(`/api/accounts/${id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() }),
      });
      await loadAccounts();
    } catch (error) { showNotice(error.message, true); }
  }
  if (event.target.matches(".delete-account")) {
    if (!confirm(`确定删除账号“${account.name}”吗？新添加账号的 Cookie 会移入 data/trash。`)) return;
    try { await api(`/api/accounts/${id}`, { method: "DELETE" }); await loadAccounts(); }
    catch (error) { showNotice(error.message, true); }
  }
});

$("#add-task").addEventListener("click", () => openTaskDialog());
$("#show-all-tasks").addEventListener("click", () => {
  state.showHiddenTasks = !state.showHiddenTasks;
  renderTasks();
});
$("#schedule-type").addEventListener("change", toggleScheduleField);
$("#task-form").addEventListener("submit", saveTask);

$("#tasks-body").addEventListener("click", async (event) => {
  const id = event.target.dataset.id;
  if (!id) return;
  const task = state.tasks.find((item) => item.id === id);
  if (event.target.matches(".run-task")) return submitTask(id, true);
  if (event.target.matches(".queue-task")) return submitTask(id, false);
  if (event.target.matches(".edit-task")) return openTaskDialog(task);
  if (event.target.matches(".hide-task")) {
    try {
      await api(`/api/tasks/${id}/hidden`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hidden: !task.hidden }),
      });
      await loadTasks();
      showNotice(task.hidden ? "任务已恢复显示。" : "任务已隐藏，可通过“全部显示”找回。")
    } catch (error) { showNotice(error.message, true); }
    return;
  }
  if (event.target.matches(".delete-task")) {
    if (!confirm(`确定删除任务“${task.name}”吗？任务配置和参考图会移入 data/trash。`)) return;
    try { await api(`/api/tasks/${id}`, { method: "DELETE" }); await loadTasks(); }
    catch (error) { showNotice(error.message, true); }
  }
});

$("#start-run").addEventListener("click", async () => {
  try { await api("/api/runtime/start", { method: "POST" }); await loadRuntime(); }
  catch (error) { showNotice(error.message, true); }
});

$("#stop-run").addEventListener("click", async () => {
  try { await api("/api/runtime/stop", { method: "POST" }); await loadRuntime(); }
  catch (error) { showNotice(error.message, true); }
});

$("#open-runtime-log").addEventListener("click", openRuntimeLog);
$("#runtime-log-dialog").addEventListener("close", stopRuntimeLogPolling);

document.querySelectorAll(".run-filter").forEach((button) => {
  button.addEventListener("click", () => {
    state.runFilter = button.dataset.runFilter;
    const runs = filteredRuns(state.runtime || { queue_runs: [] });
    state.selectedRunId = runs[0]?.run_id || null;
    renderRunQueue(state.runtime || { queue_runs: [] });
    renderRunDetail(runs[0] || null);
  });
});

$("#run-queue").addEventListener("click", async (event) => {
  const toggleButton = event.target.closest("[data-toggle-run]");
  if (toggleButton) {
    event.stopPropagation();
    try {
      const action = toggleButton.dataset.action;
      await api(`/api/runtime/runs/${toggleButton.dataset.toggleRun}/${action}`, { method: "POST" });
      await loadRuntime();
    } catch (error) { showNotice(error.message, true); }
    return;
  }
  const deleteButton = event.target.closest("[data-delete-run]");
  if (deleteButton) {
    event.stopPropagation();
    const runId = deleteButton.dataset.deleteRun;
    try {
      await api(`/api/runtime/runs/${runId}`, { method: "DELETE" });
      if (state.selectedRunId === runId) state.selectedRunId = null;
      await loadRuntime();
    } catch (error) { showNotice(error.message, true); }
    return;
  }
  const item = event.target.closest("[data-run-id]");
  if (!item) return;
  state.viewingDirectRun = false;
  state.selectedRunId = item.dataset.runId;
  renderRunQueue(state.runtime);
  const runs = state.runtime.queue_runs || [];
  const run = runs.find((entry) => entry.run_id === state.selectedRunId);
  renderRunDetail(run || null);
});

$("#run-queue").addEventListener("dragstart", (event) => {
  const item = event.target.closest("[data-run-id]");
  if (!item || item.dataset.movable !== "true") return event.preventDefault();
  state.draggedRunId = item.dataset.runId;
  item.classList.add("dragging");
  event.dataTransfer.effectAllowed = "move";
});

$("#run-queue").addEventListener("dragend", (event) => {
  event.target.closest("[data-run-id]")?.classList.remove("dragging");
  state.draggedRunId = null;
});

$("#run-queue").addEventListener("dragover", (event) => {
  const target = event.target.closest("[data-run-id]");
  if (!state.draggedRunId || !target || target.dataset.movable !== "true") return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
});

$("#run-queue").addEventListener("drop", async (event) => {
  const target = event.target.closest("[data-run-id]");
  const sourceId = state.draggedRunId;
  if (!sourceId || !target || target.dataset.movable !== "true") return;
  event.preventDefault();
  const targetId = target.dataset.runId;
  if (sourceId === targetId) return;
  const movableIds = (state.runtime.queue_runs || [])
    .filter((run) => ["queued", "stopped"].includes(run.status))
    .map((run) => run.run_id);
  const sourceIndex = movableIds.indexOf(sourceId);
  const targetIndex = movableIds.indexOf(targetId);
  if (sourceIndex < 0 || targetIndex < 0) return;
  movableIds.splice(sourceIndex, 1);
  movableIds.splice(targetIndex, 0, sourceId);
  state.draggedRunId = null;
  try {
    await api("/api/runtime/order", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_ids: movableIds }),
    });
    await loadRuntime();
  } catch (error) { showNotice(error.message, true); }
});

async function init() {
  setView(state.activeView);
  try {
    await Promise.all([loadAccounts(), loadTasks(), loadRuntime(), loadPlatformSettings()]);
  } catch (error) {
    showNotice(error.message, true);
  }
  setInterval(loadRuntime, 2000);
  setInterval(loadAccounts, 5000);
  setInterval(loadTasks, 15000);
}

init();
