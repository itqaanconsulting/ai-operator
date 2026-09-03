const state = {
  entities: [], commitments: [], actions: [], calendarEvents: [], selectedEntity: null,
  documents: [], trustedReferences: [], comparisons: [], revisionDrafts: [],
  contractSchedule: null, inboxSchedule: null, automationRuns: [], reviewQueue: [], workQueue: [],
};

const elements = {
  entities: document.querySelector("#entities"),
  commitments: document.querySelector("#commitments"),
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
  briefingContent: document.querySelector("#briefing-content"),
  briefingButton: document.querySelector("#briefing-button"),
  operatorAnswer: document.querySelector("#operator-answer"),
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
  elements.commitments.innerHTML = state.workQueue.length ? state.workQueue.map(group => `
    <section class="work-group">
      <header class="work-group-header"><strong>${escapeHtml(group.email.subject)}</strong><span>${group.commitments.length} item${group.commitments.length === 1 ? "" : "s"}</span></header>
      ${group.commitments.map(item => {
        const action = group.actions.find(candidate => candidate.commitment_id === item.id && candidate.action_type !== "open_loop_review")
          || group.actions.find(candidate => candidate.commitment_id === item.id);
        const payload = action ? parseJson(action.payload_json) : {};
        const event = payload.calendar_event || {};
        const decision = payload.decision_record || {};
        const followUp = payload.follow_up || {};
        const proposalReady = action?.action_type === "record_decision" ? Boolean(decision.title && decision.decision)
          : action?.action_type === "schedule_follow_up" ? Boolean(followUp.follow_up_at && followUp.subject && followUp.body)
          : true;
        return `<article class="work-item">
          <h3>${escapeHtml(item.title)}</h3>
          <div class="meta"><span class="pill ${escapeHtml(item.urgency)}">${escapeHtml(item.urgency)}</span><span class="pill ${deadlineState(item.deadline) === "overdue" ? "overdue" : ""}">${escapeHtml(deadlineState(item.deadline))}</span>${payload.work_item_kind ? `<span class="pill">${escapeHtml(payload.work_item_kind.replaceAll("_", " "))}</span>` : payload.scenario ? `<span class="pill">${escapeHtml(payload.scenario.replaceAll("_", " "))}</span>` : ""}</div>
          ${action ? `<div class="proposed-action"><span>Proposed action</span><p>${escapeHtml(action.description)}</p></div>` : ""}
          ${action?.action_type === "draft_reply" && payload.suggested_reply ? `<details class="draft-editor"><summary>Preview or edit reply</summary><div class="draft-editor-body"><input data-draft-subject="${action.id}" value="${escapeHtml(payload.draft_subject || `Re: ${group.email.subject}`)}" aria-label="Draft subject"><textarea data-draft-body="${action.id}" aria-label="Draft body">${escapeHtml(payload.suggested_reply)}</textarea><button class="button secondary" data-save-draft="${action.id}">Save changes</button></div></details>` : ""}
          ${action?.action_type === "calendar_event" ? `<details class="draft-editor"><summary>Preview or edit Calendar proposal</summary><div class="draft-editor-body calendar-editor-grid"><input class="wide" data-event-title="${action.id}" value="${escapeHtml(event.title || item.title)}" placeholder="Title"><input data-event-start="${action.id}" value="${escapeHtml(event.start_at || "")}" placeholder="Start ISO date/time"><input data-event-end="${action.id}" value="${escapeHtml(event.end_at || "")}" placeholder="End ISO date/time"><input class="wide" data-event-location="${action.id}" value="${escapeHtml(event.location || "")}" placeholder="Location (optional)"><input class="wide" data-event-attendees="${action.id}" value="${escapeHtml((event.attendees || []).join(", "))}" placeholder="Attendee emails, comma separated"><button class="button secondary wide" data-save-event="${action.id}">Save proposal</button></div></details>` : ""}
          ${action?.action_type === "record_decision" ? `<details class="draft-editor" open><summary>Decision record · ${escapeHtml(group.email.entity_name || "no company or project linked")}</summary><div class="draft-editor-body"><input data-decision-title="${action.id}" value="${escapeHtml(decision.title || item.title)}" aria-label="Decision title"><textarea data-decision-outcome="${action.id}" aria-label="Decision outcome" placeholder="Enter the final decision before approval">${escapeHtml(decision.decision || "")}</textarea><textarea data-decision-rationale="${action.id}" aria-label="Decision rationale" placeholder="Rationale (optional)">${escapeHtml(decision.rationale || "")}</textarea><button class="button secondary" data-save-decision="${action.id}">Save decision proposal</button></div></details>` : ""}
          ${action?.action_type === "schedule_follow_up" ? `<details class="draft-editor" open><summary>Scheduled follow-up</summary><div class="draft-editor-body"><input data-follow-up-at="${action.id}" value="${escapeHtml(followUp.follow_up_at || item.deadline || "")}" aria-label="Follow-up time" placeholder="2026-09-10T09:00:00+02:00"><input data-follow-up-subject="${action.id}" value="${escapeHtml(followUp.subject || `Re: ${group.email.subject}`)}" aria-label="Follow-up subject"><textarea data-follow-up-body="${action.id}" aria-label="Follow-up draft">${escapeHtml(followUp.body || "")}</textarea><button class="button secondary" data-save-follow-up="${action.id}">Save follow-up</button></div></details>` : ""}
          <div class="card-actions">
            ${action?.status === "pending_approval" && proposalReady ? `<button class="button approve" data-approve="${action.id}">Approve</button>` : ""}
            ${action?.status === "pending_approval" && !proposalReady ? '<span class="pill">Complete proposal first</span>' : ""}
            ${action?.status === "pending_approval" ? `<button class="button reject" data-reject="${action.id}">Reject</button>` : ""}
            ${action?.status === "approved" && action.action_type === "draft_reply" ? `<button class="button execute" data-execute="${action.id}">Create Gmail draft</button>` : ""}
            ${action?.status === "approved" && action.action_type === "calendar_event" ? `<button class="button execute" data-execute="${action.id}">Create Calendar event</button>` : ""}
            ${action?.status === "approved" && action.action_type === "record_decision" ? `<button class="button execute" data-execute="${action.id}">Record decision</button>` : ""}
            ${action?.status === "approved" && action.action_type === "schedule_follow_up" ? `<button class="button execute" data-execute="${action.id}">Activate follow-up</button>` : ""}
            ${action?.status === "approved" && !["draft_reply", "calendar_event", "record_decision", "schedule_follow_up"].includes(action.action_type) ? '<span class="pill approved">Approved · manual action</span>' : ""}
            <button class="button secondary" data-complete="${item.id}">Mark complete</button>
          </div>
        </article>`;
      }).join("")}
    </section>`).join("") : '<p class="empty-state">No work needs attention.</p>';
  elements.commitments.querySelectorAll("[data-complete]").forEach(button => {
    button.addEventListener("click", () => completeCommitment(button.dataset.complete));
  });
  elements.commitments.querySelectorAll("[data-approve]").forEach(button => button.addEventListener("click", () => decideAction(button.dataset.approve, "approve")));
  elements.commitments.querySelectorAll("[data-reject]").forEach(button => button.addEventListener("click", () => decideAction(button.dataset.reject, "reject")));
  elements.commitments.querySelectorAll("[data-execute]").forEach(button => button.addEventListener("click", () => executeAction(button.dataset.execute)));
  elements.commitments.querySelectorAll("[data-save-draft]").forEach(button => button.addEventListener("click", () => saveActionDraft(button.dataset.saveDraft)));
  elements.commitments.querySelectorAll("[data-save-event]").forEach(button => button.addEventListener("click", () => saveCalendarProposal(button.dataset.saveEvent)));
  elements.commitments.querySelectorAll("[data-save-decision]").forEach(button => button.addEventListener("click", () => saveDecisionProposal(button.dataset.saveDecision)));
  elements.commitments.querySelectorAll("[data-save-follow-up]").forEach(button => button.addEventListener("click", () => saveFollowUpProposal(button.dataset.saveFollowUp)));
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
    const [entities, commitments, actions, calendar, documents, references, comparisons, drafts, schedule, inboxSchedule, runs, reviewQueue, workQueue] = await Promise.all([
      api("/entities"), api("/commitments?status=open"), api("/actions"), api("/calendar/events"),
      api("/documents"), api("/documents/trusted-references"), api("/documents/comparisons"), api("/documents/revision-drafts"),
      api("/automation/contract-intake/schedule"),
      api("/automation/inbox/schedule"),
      api("/automation/runs"),
      api("/automation/review-queue"),
      api("/automation/work-queue"),
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
    state.inboxSchedule = inboxSchedule;
    state.automationRuns = runs.runs;
    state.reviewQueue = reviewQueue.items;
    state.workQueue = workQueue.groups;
    if (state.selectedEntity) state.selectedEntity = state.entities.find(e => e.id === state.selectedEntity.id) || null;
    renderEntities(); renderCommitments(); renderCalendarEvents();
    renderDocuments(); renderTrustedReferences(); renderComparisons(); renderRevisionDrafts(); updateMetrics();
    renderSchedule();
    renderInboxSchedule();
    renderAutomationRuns();
    renderLatestInboxRun();
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

async function generateExecutiveBriefing() {
  elements.briefingButton.disabled = true;
  elements.briefingContent.className = "empty-state";
  elements.briefingContent.textContent = "Generating a grounded cross-system briefing…";
  try {
    const brief = await api("/automation/executive-briefing", { method: "POST" });
    elements.briefingContent.className = "briefing-content";
    elements.briefingContent.innerHTML = `
      <div class="briefing-lead"><h3>${escapeHtml(brief.headline)}</h3><p>${escapeHtml(brief.executive_summary)}</p></div>
      <div class="status-grid">
        ${listBlock("Top priorities", brief.top_priorities, true)}
        ${listBlock("Recommended next actions", brief.recommended_next_actions, true)}
        ${listBlock("Urgent risks", brief.urgent_risks)}
        ${listBlock("Upcoming meetings", brief.upcoming_meetings)}
        ${listBlock("Automation health", brief.automation_health)}
        ${listBlock("Missing information", brief.missing_information)}
      </div>`;
  } catch (error) { elements.briefingContent.textContent = error.message; notify(error.message, true); }
  finally { elements.briefingButton.disabled = false; }
}

async function askOperator(event) {
  event.preventDefault();
  const input = document.querySelector("#operator-question");
  const question = input.value.trim(); if (!question) return;
  elements.operatorAnswer.hidden = false;
  elements.operatorAnswer.className = "operator-answer loading-answer";
  elements.operatorAnswer.textContent = "Retrieving grounded records and preparing an answer…";
  try {
    const result = await api("/operator/ask", { method: "POST", body: JSON.stringify({ question }) });
    elements.operatorAnswer.className = "operator-answer";
    elements.operatorAnswer.innerHTML = `
      <div class="answer-main"><strong>Answer</strong><p>${escapeHtml(result.answer)}</p></div>
      <div class="answer-details">
        ${listBlock("Recommended next actions", result.recommended_next_actions, true)}
        ${listBlock("Missing information", result.missing_information)}
        <section class="status-block"><h3>Evidence</h3><p>${result.evidence_keys.length ? result.evidence_keys.map(escapeHtml).join(" · ") : "No supporting records found."}</p></section>
        <section class="status-block"><h3>Matched entities</h3><p>${result.matched_entities.length ? result.matched_entities.map(escapeHtml).join(", ") : "Global context"}</p></section>
      </div>`;
  } catch (error) { elements.operatorAnswer.className = "operator-answer error"; elements.operatorAnswer.textContent = error.message; }
}

async function createOperatorPlan() {
  const input = document.querySelector("#operator-question");
  const question = input.value.trim(); if (!question) { input.focus(); return; }
  elements.operatorAnswer.hidden = false;
  elements.operatorAnswer.className = "operator-answer loading-answer";
  elements.operatorAnswer.textContent = "Building a grounded, approval-gated plan…";
  try {
    const result = await api("/operator/plans", { method: "POST", body: JSON.stringify({ question }) });
    renderOperatorPlan(result);
  } catch (error) { elements.operatorAnswer.className = "operator-answer error"; elements.operatorAnswer.textContent = error.message; }
}

function renderOperatorPlan(result) {
  const plan = result.plan;
  elements.operatorAnswer.className = "operator-answer";
  elements.operatorAnswer.innerHTML = `
    <div class="answer-main"><strong>Proposed plan</strong><p>${escapeHtml(plan.summary)}</p>
      <div class="card-actions">
        ${result.status === "pending_approval" ? `<button class="button approve" data-plan-decision="approve">Approve plan</button><button class="button reject" data-plan-decision="reject">Reject</button>` : `<span class="pill ${escapeHtml(result.status)}">${escapeHtml(result.status)}</span>`}
      </div>
    </div>
    <div class="answer-details">
      <section class="status-block plan-steps"><h3>Steps</h3><ol>${plan.steps.map(step => `<li><strong>${step.order}. ${escapeHtml(step.action)}</strong><span>${escapeHtml(step.system)} · ${escapeHtml(step.action_type.replaceAll("_", " "))}${step.requires_approval ? " · approval required" : ""}</span></li>`).join("")}</ol></section>
      ${listBlock("Risks", plan.risks)}
      ${listBlock("Missing information", plan.missing_information)}
    </div>`;
  elements.operatorAnswer.querySelectorAll("[data-plan-decision]").forEach(button => button.addEventListener("click", () => decideOperatorPlan(result.plan_id, button.dataset.planDecision, result)));
}

async function decideOperatorPlan(planId, decision, result) {
  try {
    await api(`/operator/plans/${planId}/${decision}`, { method: "POST", body: JSON.stringify({ note: "Decision recorded in dashboard" }) });
    result.status = decision === "approve" ? "approved" : "rejected";
    renderOperatorPlan(result);
    notify(`Plan ${result.status}. No external action was taken.`);
  } catch (error) { notify(error.message, true); }
}

async function runMonitor() {
  try {
    const result = await api("/monitor/open-loops", { method: "POST", body: JSON.stringify({ due_within_days: 3 }) });
    notify(`Monitor checked ${result.checked} commitments and created ${result.created.length} reminders.`);
    await refresh();
  } catch (error) { notify(error.message, true); }
}

async function decideAction(id, decision) {
  try {
    await api(`/actions/${id}/${decision}`, { method: "POST", body: JSON.stringify({ note: `Decision recorded in dashboard: ${decision}` }) });
    notify(`Action ${decision === "approve" ? "approved" : "rejected"}.`); await refresh();
  } catch (error) { notify(error.message, true); }
}

async function executeAction(id) {
  try { await api(`/actions/${id}/execute`, { method: "POST" }); notify("Approved action completed. No email was sent automatically."); await refresh(); }
  catch (error) { notify(error.message, true); }
}

async function saveCalendarProposal(id) {
  const value = name => elements.commitments.querySelector(`[data-event-${name}="${id}"]`).value.trim();
  const attendees = value("attendees").split(",").map(item => item.trim()).filter(Boolean);
  const proposal = { title: value("title"), start_at: value("start"), end_at: value("end"), location: value("location") || null, attendees };
  try {
    await api(`/actions/${id}/calendar-proposal`, { method: "PUT", body: JSON.stringify(proposal) });
    notify("Calendar proposal saved. No event was created."); await refresh();
  } catch (error) { notify(error.message, true); }
}

async function saveActionDraft(id) {
  const subject = elements.commitments.querySelector(`[data-draft-subject="${id}"]`).value.trim();
  const body = elements.commitments.querySelector(`[data-draft-body="${id}"]`).value.trim();
  if (!subject || !body) { notify("Draft subject and body are required.", true); return; }
  try {
    await api(`/actions/${id}/draft`, { method: "PUT", body: JSON.stringify({ subject, body }) });
    notify("Draft changes saved. Nothing was sent."); await refresh();
  } catch (error) { notify(error.message, true); }
}

async function saveDecisionProposal(id) {
  const value = name => elements.commitments.querySelector(`[data-decision-${name}="${id}"]`).value.trim();
  const proposal = { title: value("title"), decision: value("outcome"), rationale: value("rationale") || null };
  if (!proposal.title || !proposal.decision) { notify("Decision title and outcome are required.", true); return; }
  try {
    await api(`/actions/${id}/decision-proposal`, { method: "PUT", body: JSON.stringify(proposal) });
    notify("Decision proposal saved. Approve it before recording."); await refresh();
  } catch (error) { notify(error.message, true); }
}

async function saveFollowUpProposal(id) {
  const value = name => elements.commitments.querySelector(`[data-follow-up-${name}="${id}"]`).value.trim();
  const proposal = { follow_up_at: value("at"), subject: value("subject"), body: value("body") };
  if (!proposal.follow_up_at || !proposal.subject || !proposal.body) { notify("Follow-up time, subject and body are required.", true); return; }
  try {
    await api(`/actions/${id}/follow-up-proposal`, { method: "PUT", body: JSON.stringify(proposal) });
    notify("Follow-up saved. Approve it before activation."); await refresh();
  } catch (error) { notify(error.message, true); }
}

async function completeCommitment(id) {
  try {
    await api(`/commitments/${id}/complete`, { method: "POST", body: JSON.stringify({ note: "Marked complete in dashboard" }) });
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

async function importGmail() {
  const button = document.querySelector("#gmail-import-button");
  button.disabled = true;
  try {
    const result = await api("/automation/inbox", { method: "POST", body: JSON.stringify({ label: "AI-Operator", max_results: 10 }) });
    const reminders = result.open_loop_monitor.created.length;
    const documents = result.document_automation || { review_ready: [], analyzed_only: [], errors: [] };
    const documentCount = documents.review_ready.length + documents.analyzed_only.length;
    notify(`Scan #${result.run_id}: ${result.processed.length} new emails, ${documentCount} new documents, ${reminders} reminder${reminders === 1 ? "" : "s"}.`, result.errors.length > 0 || documents.errors.length > 0);
    await refresh();
  } catch (error) { notify(error.message, true); }
  finally { button.disabled = false; }
}

function renderInboxSchedule() {
  const schedule = state.inboxSchedule;
  if (!schedule) return;
  const enabled = Boolean(schedule.enabled);
  const status = schedule.last_status ? ` · last ${schedule.last_status}` : "";
  document.querySelector("#inbox-schedule-status").textContent = enabled ? `On every ${schedule.interval_minutes} minutes${status}` : `Off${status}`;
  const interval = document.querySelector("#inbox-schedule-interval");
  interval.value = schedule.interval_minutes || 15;
  interval.disabled = enabled;
  document.querySelector("#inbox-schedule-toggle").textContent = enabled ? "Disable" : "Enable";
}

async function toggleInboxSchedule() {
  const schedule = state.inboxSchedule;
  let interval = schedule.interval_minutes || 15;
  if (!schedule.enabled) interval = Number(document.querySelector("#inbox-schedule-interval").value);
  if (!Number.isInteger(interval) || interval < 1 || interval > 1440) { notify("Enter 1 to 1440 minutes.", true); return; }
  try {
    await api("/automation/inbox/schedule", { method: "PUT", body: JSON.stringify({ enabled: !Boolean(schedule.enabled), interval_minutes: interval, label: "AI-Operator", max_results: 10 }) });
    notify(schedule.enabled ? "Automatic inbox scan disabled." : "Automatic inbox scan enabled. Nothing will be sent.");
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

function renderLatestInboxRun() {
  const target = document.querySelector("#last-inbox-run");
  const run = state.automationRuns.find(item => item.workflow === "inbox_automation");
  if (!run) { target.textContent = "No inbox scan recorded."; return; }
  const result = parseJson(run.result_json);
  const documents = result.document_automation || {};
  const documentCount = (documents.review_ready?.length || 0) + (documents.analyzed_only?.length || 0);
  const errorCount = (result.errors?.length || 0) + (documents.errors?.length || 0);
  const finished = run.finished_at || run.started_at;
  target.textContent = `Last scan #${run.id} · ${result.processed?.length || 0} new · ${result.skipped?.length || 0} skipped · ${documentCount} documents · ${errorCount} errors · ${finished}`;
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
elements.briefingButton.addEventListener("click", generateExecutiveBriefing);
document.querySelector("#document-upload-form").addEventListener("submit", uploadDocument);
document.querySelector("#operator-question-form").addEventListener("submit", askOperator);
document.querySelector("#gmail-attachments-button").addEventListener("click", importGmailAttachments);
document.querySelector("#gmail-import-button").addEventListener("click", importGmail);
document.querySelector("#inbox-schedule-toggle").addEventListener("click", toggleInboxSchedule);
document.querySelector("#schedule-toggle-button").addEventListener("click", toggleSchedule);
document.querySelectorAll(".view-tab").forEach(button => button.addEventListener("click", () => switchView(button.dataset.view)));
switchView("documents");
refresh();
