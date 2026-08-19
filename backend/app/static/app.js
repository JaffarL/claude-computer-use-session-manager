"use strict";

const EVENT_TYPES = [
  "session.status",
  "run.started",
  "assistant.delta",
  "assistant.message",
  "tool.started",
  "tool.result",
  "screenshot.available",
  "run.completed",
  "run.failed",
];

const ACTIVE_VNC_STATUSES = new Set(["READY", "RUNNING"]);
const RUNNABLE_STATUSES = new Set(["READY"]);
const STOPPABLE_STATUSES = new Set(["READY", "RUNNING", "STOPPING", "FAILED"]);

const state = {
  sessions: [],
  current: null,
  messages: [],
  events: [],
  lastEventId: 0,
  eventSource: null,
  selectionVersion: 0,
};

const elements = {
  sessionList: document.querySelector("#session-list"),
  sessionCount: document.querySelector("#session-count"),
  currentTitle: document.querySelector("#current-title"),
  currentStatus: document.querySelector("#current-status"),
  currentId: document.querySelector("#current-id"),
  messageList: document.querySelector("#message-list"),
  eventList: document.querySelector("#event-list"),
  eventCount: document.querySelector("#event-count"),
  streamState: document.querySelector("#stream-state"),
  taskInput: document.querySelector("#task-input"),
  submitRun: document.querySelector("#submit-run"),
  runForm: document.querySelector("#run-form"),
  stopSession: document.querySelector("#stop-session"),
  deleteSession: document.querySelector("#delete-session"),
  refreshSession: document.querySelector("#refresh-session"),
  reloadVnc: document.querySelector("#reload-vnc"),
  vncFrame: document.querySelector("#vnc-frame"),
  desktopPlaceholder: document.querySelector("#desktop-placeholder"),
  vncExpiry: document.querySelector("#vnc-expiry"),
  healthDot: document.querySelector("#health-dot"),
  healthLabel: document.querySelector("#health-label"),
  createDialog: document.querySelector("#create-dialog"),
  createForm: document.querySelector("#create-form"),
  sessionTitle: document.querySelector("#session-title"),
  confirmCreate: document.querySelector("#confirm-create"),
  toastRegion: document.querySelector("#toast-region"),
};

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers });
  if (response.status === 204) {
    return null;
  }
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = payload?.error?.message || payload?.detail?.[0]?.msg || `请求失败（${response.status}）`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function showToast(message, kind = "info") {
  const toast = document.createElement("div");
  toast.className = `toast ${kind}`;
  toast.textContent = message;
  elements.toastRegion.append(toast);
  window.setTimeout(() => toast.remove(), 4200);
}

function setBusy(button, busy, busyText = "处理中…") {
  if (!button.dataset.originalText) {
    button.dataset.originalText = button.textContent.trim();
  }
  button.disabled = busy;
  button.textContent = busy ? busyText : button.dataset.originalText;
}

function shortId(value) {
  return value ? value.slice(0, 8) : "—";
}

function localTime(value, includeSeconds = false) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: includeSeconds ? "2-digit" : undefined,
    hour12: false,
  }).format(new Date(value));
}

function statusClass(status) {
  return String(status || "neutral").toLowerCase();
}

function renderSessions() {
  elements.sessionCount.textContent = String(state.sessions.length);
  elements.sessionList.replaceChildren();

  if (!state.sessions.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state compact";
    empty.textContent = "暂无会话";
    elements.sessionList.append(empty);
    return;
  }

  for (const session of state.sessions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `session-item ${state.current?.id === session.id ? "active" : ""}`;
    button.dataset.sessionId = session.id;

    const top = document.createElement("span");
    top.className = "session-item-top";
    const title = document.createElement("span");
    title.className = "session-item-title";
    title.textContent = session.title || `会话 ${shortId(session.id)}`;
    const dot = document.createElement("span");
    dot.className = `mini-status ${statusClass(session.status)}`;
    dot.title = session.status;
    top.append(title, dot);

    const meta = document.createElement("span");
    meta.className = "session-item-meta";
    const id = document.createElement("span");
    id.textContent = shortId(session.id);
    const time = document.createElement("span");
    time.textContent = localTime(session.created_at);
    meta.append(id, time);
    button.append(top, meta);
    button.addEventListener("click", () => selectSession(session.id));
    elements.sessionList.append(button);
  }
}

function renderCurrentSession() {
  const session = state.current;
  if (!session) {
    elements.currentTitle.textContent = "请选择一个会话";
    elements.currentId.textContent = "创建会话后即可提交任务并观察隔离桌面";
    elements.currentStatus.textContent = "未选择";
    elements.currentStatus.className = "status-badge status-neutral";
    elements.streamState.textContent = "SSE 未连接";
    elements.streamState.className = "connection-state";
    setControlsEnabled(false);
    return;
  }

  elements.currentTitle.textContent = session.title || `会话 ${shortId(session.id)}`;
  elements.currentId.textContent = `${session.id} · runtime ${shortId(session.runtime_id)}`;
  elements.currentStatus.textContent = session.status;
  elements.currentStatus.className = `status-badge status-${statusClass(session.status)}`;
  setControlsEnabled(true);
}

function setControlsEnabled(hasSession) {
  const status = state.current?.status;
  elements.refreshSession.disabled = !hasSession;
  elements.deleteSession.disabled = !hasSession;
  elements.stopSession.disabled = !hasSession || !STOPPABLE_STATUSES.has(status);
  elements.taskInput.disabled = !hasSession || !RUNNABLE_STATUSES.has(status);
  elements.submitRun.disabled = !hasSession || !RUNNABLE_STATUSES.has(status);
  elements.reloadVnc.disabled = !hasSession || !ACTIVE_VNC_STATUSES.has(status);
}

function renderMessages() {
  elements.messageList.replaceChildren();
  if (!state.current) {
    renderMessageEmpty("还没有选择会话", "从左侧创建一个独立桌面，随后提交浏览器任务。");
    return;
  }
  if (!state.messages.length) {
    if (RUNNABLE_STATUSES.has(state.current.status)) {
      renderMessageEmpty("桌面已经就绪", "输入一个任务，Agent 的持久化消息会显示在这里。");
    } else {
      renderMessageEmpty(
        `会话当前为 ${state.current.status}`,
        "该状态下不能提交新任务；已有的持久化消息仍会保留。",
      );
    }
    return;
  }

  for (const message of state.messages) {
    const role = String(message.role).toLowerCase();
    const item = document.createElement("article");
    item.className = `message ${role}`;
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = role === "assistant" ? "AI" : role === "user" ? "YOU" : "SYS";
    const body = document.createElement("div");
    body.className = "message-body";
    const content = document.createElement("p");
    content.textContent = message.content?.text || JSON.stringify(message.content, null, 2);
    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = `#${message.sequence} · ${localTime(message.created_at, true)}`;
    body.append(content, meta);
    item.append(avatar, body);
    elements.messageList.append(item);
  }
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
}

function renderMessageEmpty(titleText, bodyText) {
  elements.messageList.className = "message-list empty-state";
  const icon = document.createElement("div");
  icon.className = "empty-illustration";
  icon.textContent = "⌁";
  const title = document.createElement("h4");
  title.textContent = titleText;
  const body = document.createElement("p");
  body.textContent = bodyText;
  elements.messageList.append(icon, title, body);
}

function eventSummary(event) {
  const payload = event.payload || {};
  if (payload.text) return payload.text;
  if (payload.input && typeof payload.input === "string") return payload.input;
  if (payload.input?.action) return `${payload.name || "tool"}: ${payload.input.action}`;
  if (payload.output) return String(payload.output);
  if (payload.status) return String(payload.status);
  if (payload.error) return `错误：${payload.error}`;
  if (payload.source) return `来源：${payload.source}`;
  return `event #${event.id}`;
}

function renderEvents() {
  elements.eventCount.textContent = `${state.events.length} events`;
  elements.eventList.replaceChildren();
  if (!state.events.length) {
    elements.eventList.className = "event-list empty-state compact";
    const text = document.createElement("p");
    text.textContent = state.current ? "事件会按 PostgreSQL ID 顺序出现在这里。" : "请选择一个会话。";
    elements.eventList.append(text);
    return;
  }

  elements.eventList.className = "event-list";
  for (const event of state.events.slice(-150)) {
    const item = document.createElement("article");
    const semanticClass = event.event_type.includes("failed")
      ? "failed"
      : event.event_type.includes("completed")
        ? "completed"
        : "";
    item.className = `event-item ${semanticClass}`;
    const time = document.createElement("time");
    time.className = "event-time";
    time.textContent = localTime(event.created_at, true);
    const node = document.createElement("span");
    node.className = "event-node";
    const content = document.createElement("div");
    content.className = "event-content";
    const type = document.createElement("div");
    type.className = "event-type";
    type.textContent = event.event_type;
    const summary = document.createElement("div");
    summary.className = "event-summary";
    summary.textContent = eventSummary(event);
    const details = document.createElement("details");
    const detailsTitle = document.createElement("summary");
    detailsTitle.textContent = `查看 payload · #${event.id}`;
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(event.payload, null, 2);
    details.append(detailsTitle, pre);
    content.append(type, summary, details);
    item.append(time, node, content);
    elements.eventList.append(item);
  }
  elements.eventList.scrollTop = elements.eventList.scrollHeight;
}

function addEvent(event) {
  const id = Number(event.id || 0);
  if (id && state.events.some((item) => Number(item.id) === id)) return;
  if (id) state.lastEventId = Math.max(state.lastEventId, id);
  state.events.push(event);
  state.events.sort((left, right) => Number(left.id) - Number(right.id));
  renderEvents();
}

async function loadSessions({ preserveSelection = true } = {}) {
  const payload = await api("/api/v1/sessions?offset=0&limit=100");
  state.sessions = payload.items;
  if (state.current) {
    const updated = state.sessions.find((session) => session.id === state.current.id);
    if (updated) state.current = updated;
  }
  renderSessions();
  renderCurrentSession();
  if (!preserveSelection && state.sessions.length) {
    await selectSession(state.sessions[0].id);
  }
}

async function selectSession(sessionId) {
  if (!sessionId) return;
  const version = ++state.selectionVersion;
  closeEventStream();
  clearDesktop("正在签发桌面访问令牌…");
  elements.streamState.textContent = "正在连接 SSE…";
  elements.streamState.className = "connection-state reconnecting";

  try {
    const [session, messages, history] = await Promise.all([
      api(`/api/v1/sessions/${sessionId}`),
      api(`/api/v1/sessions/${sessionId}/messages`),
      api(`/api/v1/sessions/${sessionId}/events/history?after_id=0&limit=1000`),
    ]);
    if (version !== state.selectionVersion) return;
    state.current = session;
    state.messages = messages.items;
    state.events = history.items;
    state.lastEventId = state.events.reduce((max, event) => Math.max(max, Number(event.id)), 0);
    renderSessions();
    renderCurrentSession();
    elements.messageList.className = "message-list";
    renderMessages();
    renderEvents();
    connectEventStream(sessionId, version);
    if (ACTIVE_VNC_STATUSES.has(session.status)) {
      await loadVnc(version);
    } else {
      clearDesktop(`当前状态 ${session.status}，桌面不可访问。`);
    }
  } catch (error) {
    if (version === state.selectionVersion) {
      showToast(error.message, "error");
      elements.streamState.textContent = "加载失败";
      elements.streamState.className = "connection-state";
    }
  }
}

function connectEventStream(sessionId, version) {
  closeEventStream();
  const source = new EventSource(`/api/v1/sessions/${sessionId}/events?after_id=${state.lastEventId}`);
  state.eventSource = source;

  source.onopen = () => {
    if (version !== state.selectionVersion) return;
    elements.streamState.textContent = "SSE 已连接";
    elements.streamState.className = "connection-state connected";
  };
  source.onerror = () => {
    if (version !== state.selectionVersion) return;
    elements.streamState.textContent = "SSE 重连中";
    elements.streamState.className = "connection-state reconnecting";
  };

  for (const eventType of EVENT_TYPES) {
    source.addEventListener(eventType, (message) => handleStreamMessage(message, version));
  }
  source.addEventListener("heartbeat", () => {
    if (version !== state.selectionVersion) return;
    elements.streamState.textContent = "SSE 已连接";
    elements.streamState.className = "connection-state connected";
  });
  source.addEventListener("stream.reset", async () => {
    if (version !== state.selectionVersion) return;
    source.close();
    showToast("事件队列已重置，正在从数据库恢复。", "error");
    await reloadHistory();
    connectEventStream(sessionId, version);
  });
}

async function handleStreamMessage(message, version) {
  if (version !== state.selectionVersion) return;
  try {
    const event = JSON.parse(message.data);
    addEvent(event);
    if (["run.started", "run.completed", "run.failed", "assistant.message"].includes(event.event_type)) {
      await refreshCurrentData();
    }
  } catch (error) {
    showToast(`事件解析失败：${error.message}`, "error");
  }
}

function closeEventStream() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

async function reloadHistory() {
  if (!state.current) return;
  const history = await api(
    `/api/v1/sessions/${state.current.id}/events/history?after_id=${state.lastEventId}&limit=1000`,
  );
  for (const event of history.items) addEvent(event);
}

async function refreshCurrentData() {
  if (!state.current) return;
  const currentId = state.current.id;
  const [session, messages] = await Promise.all([
    api(`/api/v1/sessions/${currentId}`),
    api(`/api/v1/sessions/${currentId}/messages`),
  ]);
  if (state.current?.id !== currentId) return;
  state.current = session;
  state.messages = messages.items;
  const listItem = state.sessions.findIndex((item) => item.id === currentId);
  if (listItem >= 0) state.sessions[listItem] = session;
  renderSessions();
  renderCurrentSession();
  elements.messageList.className = "message-list";
  renderMessages();
}

function clearDesktop(message = "选择处于 READY 或 RUNNING 状态的会话。") {
  elements.vncFrame.src = "about:blank";
  elements.vncFrame.classList.remove("visible");
  elements.desktopPlaceholder.classList.remove("hidden");
  const paragraph = elements.desktopPlaceholder.querySelector("p");
  if (paragraph) paragraph.textContent = message;
  elements.vncExpiry.textContent = "短期令牌未签发";
}

async function loadVnc(version = state.selectionVersion) {
  if (!state.current || !ACTIVE_VNC_STATUSES.has(state.current.status)) return;
  const sessionId = state.current.id;
  elements.reloadVnc.disabled = true;
  try {
    const access = await api(`/api/v1/sessions/${sessionId}/vnc-access`, { method: "POST" });
    if (version !== state.selectionVersion || state.current?.id !== sessionId) return;
    elements.vncFrame.src = access.url;
    elements.vncFrame.classList.add("visible");
    elements.desktopPlaceholder.classList.add("hidden");
    elements.vncExpiry.textContent = `令牌至 ${localTime(access.expires_at, true)}`;
  } catch (error) {
    clearDesktop(error.message);
    showToast(error.message, "error");
  } finally {
    renderCurrentSession();
  }
}

async function createSession(title) {
  setBusy(elements.confirmCreate, true, "正在创建桌面…");
  try {
    const session = await api("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ title, expires_in_seconds: 3600 }),
    });
    elements.createDialog.close();
    elements.createForm.reset();
    await loadSessions();
    await selectSession(session.id);
    showToast(`会话“${session.title || shortId(session.id)}”已就绪。`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(elements.confirmCreate, false);
  }
}

async function submitRun(task) {
  if (!state.current) return;
  setBusy(elements.submitRun, true, "正在提交…");
  try {
    await api(`/api/v1/sessions/${state.current.id}/runs`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ input: task }),
    });
    elements.taskInput.value = "";
    await refreshCurrentData();
  } catch (error) {
    showToast(error.message, "error");
    await refreshCurrentData();
  } finally {
    setBusy(elements.submitRun, false);
    renderCurrentSession();
  }
}

async function stopCurrentSession() {
  if (!state.current) return;
  setBusy(elements.stopSession, true, "正在停止…");
  try {
    state.current = await api(`/api/v1/sessions/${state.current.id}/stop`, { method: "POST" });
    closeEventStream();
    elements.streamState.textContent = "SSE 已断开";
    elements.streamState.className = "connection-state";
    clearDesktop("会话已停止，桌面容器不再运行。");
    await loadSessions();
    renderCurrentSession();
    renderMessages();
    showToast("会话和桌面已停止。");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(elements.stopSession, false);
    renderCurrentSession();
  }
}

async function deleteCurrentSession() {
  if (!state.current) return;
  const session = state.current;
  if (!window.confirm(`确定删除“${session.title || shortId(session.id)}”并销毁桌面容器吗？`)) return;
  setBusy(elements.deleteSession, true, "正在删除…");
  try {
    await api(`/api/v1/sessions/${session.id}`, { method: "DELETE" });
    closeEventStream();
    state.current = null;
    state.messages = [];
    state.events = [];
    state.lastEventId = 0;
    clearDesktop();
    renderCurrentSession();
    renderMessages();
    renderEvents();
    await loadSessions();
    if (state.sessions.length) await selectSession(state.sessions[0].id);
    showToast("会话及其桌面容器已删除。");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(elements.deleteSession, false);
    renderCurrentSession();
  }
}

async function checkHealth() {
  try {
    const health = await api("/health/ready");
    const components = Object.values(health.components || {});
    const healthy = health.status === "正常" && components.every((item) => item.status === "正常");
    elements.healthDot.className = `health-dot ${healthy ? "healthy" : "unhealthy"}`;
    elements.healthLabel.textContent = healthy ? "服务与运行时正常" : "部分依赖不可用";
  } catch {
    elements.healthDot.className = "health-dot unhealthy";
    elements.healthLabel.textContent = "无法连接控制面";
  }
}

function installHandlers() {
  document.querySelector("#open-create").addEventListener("click", () => {
    elements.createDialog.showModal();
    window.setTimeout(() => elements.sessionTitle.focus(), 0);
  });
  document.querySelector("#close-create").addEventListener("click", () => elements.createDialog.close());
  document.querySelector("#cancel-create").addEventListener("click", () => elements.createDialog.close());
  elements.createForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const title = elements.sessionTitle.value.trim();
    if (title) createSession(title);
  });
  elements.runForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const task = elements.taskInput.value.trim();
    if (task) submitRun(task);
  });
  elements.taskInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey) {
      event.preventDefault();
      elements.runForm.requestSubmit();
    }
  });
  elements.refreshSession.addEventListener("click", async () => {
    if (state.current) await selectSession(state.current.id);
  });
  elements.reloadVnc.addEventListener("click", () => loadVnc());
  elements.stopSession.addEventListener("click", stopCurrentSession);
  elements.deleteSession.addEventListener("click", deleteCurrentSession);
  window.addEventListener("beforeunload", closeEventStream);
}

async function start() {
  installHandlers();
  renderCurrentSession();
  await checkHealth();
  try {
    await loadSessions({ preserveSelection: false });
  } catch (error) {
    showToast(error.message, "error");
  }
  window.setInterval(checkHealth, 15000);
}

start();
