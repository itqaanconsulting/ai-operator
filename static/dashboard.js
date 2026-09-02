const state = {
  entities: [], commitments: [], actions: [], calendarEvents: [], selectedEntity: null,
  documents: [], trustedReferences: [], comparisons: [], revisionDrafts: [],
  contractSchedule: null, automationRuns: [], reviewQueue: [],
};

const elements = {
  entities: document.querySelector("#entities"),
  commitments: document.querySelector("#commitments"),
  actions: document.querySelector("#actions"),
  calendarEvents: document.querySelector("#calendar-events"),
  notification: document.querySelector("#notification"),
  statusTitle: document.querySelector("#status-title"),
  statusContent: document.querySelector("#status-content"),
  statusButton: document.querySelector("#status-button"),
  documents: document.querySelector("#documents"),
  trustedReferences: document.querySelector("#trusted-references"),
  comparisons: document.querySelector("#comparisons"),
  revisionDrafts: document.querySelector("#revision-drafts"),
  automationRuns: document.querySelector("#automation-runs"),
  reviewQueue: document.querySelector("#review-queue"),
};

async function api(path, options = {}) {
  const isForm = options.body instanceof FormData;
  const response = await fetch(path, {
    headers: { ...(isForm ? {} : { "Content-Type": "application/json" }), ...(options.headers || {}) },
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
  document.querySelector("#document-count").textContent = state.documents.length;
}

function parseJson(value, fallback = {}) {
  try { return JSON.parse(value || ""); } catch { return fallback; }
}

function renderDocuments() {
  const trustedIds = new Set(state.trustedReferences.map(item => item.document_id));
  elements.documents.innerHTML = state.documents.length ? state.documents.map(item => `
    <article class="list-card document-card">
      <div class="card-title-row"><h3>${escapeHtml(item.filename)}</h3><span class="pill">${escapeHtml(item.document_type)}</span></div>
      <p>${escapeHtml(item.summary)}</p>
      <div class="meta"><span>${escapeHtml(item.entity_names || "Unmatched")}</span><span>Document #${item.id}</span></div>
      <div class="card-actions">
        ${trustedIds.has(item.id) ? '<span class="pill approved">Trusted reference</span>' : `<button class="button secondary" data-trust="${item.id}">Mark trusted</button>`}
        <button class="button execute" data-auto-compare="${item.id}">Compare with trusted reference</button>
      </div>
    </article>`).join("") : '<p class="empty-state">No documents imported yet.</p>';
  elements.documents.querySelectorAll("[data-trust]").forEach(button => button.addEventListener("click", () => markTrusted(button.dataset.trust)));
  elements.documents.querySelectorAll("[data-auto-compare]").forEach(button => button.addEventListener("click", () => compareTrusted(button.dataset.autoCompare)));
}

function renderTrustedReferences() {
  elements.trustedReferences.innerHTML = state.trustedReferences.length ? state.trustedReferences.map(item => `
    <article class="list-card">
      <h3>${escapeHtml(item.label)}</h3>
      <p>${escapeHtml(item.filename)}</p>
      <div class="meta"><span>${escapeHtml(item.entity_name || "Global")}</span><span>${escapeHtml(item.document_type)}</span></div>
      <p class="supporting-copy">${escapeHtml(item.note)}</p>
    </article>`).join("") : '<p class="empty-state">No trusted references. Human review is required before adding one.</p>';
}

function differenceList(comparison) {
  if (!comparison.material_differences?.length) return '<p class="supporting-copy">No material differences found.</p>';
  return comparison.material_differences.map(change => `
    <div class="difference-row">
      <span class="risk ${escapeHtml(change.significance)}">${escapeHtml(change.significance)}</span>
      <div><strong>${escapeHtml(change.topic)}</strong><p>${escapeHtml(change.impact)}</p><small>${escapeHtml(change.suggested_resolution)}</small>
        <div class="evidence-grid">
          ${evidenceBlock("Candidate", change.candidate_evidence)}
          ${evidenceBlock("Reference", change.reference_evidence)}
        </div>
      </div>
    </div>`).join("");
}

function evidenceBlock(label, evidence) {
  if (!evidence) return `<div class="evidence missing"><strong>${label}</strong><span>No source evidence returned</span></div>`;
  return `<div class="evidence ${evidence.verified ? "verified" : "unverified"}">
    <strong>${label} · ${escapeHtml(evidence.location)}</strong>
    <q>${escapeHtml(evidence.excerpt)}</q>
    <span>${evidence.verified ? "Verified against extracted source" : "Not verified — inspect source"}</span>
  </div>`;
}

function renderComparisons() {
  elements.comparisons.innerHTML = state.comparisons.length ? state.comparisons.map(item => {
    const comparison = parseJson(item.comparison_json);
    return `<article class="comparison-card">
      <div class="comparison-header">
        <div><h3>${escapeHtml(item.candidate_filename)}</h3><p>vs ${escapeHtml(item.reference_filename)}</p></div>
        <div class="recommendation"><span class="pill ${escapeHtml(comparison.recommendation)}">AI: ${escapeHtml(comparison.recommendation || "review")}</span><span class="pill ${escapeHtml(item.review_status)}">${escapeHtml(item.review_status.replaceAll("_", " "))}</span></div>
      </div>
      <p class="comparison-summary">${escapeHtml(comparison.executive_summary || item.executive_summary)}</p>
      <div class="differences">${differenceList(comparison)}</div>
      <div class="card-actions">
        ${item.review_status === "pending_review" ? `
          <button class="button approve" data-review="approved" data-comparison="${item.id}">Approve</button>
          <button class="button secondary" data-review="revision_requested" data-comparison="${item.id}">Request revision</button>
          <button class="button reject" data-review="rejected" data-comparison="${item.id}">Reject</button>` : ""}
        ${item.review_status === "revision_requested" ? `<button class="button execute" data-revision-draft="${item.id}">Prepare revision draft</button>` : ""}
      </div>
    </article>`;
  }).join("") : '<p class="empty-state">No comparisons yet.</p>';
  elements.comparisons.querySelectorAll("[data-review]").forEach(button => button.addEventListener("click", () => reviewComparison(button.dataset.comparison, button.dataset.review)));
  elements.comparisons.querySelectorAll("[data-revision-draft]").forEach(button => button.addEventListener("click", () => createRevisionDraft(button.dataset.revisionDraft)));
}

function renderRevisionDrafts() {
  elements.revisionDrafts.innerHTML = state.revisionDrafts.length ? state.revisionDrafts.map(item => `
    <article class="list-card">
      <div class="card-title-row"><h3>${escapeHtml(item.subject)}</h3><span class="pill ${escapeHtml(item.delivery_status || "pending_approval")}">${escapeHtml(item.delivery_status || "not approved")}</span></div>
      <p class="draft-body">${escapeHtml(item.body)}</p>
      <div class="meta"><span>${escapeHtml(item.candidate_filename)}</span>${item.recipient ? `<span>To: ${escapeHtml(item.recipient)}</span>` : ""}</div>
      <div class="card-actions">
        ${!item.delivery_id ? `<button class="button approve" data-approve-draft="${item.id}">Approve recipient</button>` : ""}
        ${item.delivery_status === "approved" ? `<button class="button execute" data-execute-delivery="${item.delivery_id}">Create Gmail draft</button>` : ""}
        ${item.delivery_status === "executed" ? '<span class="pill approved">Gmail draft created · not sent</span>' : ""}
      </div>
    </article>`).join("") : '<p class="empty-state">No revision request drafts yet.</p>';
  elements.revisionDrafts.querySelectorAll("[data-approve-draft]").forEach(button => button.addEventListener("click", () => approveRevisionDraft(button.dataset.approveDraft)));
  elements.revisionDrafts.querySelectorAll("[data-execute-delivery]").forEach(button => button.addEventListener("click", () => executeRevisionDelivery(button.dataset.executeDelivery)));
}

async function refresh() {
  document.body.classList.add("loading");
  try {
    const [entities, commitments, actions, calendar, documents, references, comparisons, drafts, schedule, runs, reviewQueue] = await Promise.all([
      api("/entities"), api("/commitments?status=open"), api("/actions"), api("/calendar/events"),
      api("/documents"), api("/documents/trusted-references"), api("/documents/comparisons"), api("/documents/revision-drafts"),
      api("/automation/contract-intake/schedule"),
      api("/automation/runs"),
      api("/automation/review-queue"),
    ]);
    state.entities = entities.entities;
    state.commitments = commitments.commitments;
    state.actions = actions.actions;
    state.calendarEvents = calendar.events;
    state.documents = documents.documents;
    state.trustedReferences = references.trusted_references;
    state.comparisons = comparisons.comparisons;
    state.revisionDrafts = drafts.drafts;
    state.contractSchedule = schedule;
    state.automationRuns = runs.runs;
    state.reviewQueue = reviewQueue.items;
    if (state.selectedEntity) state.selectedEntity = state.entities.find(e => e.id === state.selectedEntity.id) || null;
    renderEntities(); renderCommitments(); renderActions(); renderCalendarEvents();
    renderDocuments(); renderTrustedReferences(); renderComparisons(); renderRevisionDrafts(); updateMetrics();
    renderSchedule();
    renderAutomationRuns();
    renderReviewQueue();
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

async function uploadDocument(event) {
  event.preventDefault();
  const input = document.querySelector("#document-file");
  if (!input.files[0]) return;
  const body = new FormData(); body.append("file", input.files[0]);
  try { await api("/documents/analyze", { method: "POST", body }); notify("Document analyzed and stored."); event.target.reset(); await refresh(); }
  catch (error) { notify(error.message, true); }
}

async function importGmailAttachments() {
  try {
    const result = await api("/automation/contract-intake", { method: "POST", body: JSON.stringify({ label: "AI-Operator", max_messages: 10 }) });
    notify(`Automation #${result.run_id}: ${result.review_ready.length} ready for review, ${result.analyzed_only.length} need a reference, ${result.errors.length} errors.`, result.errors.length > 0);
    await refresh();
  } catch (error) { notify(error.message, true); }
}

function renderSchedule() {
  if (!state.contractSchedule) return;
  const enabled = Boolean(state.contractSchedule.enabled);
  const last = state.contractSchedule.last_status
    ? ` Last run: ${state.contractSchedule.last_status}${state.contractSchedule.last_finished_at ? ` at ${state.contractSchedule.last_finished_at}` : ""}.`
    : " No scheduled run yet.";
  document.querySelector("#schedule-status").textContent = enabled
    ? `Enabled every ${state.contractSchedule.interval_minutes} minutes for label “${state.contractSchedule.label}”.${last}`
    : `Disabled.${last}`;
  const button = document.querySelector("#schedule-toggle-button");
  document.querySelector("#schedule-interval").value = state.contractSchedule.interval_minutes || 15;
  document.querySelector("#schedule-interval").disabled = enabled;
  button.textContent = enabled ? "Disable schedule" : "Enable schedule";
  button.className = `button ${enabled ? "reject" : "approve"}`;
}

function renderAutomationRuns() {
  elements.automationRuns.innerHTML = state.automationRuns.length ? state.automationRuns.slice(0, 8).map(run => {
    const result = parseJson(run.result_json);
    return `<article class="run-row">
      <div><strong>Run #${run.id}</strong><span>${escapeHtml(result.trigger || "unknown trigger")}</span></div>
      <span class="pill ${escapeHtml(run.status)}">${escapeHtml(run.status)}</span>
      <span>${result.review_ready?.length || 0} review-ready</span>
      <span>${result.analyzed_only?.length || 0} awaiting reference</span>
      <time>${escapeHtml(run.finished_at || run.started_at)}</time>
    </article>`;
  }).join("") : '<p class="empty-state">No automation runs yet.</p>';
}

function renderReviewQueue() {
  elements.reviewQueue.innerHTML = state.reviewQueue.length ? state.reviewQueue.map(item => `
    <article class="review-queue-row">
      <span class="priority ${escapeHtml(item.priority)}">${escapeHtml(item.priority)}</span>
      <div><strong>${escapeHtml(item.candidate_filename)}</strong><p>${escapeHtml(item.entity_names || "Unmatched entity")} · AI recommends ${escapeHtml(item.recommendation)}</p></div>
      <ul>${item.priority_reasons.map(reason => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>
      <button class="button secondary" data-jump-comparison="${item.comparison_id}">Review comparison</button>
    </article>`).join("") : '<p class="empty-state">Nothing is waiting for human review.</p>';
  elements.reviewQueue.querySelectorAll("[data-jump-comparison]").forEach(button => button.addEventListener("click", () => {
    document.querySelector(`[data-comparison="${button.dataset.jumpComparison}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }));
}

async function toggleSchedule() {
  const current = state.contractSchedule;
  if (!current) return;
  let interval = current.interval_minutes || 15;
  if (!current.enabled) {
    interval = Number(document.querySelector("#schedule-interval").value);
    if (!Number.isInteger(interval) || interval < 1 || interval > 1440) {
      notify("Enter a whole number between 1 and 1440 minutes.", true); return;
    }
  }
  try {
    await api("/automation/contract-intake/schedule", {
      method: "PUT",
      body: JSON.stringify({ enabled: !Boolean(current.enabled), interval_minutes: interval, label: "AI-Operator", max_messages: 10 }),
    });
    notify(current.enabled ? "Scheduled intake disabled." : "Scheduled intake enabled. Human review remains required.");
    await refresh();
  } catch (error) { notify(error.message, true); }
}

async function markTrusted(id) {
  const label = window.prompt("Reference label:", "Approved reference")?.trim(); if (!label) return;
  const note = window.prompt("Why is this document trusted?", "Manually reviewed and approved as baseline.")?.trim(); if (!note) return;
  try { await api(`/documents/${id}/trusted-reference`, { method: "POST", body: JSON.stringify({ label, note }) }); notify("Trusted reference added by human decision."); await refresh(); }
  catch (error) { notify(error.message, true); }
}

async function compareTrusted(id) {
  try { await api(`/documents/${id}/compare-with-trusted-reference`, { method: "POST" }); notify("Comparison completed with the selected trusted reference."); await refresh(); }
  catch (error) { notify(error.message, true); }
}

async function reviewComparison(id, decision) {
  const note = window.prompt(`Required reason for ${decision.replaceAll("_", " ")}:`, "")?.trim(); if (!note) return;
  try { await api(`/documents/comparisons/${id}/decision`, { method: "POST", body: JSON.stringify({ decision, note }) }); notify("Human review decision recorded."); await refresh(); }
  catch (error) { notify(error.message, true); }
}

async function createRevisionDraft(id) {
  try { await api(`/documents/comparisons/${id}/revision-draft`, { method: "POST" }); notify("Revision request draft prepared. Nothing was sent."); await refresh(); }
  catch (error) { notify(error.message, true); }
}

async function approveRevisionDraft(id) {
  const recipient = window.prompt("Recipient email address:", "")?.trim(); if (!recipient) return;
  const note = window.prompt("Approval note:", "Recipient and wording manually verified.")?.trim(); if (!note) return;
  try { await api(`/documents/revision-drafts/${id}/approve-gmail-draft`, { method: "POST", body: JSON.stringify({ recipient, note }) }); notify("Recipient approved. Gmail has not been called yet."); await refresh(); }
  catch (error) { notify(error.message, true); }
}

async function executeRevisionDelivery(id) {
  if (!window.confirm("Create the approved Gmail draft? The email will not be sent.")) return;
  try { await api(`/documents/revision-draft-deliveries/${id}/execute`, { method: "POST" }); notify("Gmail draft created. Nothing was sent."); await refresh(); }
  catch (error) { notify(error.message, true); }
}

function switchView(view) {
  document.querySelectorAll(".app-view").forEach(section => { section.hidden = !section.id.startsWith(view); });
  document.querySelectorAll(".view-tab").forEach(button => button.classList.toggle("active", button.dataset.view === view));
  document.querySelector(".metrics").hidden = view !== "operations";
  document.querySelector("#monitor-button").hidden = view !== "operations";
}

document.querySelector("#refresh-button").addEventListener("click", refresh);
document.querySelector("#monitor-button").addEventListener("click", runMonitor);
elements.statusButton.addEventListener("click", generateStatus);
document.querySelector("#document-upload-form").addEventListener("submit", uploadDocument);
document.querySelector("#gmail-attachments-button").addEventListener("click", importGmailAttachments);
document.querySelector("#schedule-toggle-button").addEventListener("click", toggleSchedule);
document.querySelectorAll(".view-tab").forEach(button => button.addEventListener("click", () => switchView(button.dataset.view)));
switchView("documents");
refresh();
