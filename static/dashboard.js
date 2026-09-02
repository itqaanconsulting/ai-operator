const state = { entities: [], commitments: [], actions: [], calendarEvents: [], selectedEntity: null };

const elements = {
  entities: document.querySelector("#entities"),
  commitments: document.querySelector("#commitments"),
  actions: document.querySelector("#actions"),
  calendarEvents: document.querySelector("#calendar-events"),
  notification: document.querySelector("#notification"),
  statusTitle: document.querySelector("#status-title"),
  statusContent: document.querySelector("#status-content"),
  statusButton: document.querySelector("#status-button"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed with HTTP ${response.status}`);
  return data;
}

function notify(message, isError = false) {
  elements.notification.textContent = message;
  elements.notification.classList.toggle("error", isError);
  elements.notification.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { elements.notification.hidden = true; }, 5000);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function deadlineState(deadline) {
  if (!deadline) return "No deadline";
  const date = new Date(deadline.length === 10 ? `${deadline}T23:59:59Z` : deadline);
  return date < new Date() ? "overdue" : deadline;
}

function renderEntities() {
  elements.entities.innerHTML = state.entities.length ? state.entities.map(entity => `
    <button class="entity-button ${state.selectedEntity?.id === entity.id ? "active" : ""}"
            data-entity="${escapeHtml(entity.name)}">
      <strong>${escapeHtml(entity.name)}</strong>
      <span>${entity.email_count} emails · ${entity.open_commitment_count} open loops</span>
    </button>`).join("") : '<p class="empty-state">No entities yet.</p>';
  elements.entities.querySelectorAll("[data-entity]").forEach(button => {
    button.addEventListener("click", () => selectEntity(button.dataset.entity));
  });
}

function renderCommitments() {
  const open = state.commitments;
  elements.commitments.innerHTML = open.length ? open.map(item => `
    <article class="list-card">
      <h3>${escapeHtml(item.title)}</h3>
      <div class="meta">
        <span class="pill ${escapeHtml(item.urgency)}">${escapeHtml(item.urgency)}</span>
        <span class="pill ${deadlineState(item.deadline) === "overdue" ? "overdue" : ""}">
          ${escapeHtml(deadlineState(item.deadline))}
        </span>
        ${item.company_or_project ? `<span>${escapeHtml(item.company_or_project)}</span>` : ""}
      </div>
      <div class="card-actions">
        <button class="button secondary" data-complete="${item.id}">Mark complete</button>
      </div>
    </article>`).join("") : '<p class="empty-state">No open commitments.</p>';
  elements.commitments.querySelectorAll("[data-complete]").forEach(button => {
    button.addEventListener("click", () => completeCommitment(button.dataset.complete));
  });
}

function renderActions() {
  const visible = state.actions.filter(action => ["pending_approval", "approved"].includes(action.status));
  elements.actions.innerHTML = visible.length ? visible.map(action => `
    <article class="list-card">
      <h3>${escapeHtml(action.description)}</h3>
      <div class="meta">
        <span class="pill ${escapeHtml(action.status)}">${escapeHtml(action.status.replaceAll("_", " "))}</span>
        <span>${escapeHtml(action.action_type.replaceAll("_", " "))}</span>
      </div>
      <div class="card-actions">
        ${action.status === "pending_approval" ? `
          <button class="button approve" data-approve="${action.id}">Approve</button>
          <button class="button reject" data-reject="${action.id}">Reject</button>` : ""}
        ${action.status === "approved" && action.action_type === "draft_reply" ? `
          <button class="button execute" data-execute="${action.id}">Create Gmail draft</button>` : ""}
      </div>
    </article>`).join("") : '<p class="empty-state">No actions need attention.</p>';
  elements.actions.querySelectorAll("[data-approve]").forEach(button => button.addEventListener("click", () => decideAction(button.dataset.approve, "approve")));
  elements.actions.querySelectorAll("[data-reject]").forEach(button => button.addEventListener("click", () => decideAction(button.dataset.reject, "reject")));
  elements.actions.querySelectorAll("[data-execute]").forEach(button => button.addEventListener("click", () => executeAction(button.dataset.execute)));
}

function renderCalendarEvents() {
  elements.calendarEvents.innerHTML = state.calendarEvents.length ? state.calendarEvents.map(event => `
    <article class="list-card">
      <h3>${escapeHtml(event.title)}</h3>
      <div class="meta">
        <span class="pill">${event.all_day ? "all day" : "meeting"}</span>
        <span>${escapeHtml(event.start_at || "No start time")}</span>
        <span>${escapeHtml(event.entity_names || "Unmatched")}</span>
      </div>
    </article>`).join("") : '<p class="empty-state">No Calendar events imported yet.</p>';
}

function updateMetrics() {
  document.querySelector("#entity-count").textContent = state.entities.length;
  document.querySelector("#commitment-count").textContent = state.commitments.length;
  document.querySelector("#approval-count").textContent = state.actions.filter(a => a.status === "pending_approval").length;
  document.querySelector("#overdue-count").textContent = state.commitments.filter(c => deadlineState(c.deadline) === "overdue").length;
}

async function refresh() {
  document.body.classList.add("loading");
  try {
    const [entities, commitments, actions, calendar] = await Promise.all([
      api("/entities"), api("/commitments?status=open"), api("/actions"), api("/calendar/events"),
    ]);
    state.entities = entities.entities;
    state.commitments = commitments.commitments;
    state.actions = actions.actions;
    state.calendarEvents = calendar.events;
    if (state.selectedEntity) state.selectedEntity = state.entities.find(e => e.id === state.selectedEntity.id) || null;
    renderEntities(); renderCommitments(); renderActions(); renderCalendarEvents(); updateMetrics();
  } catch (error) { notify(error.message, true); }
  finally { document.body.classList.remove("loading"); }
}

function selectEntity(name) {
  state.selectedEntity = state.entities.find(entity => entity.name === name);
  elements.statusTitle.textContent = state.selectedEntity.name;
  elements.statusButton.disabled = false;
  elements.statusContent.className = "empty-state";
  elements.statusContent.textContent = "Generate a grounded brief from linked emails, commitments, actions, and decisions.";
  renderEntities();
}

function listBlock(title, items, highlight = false) {
  const content = items?.length ? `<ul>${items.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "<p>None recorded.</p>";
  return `<section class="status-block ${highlight ? "highlight" : ""}"><h3>${escapeHtml(title)}</h3>${content}</section>`;
}

async function generateStatus() {
  if (!state.selectedEntity) return;
  elements.statusButton.disabled = true;
  elements.statusContent.className = "empty-state";
  elements.statusContent.textContent = "Generating grounded status brief…";
  try {
    const brief = await api(`/entities/${encodeURIComponent(state.selectedEntity.name)}/status`);
    elements.statusContent.className = "status-content status-grid";
    elements.statusContent.innerHTML = `
      ${listBlock("Current status", [brief.current_status], true)}
      ${listBlock("Recommended next action", [brief.recommended_next_action], true)}
      ${listBlock("Recent activity", brief.recent_activity)}
      ${listBlock("Upcoming meetings", brief.upcoming_meetings)}
      ${listBlock("Open commitments", brief.open_commitments)}
      ${listBlock("Pending actions", brief.pending_actions)}
      ${listBlock("Decisions", brief.decisions)}
      ${listBlock("Blockers", brief.blockers)}
      ${listBlock("Missing information", brief.missing_information)}`;
  } catch (error) { elements.statusContent.textContent = error.message; notify(error.message, true); }
  finally { elements.statusButton.disabled = false; }
}

async function runMonitor() {
  try {
    const result = await api("/monitor/open-loops", { method: "POST", body: JSON.stringify({ due_within_days: 3 }) });
    notify(`Monitor checked ${result.checked} commitments and created ${result.created.length} reminders.`);
    await refresh();
  } catch (error) { notify(error.message, true); }
}

async function decideAction(id, decision) {
  const note = window.prompt(`Optional note for ${decision}:`, "") ?? null;
  if (note === null) return;
  try {
    await api(`/actions/${id}/${decision}`, { method: "POST", body: JSON.stringify({ note }) });
    notify(`Action ${decision === "approve" ? "approved" : "rejected"}.`); await refresh();
  } catch (error) { notify(error.message, true); }
}

async function executeAction(id) {
  if (!window.confirm("Create a Gmail draft? The message will not be sent.")) return;
  try { await api(`/actions/${id}/execute`, { method: "POST" }); notify("Gmail draft created. Nothing was sent."); await refresh(); }
  catch (error) { notify(error.message, true); }
}

async function completeCommitment(id) {
  const note = window.prompt("Completion note:", "") ?? null;
  if (note === null) return;
  try {
    await api(`/commitments/${id}/complete`, { method: "POST", body: JSON.stringify({ note }) });
    notify("Commitment completed."); await refresh();
  } catch (error) { notify(error.message, true); }
}

document.querySelector("#refresh-button").addEventListener("click", refresh);
document.querySelector("#monitor-button").addEventListener("click", runMonitor);
elements.statusButton.addEventListener("click", generateStatus);
refresh();
