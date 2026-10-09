import { ApiError } from "./api-client";
import { appEvents } from "./app-events";
import { getApiClient, getNavigation } from "./runtime";
import { createAppState } from "./state";
import { CommandOutbox } from "./command-outbox";
import { useAuthStore } from "./stores/auth";
import { useUiStore } from "./stores/ui";
import { buildCommandEnvelope, reduceRealtimeEnvelope } from "./ws-protocol";

export function mountLegacyApp() {
const state = createAppState();
const commandOutbox = new CommandOutbox();
const appRouter = getNavigation();
const authStore = useAuthStore();
const uiStore = useUiStore();
const authChannel = "BroadcastChannel" in window ? new BroadcastChannel("ai-mm-auth") : null;

const els = Object.fromEntries(
  [
    "authView", "appView", "appSidebar",
    "createView", "recordsView", "gameView", "categoryGrid", "modeControl", "selectedCategoryText",
    "selectedModeText", "uploadZone", "scriptFileInput", "chooseFileBtn", "exampleScriptBtn",
    "uploadTitle", "uploadMeta", "scriptError", "scriptPreview", "previewTitle", "previewStages",
    "previewRoles", "previewAgents", "roleOptions", "startGameBtn",
    "leaveGameBtn", "expandSidebarBtn", "gameModeLabel", "gameTitle", "currentStage", "totalStages", "playerIntel",
    "searchTargets", "messages", "speechForm", "speechInput", "humanRole", "totalRoles",
    "agentCount", "castList", "dispatchList", "advanceBtn", "toast", "whisperSection",
    "whisperTarget", "whisperInviteBtn", "whisperCloseBtn", "whisperStatus",
    "channelControl", "publicChannelBtn", "privateChannelBtn", "channelTarget", "speechSubmitBtn",
    "compactGameTabs", "compactIntelTab", "compactDialogueTab", "compactDmTab",
    "gameLayout", "intelPanel", "dialoguePanel", "dmPanel",
    "phaseStatus", "roundClock", "roundCountdown", "phaseStage", "phaseRoundLabel",
    "phaseRoundTitle", "phaseEyebrow", "phaseTitle", "narrationBlock", "dmNarration",
    "streamCursor", "privateDossier", "dossierRole", "dossierIdentity", "dossierBlocks",
    "dossierTask", "phaseHint", "phaseContinueBtn", "phaseObjectiveList", "phaseCastList",
    "stageResolutionPanel", "resolutionTitle", "resolutionMetric", "resolutionRoleResults",
    "resolutionVoteSection", "resolutionVoteLabel", "resolutionVotePrompt", "resolutionVoteRule", "resolutionCandidates",
    "submitStageVoteBtn", "resolutionVoteResult",
    "phaseRules", "investigationEndVoteStatus", "agentAutonomyState", "notebookAutoTab", "notebookCluesTab", "notebookManualTab",
    "notebookAutoPane", "notebookCluesPane", "notebookManualPane", "notebookAutoEntries",
    "ownedClues",
    "notebookManualNotes", "notebookSaveState", "roleRecordsModal",
    "closeRoleRecordsBtn", "auditRoleTabs", "auditClues", "auditAutomaticEntries",
    "auditReasoningEntries", "auditStageResults", "auditOperations", "auditAgentContexts",
    "conversationParticipants",
  ].map((id) => [id, document.getElementById(id)])
);
const avatarActionTimers = new WeakMap();

const categoryNames = {
  mystery: "悬疑推理",
  adventure: "冒险探索",
  fantasy: "奇幻世界",
  history: "历史演绎",
  custom: "自定义",
};
const modeNames = { narrative: "剧情体验", deduction: "推理对抗", faction: "阵营博弈" };
const apiClient = getApiClient();

async function api(path, options = {}) {
  try {
    return await apiClient.request(path, options);
  } catch (error) {
    if (
      error instanceof ApiError
      && error.status === 404
      && error.body.detail === "Not Found"
      && (path.includes("/notebook") || path.includes("/role-records"))
    ) {
      throw new Error("后端仍在运行旧版本，请重启项目后刷新页面");
    }
    throw error;
  }
}

function showAuth(preserveReturnPath = true) {
  if (preserveReturnPath) {
    appRouter.rememberCurrentReturnPath();
  } else {
    appRouter.clearReturnPath();
  }
  authStore.clearSession();
  uiStore.setGameActive(false);
  state.csrfToken = "";
  state.user = null;
  state.script = null;
  state.builtinScriptId = null;
  state.preview = null;
  state.game = null;
  state.lastEventId = 0;
  state.roleRecords = null;
  setSidebarCollapsed(false);
  els.appView.classList.remove("game-active");
  syncAccountAvatar();
  resetNotebook();
  closeRoleRecords();
  localStorage.removeItem("ai_mm_token");
  closeGameSocket();
  stopCountdown();
  els.uploadTitle.textContent = "拖入案件文件，或从本机选择";
  els.uploadMeta.textContent = "JSON · 最大 5 MB";
  els.scriptPreview.classList.add("hidden");
  els.scriptError.textContent = "";
  setCreationStep(1);
  els.authView.classList.remove("hidden");
  els.appView.classList.add("hidden");
  const authMode = appRouter.current().name === "register" ? "register" : "login";
  void appRouter.replace({ name: authMode });
  animateView(els.authView);
}

async function enterApp(user) {
  authStore.setSession(user);
  state.csrfToken = authStore.csrfToken;
  state.user = authStore.user;
  els.authView.classList.add("hidden");
  els.appView.classList.remove("hidden");
  state.catalog = await api("/api/catalog");
  renderCatalog();
  const returnPath = appRouter.consumeReturnPath();
  if (returnPath) {
    await appRouter.replacePath(returnPath);
  } else if (["login", "register", "not-found"].includes(appRouter.current().name)) {
    await appRouter.replace({ name: "case-create" });
  }
  await restoreRoute();
}

function syncAccountAvatar() {
  uiStore.setGameActive(Boolean(state.user) && els.appView.classList.contains("game-active"));
}

function renderCatalog() {
  const category = state.catalog.categories.find((item) => item.id === "mystery");
  const mode = state.catalog.modes.find((item) => item.id === "deduction");
  state.category = category?.id || "mystery";
  state.mode = mode?.id || "deduction";
  els.selectedCategoryText.textContent = category?.name || "悬疑推理";
  els.selectedModeText.textContent = mode?.name || "推理对抗";

  els.categoryGrid.innerHTML = "";
  els.modeControl.innerHTML = "";
}

function showPage(name, updateHistory = true) {
  closeGameSocket();
  closeRoleRecords();
  setSidebarCollapsed(false);
  els.appView.classList.remove("game-active");
  syncAccountAvatar();
  for (const view of [els.createView, els.recordsView, els.gameView]) view.classList.add("hidden");
  if (name === "records") {
    if (updateHistory) void appRouter.push({ name: "case-list" });
    els.recordsView.classList.remove("hidden");
    animateView(els.recordsView);
  } else {
    if (updateHistory) void appRouter.push({ name: "case-create" });
    els.createView.classList.remove("hidden");
    setCreationStep(state.preview ? 2 : 1);
    animateView(els.createView);
  }
}

async function restoreRoute() {
  const route = appRouter.current();
  if (route.name === "case-detail") {
    await openGame(route.gameId, null, false);
    return;
  }
  if (route.name === "case-list") {
    showPage("records", false);
    return;
  }
  if (route.name !== "case-create") await appRouter.replace({ name: "case-create" });
  showPage("create", false);
}

function setCreationStep(step) {
  document.querySelectorAll(".step-indicator span").forEach((item, index) => {
    const current = index + 1;
    item.classList.toggle("active", current === step);
    item.classList.toggle("complete", current < step);
  });
}

async function readScriptFile(file) {
  els.scriptError.textContent = "";
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) {
    els.scriptError.textContent = "剧本文件不能超过 5 MB";
    return;
  }
  try {
    state.builtinScriptId = null;
    state.script = JSON.parse(await file.text());
    els.uploadTitle.textContent = file.name;
    els.uploadMeta.textContent = `${Math.max(1, Math.ceil(file.size / 1024))} KB · JSON`;
    await inspectScript();
  } catch (error) {
    state.script = null;
    els.scriptPreview.classList.add("hidden");
    setCreationStep(1);
    els.scriptError.textContent = error instanceof SyntaxError ? "JSON 格式无效" : error.message;
  }
}

async function inspectScript() {
  if (!state.script && !state.builtinScriptId) return;
  try {
    state.preview = await api("/api/scripts/inspect", {
      method: "POST",
      body: JSON.stringify({ mode: state.mode, ...scriptSource() }),
    });
    els.scriptError.textContent = "";
    renderScriptPreview();
  } catch (error) {
    state.preview = null;
    els.scriptPreview.classList.add("hidden");
    setCreationStep(1);
    els.scriptError.textContent = error.message;
  }
}

function scriptSource() {
  return state.builtinScriptId ? { script_id: state.builtinScriptId } : { script: state.script };
}

function renderScriptPreview() {
  const preview = state.preview;
  els.previewTitle.textContent = preview.title;
  els.previewStages.textContent = String(preview.total_stages);
  els.previewRoles.textContent = String(preview.role_count);
  els.previewAgents.textContent = String(preview.ai_agent_count);
  els.roleOptions.innerHTML = "";
  preview.playable_roles.forEach((role, index) => {
    const label = document.createElement("label");
    label.className = "role-option";
    label.innerHTML = `
      <input type="radio" name="player-role" value="${escapeHtml(role.role_id)}" ${index === 0 ? "checked" : ""} />
      <span><strong>${escapeHtml(role.role_name)}</strong><span>${escapeHtml(role.public_identity)}</span></span>`;
    els.roleOptions.appendChild(label);
  });
  els.scriptPreview.classList.remove("hidden");
  setCreationStep(2);
}

async function startGame() {
  const selectedRole = document.querySelector('input[name="player-role"]:checked');
  if ((!state.script && !state.builtinScriptId) || !state.preview || !selectedRole) return;
  setCreationStep(3);
  els.startGameBtn.disabled = true;
  els.startGameBtn.innerHTML = "<span>DM 正在建立调查现场...</span><b>···</b>";
  try {
    const game = await api("/api/games", {
      method: "POST",
      body: JSON.stringify({
        category: state.category,
        mode: state.mode,
        player_role_id: selectedRole.value,
        ...scriptSource(),
      }),
    });
    appEvents.emit("records:invalidate", {});
    await openGame(game.id, game);
  } catch (error) {
    setCreationStep(2);
    toast(error.message);
  } finally {
    els.startGameBtn.disabled = false;
    els.startGameBtn.innerHTML = "<span>启动 DM，进入案发现场</span><b>→</b>";
  }
}

async function openGame(gameId, summary = null, updateHistory = true) {
  closeGameSocket();
  state.lastEventId = 0;
  let detail;
  try {
    detail = await api(`/api/games/${gameId}`);
  } catch (error) {
    toast(error.message);
    return;
  }
  state.game = { ...(summary || {}), ...detail };
  if (updateHistory) void appRouter.push({ name: "case-detail", gameId: Number(gameId) });
  state.roleRecords = null;
  setSidebarCollapsed(false);
  els.appView.classList.add("game-active");
  syncAccountAvatar();
  closeRoleRecords();
  els.createView.classList.add("hidden");
  els.recordsView.classList.add("hidden");
  els.gameView.classList.remove("hidden");
  animateView(els.gameView);
  els.gameTitle.textContent = detail.title;
  els.gameModeLabel.textContent = `${categoryNames[detail.category] || detail.category} · ${modeNames[detail.mode] || detail.mode}`;
  els.currentStage.textContent = String(detail.current_stage);
  els.totalStages.textContent = String(detail.total_stages);
  els.messages.innerHTML = "";
  resetWhisper();
  resetPhaseExperience();
  resetNotebook();
  setCompactGamePanel("dialogue", false);
  loadNotebook(gameId);
  connectGame(gameId);
}

function setSidebarCollapsed(collapsed, focusTarget = false) {
  const active = Boolean(collapsed);
  state.sidebarCollapsed = active;
  uiStore.setSidebarCollapsed(active);
  els.appView?.classList.toggle("sidebar-collapsed", active);
  els.appSidebar?.setAttribute("aria-hidden", String(active));
  els.appSidebar?.toggleAttribute("inert", active);
  els.expandSidebarBtn?.setAttribute("aria-expanded", String(!active));
  if (focusTarget) {
    window.requestAnimationFrame(() => {
      (active ? els.expandSidebarBtn : document.getElementById("collapseSidebarBtn"))?.focus();
    });
  }
}

const compactGameMedia = window.matchMedia("(max-width: 1180px)");

function syncCompactGamePanel() {
  const compact = compactGameMedia.matches;
  const panels = {
    intel: els.intelPanel,
    dialogue: els.dialoguePanel,
    dm: els.dmPanel,
  };
  Object.entries(panels).forEach(([name, panel]) => {
    if (compact) {
      panel.setAttribute("aria-hidden", String(name !== state.compactPanel));
    } else {
      panel.removeAttribute("aria-hidden");
    }
  });
}

function setCompactGamePanel(panelName, animate = true) {
  if (!["intel", "dialogue", "dm"].includes(panelName)) return;
  state.compactPanel = panelName;
  els.gameLayout.dataset.compactPanel = panelName;
  document.querySelectorAll(".compact-game-tab").forEach((button) => {
    const selected = button.dataset.panel === panelName;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  syncCompactGamePanel();

  const panel = {
    intel: els.intelPanel,
    dialogue: els.dialoguePanel,
    dm: els.dmPanel,
  }[panelName];
  if (compactGameMedia.matches && animate) animateView(panel);
  if (panelName === "dialogue") els.messages.scrollTop = els.messages.scrollHeight;
}

const scenePhaseOrder = ["briefing", "private_reveal", "investigation", "dm_hosting"];

function resetPhaseExperience() {
  stopCountdown();
  clearAgentActivity();
  state.currentPhase = "briefing";
  state.phaseSummary = null;
  state.activeMechanics = [];
  state.enabledActions = [];
  state.stageResolution = null;
  state.selectedVoteRoleId = null;
  els.phaseStage.classList.add("hidden");
  els.privateDossier.classList.add("hidden");
  els.stageResolutionPanel.classList.add("hidden");
  els.investigationEndVoteStatus.classList.add("hidden");
  els.investigationEndVoteStatus.innerHTML = "";
  els.streamCursor.classList.add("hidden");
  els.dmNarration.textContent = "";
  els.phaseContinueBtn.disabled = true;
  els.roundClock.classList.add("hidden");
}

function renderScenePhase(summary) {
  if (!summary) return;
  state.phaseSummary = summary;
  state.currentPhase = summary.phase;
  state.enabledActions = summary.enabled_actions || [];
  renderOwnedClues();
  els.currentStage.textContent = String(summary.stage);
  els.totalStages.textContent = String(summary.total_stages);
  els.phaseStatus.textContent = summary.phase_label;
  els.phaseRoundLabel.textContent = `ACT ${String(summary.stage).padStart(2, "0")}`;
  els.phaseRoundTitle.textContent = summary.stage_title;
  els.phaseTitle.textContent = summary.stage_title;
  const penaltyText = (summary.player_penalties || [])
    .map((penalty) => `${penalty.label}：${penalty.description}`)
    .join("；");
  renderInvestigationRules(summary, penaltyText);
  els.agentAutonomyState.classList.toggle("hidden", !summary.autonomy?.enabled);

  const currentIndex = scenePhaseOrder.indexOf(summary.phase);
  document.querySelectorAll(".phase-sequence li").forEach((item, index) => {
    item.classList.toggle("active", index === currentIndex);
    item.classList.toggle("complete", index < currentIndex);
  });
  renderPhaseObjectives(summary.public_tasks || []);
  if (summary.resolution) renderStageResolution(summary.resolution);

  if (summary.phase === "investigation") {
    els.advanceBtn.disabled = !summary.can_manual_end;
    els.advanceBtn.textContent = summary.can_manual_end
      ? summary.end_condition?.met
        ? "建议目标已达成，发起结束投票"
        : "发起结束投票"
      : "等待条件达成或计时结束";
    applyActionAvailability();
    return;
  }

  stopCountdown();
  showPhaseStage(true);
  els.privateDossier.classList.add("hidden");
  els.phaseEyebrow.textContent = {
    briefing: "DM BRIEFING · 公开信息",
    private_reveal: "ROLE DOSSIER · 仅你可见",
    dm_hosting: "DM HOSTING · 本幕收束",
  }[summary.phase] || "DM HOSTING";
  els.phaseHint.textContent = {
    briefing: "请听完 DM 的案情通报与本幕公开任务",
    private_reveal: "阅读你的独属剧本和个人任务",
    dm_hosting: "DM 正在封存证词并推进故事",
  }[summary.phase] || "";
}

function renderInvestigationRules(summary, penaltyText = "") {
  const condition = summary?.end_condition;
  const progress = (condition?.items || [])
    .map((item) => `${item.label} ${item.current}/${item.target}`)
    .join(condition?.mode === "any" ? "，任一达成" : "，");
  const readyText = condition?.met && !condition?.auto_end
    ? "建议目标已达成但不会自动结束；你可以继续调查或发起结束投票"
    : "";
  els.phaseRules.textContent = [
    summary?.end_condition_text || "由 DM 根据本幕规则收束",
    progress ? `当前进度：${progress}` : "",
    readyText,
    penaltyText,
  ].filter(Boolean).join(" · ");
  els.phaseRules.classList.toggle("ready", Boolean(condition?.met));
}

function renderInvestigationEndVote(vote) {
  if (!vote) return;
  const ballots = (vote.ballots || [])
    .map((ballot) => `
      <li class="${ballot.approved ? "approved" : "rejected"}">
        <span>${escapeHtml(ballot.voter_role_name)}</span>
        <b>${ballot.approved ? "同意" : "反对"}</b>
      </li>`)
    .join("");
  els.investigationEndVoteStatus.className = `end-vote-status ${
    vote.approved ? "approved" : "rejected"
  }`;
  els.investigationEndVoteStatus.innerHTML = `
    <strong>${vote.approved ? "结束投票通过" : "结束投票未通过"}</strong>
    <p>${escapeHtml(vote.message || "")}</p>
    <div><b>${escapeHtml(vote.approved_votes)}/${escapeHtml(vote.total_votes)}</b><span>同意 · 需要 ${escapeHtml(vote.required_votes)} 票</span></div>
    <ul>${ballots}</ul>`;
}

function showPhaseStage(show) {
  els.phaseStage.classList.toggle("hidden", !show);
  els.gameLayout.classList.toggle("hidden", show);
  els.compactGameTabs.classList.toggle("hidden", show);
}

function renderPhaseObjectives(tasks) {
  els.phaseObjectiveList.innerHTML = "";
  tasks.forEach((task, index) => {
    const item = document.createElement("li");
    item.innerHTML = `<b>${String(index + 1).padStart(2, "0")}</b><span>${escapeHtml(task)}</span>`;
    els.phaseObjectiveList.appendChild(item);
  });
  if (!tasks.length) {
    els.phaseObjectiveList.innerHTML = "<li><span>等待 DM 发布本幕任务</span></li>";
  }
}

function renderPhaseCast(roles, humanRoleId) {
  els.phaseCastList.innerHTML = "";
  roles.forEach((role) => {
    const item = document.createElement("div");
    const isHuman = role.role_id === humanRoleId;
    item.className = "phase-cast-item";
    item.innerHTML = `
      ${roleAvatarMarkup(role.role_id, role.role_name, {
        isHuman,
        size: "small",
        live: true,
      })}
      <div><strong>${escapeHtml(role.role_name)}</strong><small>${escapeHtml(role.public_identity)}</small></div>`;
    els.phaseCastList.appendChild(item);
  });
}

function beginNarration(message) {
  showPhaseStage(true);
  setComposerBusy(false);
  els.privateDossier.classList.add("hidden");
  if (message.phase !== "dm_hosting") {
    els.stageResolutionPanel.classList.add("hidden");
  }
  els.phaseTitle.textContent = message.title || state.phaseSummary?.stage_title || "DM 主持";
  els.dmNarration.textContent = "";
  els.narrationBlock.classList.remove("hidden");
  els.streamCursor.classList.remove("hidden");
  setPhaseContinue("DM 正在讲述", false);
}

function appendNarration(content) {
  els.dmNarration.textContent += content || "";
}

function finishNarration(message) {
  els.streamCursor.classList.add("hidden");
  setPhaseContinue(
    message.continue_label || "继续",
    message.can_continue !== false,
  );
  els.phaseHint.textContent = state.currentPhase === "briefing"
    ? "公开信息已发布，下一步将向每个角色单独发放剧本"
    : message.can_continue === false
      ? "请先完成本幕集体决策，DM 才会开放后续剧情"
      : "本幕主持已结束，可以继续推进故事";
}

function renderPrivateAssignment(message) {
  const assignment = message.assignment;
  renderScenePhase(message.phase);
  showPhaseStage(true);
  els.narrationBlock.classList.add("hidden");
  els.privateDossier.classList.remove("hidden");
  els.stageResolutionPanel.classList.add("hidden");
  els.phaseTitle.textContent = "你的角色剧本";
  els.dossierRole.textContent = assignment.role_name;
  els.dossierIdentity.textContent = assignment.public_identity;
  els.dossierTask.textContent = assignment.personal_task;
  els.dossierBlocks.innerHTML = "";
  assignment.blocks.forEach((block, index) => {
    const item = document.createElement("article");
    item.innerHTML = `
      <span>PRIVATE ${String(index + 1).padStart(2, "0")}</span>
      <p>${escapeHtml(block.content)}</p>`;
    els.dossierBlocks.appendChild(item);
  });
  if (!assignment.blocks.length) {
    els.dossierBlocks.innerHTML = "<article><p>本幕没有新增私人剧本。</p></article>";
  }
  renderIntel(assignment.blocks);
  renderDispatch(message.dispatch);
  setPhaseContinue("我已阅读，进入调查", true);
  els.phaseHint.textContent = "确认后将开放本幕配置的公聊、搜证与私聊操作";
}

function openInvestigation(message) {
  renderScenePhase(message.phase);
  els.investigationEndVoteStatus.classList.add("hidden");
  els.investigationEndVoteStatus.innerHTML = "";
  state.activeMechanics = message.active_mechanics || [];
  state.enabledActions = message.phase.enabled_actions || [];
  if (Array.isArray(message.clues)) {
    state.notebook.clues = message.clues;
    renderOwnedClues();
  }
  showPhaseStage(false);
  els.stageResolutionPanel.classList.add("hidden");
  renderIntel((message.stage_info || []).filter((block) => block.visibility !== "public"));
  renderSearchTargets(state.activeMechanics);
  renderWhisperControls(
    state.activeMechanics,
    state.game.publicRoles || [],
    state.game.player_role_id,
    message.whisper_status,
  );
  applyActionAvailability();
  setCompactGamePanel("dialogue", false);
  addMessage(
    "dm",
    "DM Agent",
    `${message.phase.stage_title}调查开始。可用操作：${formatEnabledActions(state.enabledActions)}。${
      message.phase.autonomy?.enabled
        ? "角色 Agent 已开始依据各自任务自主调查。"
        : ""
    }`,
  );
  startCountdown(message.phase.remaining_seconds);
}

function showReplay(message) {
  stopCountdown();
  clearAgentActivity();
  state.currentPhase = "replay";
  state.enabledActions = [];
  if (state.game) state.game.status = "completed";
  showPhaseStage(true);
  els.phaseStatus.textContent = "终局复盘";
  els.phaseRoundLabel.textContent = "CASE CLOSED";
  els.phaseRoundTitle.textContent = "案件终局";
  const finalDecision = message.final_decision;
  const truthRevealed = message.truth_revealed !== false;
  els.phaseEyebrow.textContent = truthRevealed
    ? "DM REPLAY · 真相公开"
    : "DM VERDICT · 错误指认";
  els.phaseTitle.textContent = truthRevealed ? "完整案件复盘" : "最终指认失败";
  els.privateDossier.classList.add("hidden");
  els.stageResolutionPanel.classList.add("hidden");
  els.narrationBlock.classList.remove("hidden");
  els.streamCursor.classList.add("hidden");
  const timeline = Object.values(message.timeline || {});
  const narrativeParts = [
    message.verdict,
    message.full_story !== message.verdict ? message.full_story : "",
    ...timeline,
  ].filter(Boolean);
  els.dmNarration.textContent = narrativeParts.join("\n\n");
  const decisionSummary = finalDecision?.selected_role_name
    ? `最终指认：${finalDecision.selected_role_name}`
    : "案件已形成最终结果";
  renderPhaseObjectives(
    truthRevealed
      ? [decisionSummary, "指认成立，完整真相已经公开", ...timeline]
      : [decisionSummary, "指认未成立，该角色并非真正凶手", "真正作案者没有在本局中公开"],
  );
  document.querySelectorAll(".phase-sequence li").forEach((item) => {
    item.classList.remove("active");
    item.classList.add("complete");
  });
  els.phaseHint.textContent = truthRevealed
    ? "指认正确，本局记录与完整真相已保存"
    : "指认错误，本局仍已形成明确结局并保存全部记录";
  setPhaseContinue("查看全部角色记录", true);
  els.advanceBtn.classList.add("hidden");
  setComposerBusy(false);
  loadNotebook(state.game?.id);
}

function renderStageResolution(resolution) {
  if (!resolution) return;
  if (state.stageResolution?.stage !== resolution.stage || !resolution.vote?.pending) {
    state.selectedVoteRoleId = null;
  }
  state.stageResolution = resolution;
  els.stageResolutionPanel.classList.remove("hidden");
  els.resolutionTitle.textContent = resolution.title || "本幕结算";
  const metric = resolution.metric || { label: "阶段成果", unit: "" };
  els.resolutionMetric.textContent = `${metric.label} · 累计值`;
  els.resolutionRoleResults.innerHTML = "";
  (resolution.role_results || []).forEach((result) => {
    const row = document.createElement("article");
    const sign = Number(result.delta) >= 0 ? "+" : "";
    const reasons = (result.reasons || [])
      .map((reason) => `${reason.label} ${reason.count} 次 ${Number(reason.points) >= 0 ? "+" : ""}${reason.points}${metric.unit}`)
      .join(" · ") || "本幕没有产生可计分操作";
    row.className = "resolution-role-result";
    row.innerHTML = `
      ${roleAvatarMarkup(result.role_id, result.role_name, {
        isHuman: result.controller === "human",
        size: "small",
        live: true,
      })}
      <div>
        <strong>${escapeHtml(result.role_name)}</strong>
        <p>${escapeHtml(reasons)}</p>
      </div>
      <span class="${Number(result.delta) < 0 ? "negative" : ""}">${sign}${escapeHtml(result.delta)} ${escapeHtml(metric.unit)}</span>
      <b>${escapeHtml(result.total)} ${escapeHtml(metric.unit)}</b>
      ${taskResultMarkup(result.task_results)}`;
    els.resolutionRoleResults.appendChild(row);
  });

  const vote = resolution.vote;
  els.resolutionVoteSection.classList.toggle("hidden", !vote);
  if (!vote) {
    setPhaseContinue(
      Number(resolution.stage) >= Number(state.phaseSummary?.total_stages)
        ? "查看终局复盘"
        : "进入下一幕",
      true,
    );
    return;
  }

  els.resolutionVoteLabel.textContent = vote.kind === "final"
    ? "FINAL ACCUSATION"
    : "COLLECTIVE DECISION";
  els.resolutionVotePrompt.textContent = vote.prompt;
  els.resolutionVoteRule.textContent = vote.tie_breaker_label || "";
  els.resolutionCandidates.innerHTML = "";
  (vote.eligible_roles || []).forEach((role) => {
    const button = document.createElement("button");
    const selected = state.selectedVoteRoleId === role.role_id;
    const resultSelected = !vote.pending && vote.selected_role_id === role.role_id;
    button.type = "button";
    button.className = [
      "resolution-candidate",
      selected ? "selected" : "",
      resultSelected ? "result-selected" : "",
    ].filter(Boolean).join(" ");
    button.dataset.voteRoleId = role.role_id;
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(selected || resultSelected));
    button.disabled = !vote.pending;
    button.innerHTML = `
      ${roleAvatarMarkup(role.role_id, role.role_name, { size: "small" })}
      <span><strong>${escapeHtml(role.role_name)}</strong><small>${escapeHtml(role.public_identity)}</small></span>`;
    button.addEventListener("click", () => selectResolutionCandidate(role.role_id));
    els.resolutionCandidates.appendChild(button);
  });

  els.submitStageVoteBtn.classList.toggle("hidden", !vote.pending);
  els.submitStageVoteBtn.disabled = !state.selectedVoteRoleId || !vote.pending;
  els.submitStageVoteBtn.innerHTML = `<span>${
    vote.kind === "final" ? "确认最终指认" : "提交本幕投票"
  }</span><b>→</b>`;
  els.resolutionVoteResult.classList.toggle("hidden", vote.pending);
  if (vote.pending) {
    els.resolutionVoteResult.innerHTML = "";
    setPhaseContinue(
      vote.kind === "final" ? "完成最终指认后查看结局" : "完成本幕投票后继续",
      false,
    );
    return;
  }

  const tally = (vote.tally || [])
    .map((item) => `<li><span>${escapeHtml(item.role_name)}</span><b>${escapeHtml(item.votes)} 票</b></li>`)
    .join("");
  els.resolutionVoteResult.innerHTML = `
    <strong>${vote.correct === true ? "指认成立" : vote.correct === false ? "指认未成立" : "投票完成"}</strong>
    <p>${escapeHtml(vote.outcome_text || "")}</p>
    <ul>${tally}</ul>`;
  setPhaseContinue(
    vote.kind === "final" ? "查看最终结局" : "进入下一幕",
    true,
  );
  els.phaseHint.textContent = vote.kind === "final"
    ? "最终指认已经封存，DM 将发布对应结局"
    : "本幕投票与处罚已经生效，可以继续推进";
  loadNotebook(state.game?.id);
}

function selectResolutionCandidate(roleId) {
  const vote = state.stageResolution?.vote;
  if (!vote?.pending) return;
  state.selectedVoteRoleId = roleId;
  document.querySelectorAll(".resolution-candidate").forEach((button) => {
    const selected = button.dataset.voteRoleId === roleId;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-checked", String(selected));
  });
  els.submitStageVoteBtn.disabled = false;
}

function applyActionAvailability() {
  const speechEnabled = state.currentPhase === "investigation"
    && (
      state.whisper.channel === "private"
        ? state.enabledActions.includes("whisper") && Boolean(state.whisper.activeTargetRoleId)
        : state.enabledActions.includes("public_speech")
    );
  els.speechForm.classList.toggle("action-locked", !speechEnabled);
  setComposerBusy(false);
  els.advanceBtn.classList.toggle("hidden", state.currentPhase !== "investigation");
}

function setPhaseContinue(label, enabled) {
  els.phaseContinueBtn.disabled = !enabled;
  els.phaseContinueBtn.innerHTML = `<span>${escapeHtml(label)}</span><b>→</b>`;
}

function formatEnabledActions(actions) {
  const labels = {
    public_speech: "公开询问",
    search: "现场搜证",
    whisper: "秘密询问",
  };
  return actions.map((action) => labels[action] || action).join("、") || "等待 DM 指令";
}

function startCountdown(seconds) {
  stopCountdown();
  const duration = Number(seconds);
  if (!Number.isFinite(duration) || duration <= 0) {
    els.roundClock.classList.add("hidden");
    return;
  }
  state.countdownDeadline = Date.now() + duration * 1000;
  els.roundClock.classList.remove("hidden");
  const tick = () => {
    const remaining = Math.max(0, Math.ceil((state.countdownDeadline - Date.now()) / 1000));
    const minutes = String(Math.floor(remaining / 60)).padStart(2, "0");
    const secondsPart = String(remaining % 60).padStart(2, "0");
    els.roundCountdown.textContent = `${minutes}:${secondsPart}`;
    els.roundClock.classList.toggle("urgent", remaining <= 60);
    if (remaining <= 0) stopCountdown(false);
  };
  tick();
  state.countdownTimer = window.setInterval(tick, 1000);
}

function stopCountdown(hide = true) {
  if (state.countdownTimer) window.clearInterval(state.countdownTimer);
  state.countdownTimer = null;
  state.countdownDeadline = null;
  if (hide) els.roundClock.classList.add("hidden");
  els.roundClock.classList.remove("urgent");
}

async function connectGame(gameId, reconnecting = false) {
  if (state.reconnectTimer) window.clearTimeout(state.reconnectTimer);
  state.reconnectTimer = null;
  let ticket;
  try {
    const result = await api(`/api/games/${gameId}/ws-ticket`, { method: "POST" });
    ticket = result.ticket;
  } catch (error) {
    if (state.user) {
      toast(error.message || "调查连接凭证获取失败");
      scheduleGameReconnect(gameId);
    }
    return;
  }
  if (!state.game || Number(state.game.id) !== Number(gameId)) return;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(
    `${protocol}://${location.host}/ws/v1/games/${gameId}?ticket=${encodeURIComponent(ticket)}&after_event_id=${state.lastEventId}`,
  );
  state.ws = socket;
  socket.addEventListener("open", () => {
    state.reconnectAttempts = 0;
    if (reconnecting) toast("调查连接已恢复");
  });
  socket.addEventListener("message", (event) => {
    if (state.ws !== socket) return;
    try {
      handleSocketMessage(JSON.parse(event.data));
    } catch (_) {
      toast("收到无法解析的实时消息");
    }
  });
  socket.addEventListener("close", (event) => {
    const expected = state.expectedSocketClosures.has(socket);
    state.expectedSocketClosures.delete(socket);
    if (state.ws !== socket) return;
    state.ws = null;
    stopCountdown();
    setComposerBusy(false);
    if (expected) {
      return;
    }
    console.warn("调查连接中断", { gameId, code: event.code, reason: event.reason });
    if (event.code === 4401) {
      showAuth();
    } else if (event.code === 4404 || event.code === 4409) {
      toast(event.reason || "案件存档无法恢复");
    } else if (event.code !== 1000) {
      scheduleGameReconnect(gameId);
    }
  });
}

function handleSocketMessage(message) {
  commandOutbox.acknowledge(message);
  const reduction = reduceRealtimeEnvelope(message, state.lastEventId);
  state.lastEventId = reduction.lastEventId;
  if (reduction.snapshotGame) renderGameInit(reduction.snapshotGame);
  reduction.messages.forEach(handleGameMessage);
  if (reduction.snapshotGame && state.ws?.readyState === WebSocket.OPEN) {
    const { commands, expiredCount } = commandOutbox.reconcile(commandContext());
    if (expiredCount) toast("阶段已变化，未确认的旧操作不再重发，请核对案件记录");
    for (const command of commands) state.ws.send(JSON.stringify(command));
    if (commands.some(command => ["player_speech", "whisper_speech"].includes(command.type))) setComposerBusy(true);
  }
}

function scheduleGameReconnect(gameId) {
  if (!state.game || Number(state.game.id) !== Number(gameId)) return;
  if (state.reconnectTimer) return;
  if (state.reconnectAttempts >= 5) {
    toast("调查连接多次恢复失败，请返回案件档案后重试");
    return;
  }
  const delaySeconds = Math.min(10, 2 ** state.reconnectAttempts);
  state.reconnectAttempts += 1;
  toast(`调查连接已中断，${delaySeconds} 秒后自动恢复`);
  state.reconnectTimer = window.setTimeout(() => {
    state.reconnectTimer = null;
    if (!state.game || Number(state.game.id) !== Number(gameId)) return;
    connectGame(gameId, true);
  }, delaySeconds * 1000);
}

function handleGameMessage(message) {
  switch (message.type) {
    case "heartbeat":
      break;
    case "game_init":
      renderGameInit(message);
      break;
    case "phase_changed":
      renderScenePhase(message.phase);
      break;
    case "dm_narration_start":
      beginNarration(message);
      break;
    case "dm_narration_chunk":
      appendNarration(message.content);
      break;
    case "dm_narration_end":
      finishNarration(message);
      loadNotebook(state.game?.id);
      break;
    case "private_script":
      renderPrivateAssignment(message);
      loadNotebook(state.game?.id);
      break;
    case "investigation_open":
      openInvestigation(message);
      break;
    case "human_speech_echo":
      setAvatarAction([message.role_id || state.game?.player_role_id], "public");
      addMessage(
        "user",
        "你",
        message.content,
        {
          roleId: message.role_id || state.game?.player_role_id,
          action: "public",
          isHuman: true,
        },
      );
      break;
    case "ai_speech":
      clearAgentActivity();
      setAvatarAction([message.role_id], "public");
      addMessage(
        "agent",
        message.proactive_response
          ? `${roleName(message.role_id)} · 回应 ${message.target_role_name || roleName(message.target_role_id)}`
          : roleName(message.role_id),
        message.content,
        { roleId: message.role_id, action: "public" },
      );
      if (!message.proactive_response) setComposerBusy(false);
      loadNotebook(state.game?.id);
      break;
    case "agent_activity_start":
      showAgentActivity(message);
      break;
    case "ai_proactive_speech":
      clearAgentActivity();
      setAvatarAction([message.role_id], "public");
      addMessage(
        "agent proactive",
        `${message.role_name || roleName(message.role_id)} · 主动询问 ${message.target_role_name || roleName(message.target_role_id)}`,
        message.content,
        { roleId: message.role_id, action: "public" },
      );
      break;
    case "agent_private_exchange":
      clearAgentActivity();
      addMessage("dm ambient", "DM 动态", message.summary);
      break;
    case "autonomy_status":
      els.agentAutonomyState.classList.toggle("hidden", !message.autonomy?.enabled);
      break;
    case "speech_warning":
      addMessage("dm", "DM 校验", message.message);
      break;
    case "search_result":
      setAvatarAction(
        [message.actor_role_id || state.game?.player_role_id],
        "search",
      );
      addMessage(
        "search",
        `搜证 · ${message.actor_role_name || roleName(message.actor_role_id || state.game?.player_role_id)}`,
        message.clue ? message.clue.content : message.message,
        {
          roleId: message.actor_role_id || state.game?.player_role_id,
          action: "search",
          isHuman: true,
        },
      );
      setCompactGamePanel("dialogue");
      loadNotebook(state.game?.id);
      break;
    case "clue_disclosed": {
      const privateShare = message.channel === "private";
      setAvatarAction(
        [
          message.actor_role_id || state.game?.player_role_id,
          ...(privateShare && message.target_role_id ? [message.target_role_id] : []),
        ],
        privateShare ? "private" : "public",
      );
      const modeLabel = message.owner_view_mode === "distorted" ? "改写后分享" : "如实分享";
      addMessage(
        privateShare ? "user private" : "user",
        `你 · ${modeLabel}`,
        message.content,
        {
          roleId: message.actor_role_id || state.game?.player_role_id,
          action: privateShare ? "private" : "public",
          isHuman: true,
        },
      );
      loadNotebook(state.game?.id);
      break;
    }
    case "agent_search_result":
      clearAgentActivity();
      setAvatarAction([message.actor_role_id], "search");
      if (message.public_status === "shared_with_player") {
        setAvatarAction([state.game?.player_role_id], "private");
      }
      addMessage(
        message.public_status === "shared_with_player" ? "agent private" : "search",
        `搜证 · ${message.actor_role_name || roleName(message.actor_role_id)}`,
        message.summary,
        {
          roleId: message.actor_role_id,
          action: "search",
        },
      );
      loadNotebook(state.game?.id);
      break;
    case "whisper_accepted":
      updateWhisperStatus({
        enabled: true,
        active_target_role_id: message.target_role_id,
        remaining_sessions: message.remaining_sessions,
      });
      setChannel("private");
      addMessage("dm", "DM 私聊", `${message.target_role_name || roleName(message.target_role_id)}接受了私聊邀请。`);
      setCompactGamePanel("dialogue");
      break;
    case "whisper_declined":
      addMessage("dm", "DM 私聊", `${message.target_role_name || roleName(message.target_role_id)}拒绝了邀请：${message.message}`);
      setCompactGamePanel("dialogue");
      break;
    case "whisper_closed":
      addMessage("dm", "DM 私聊", message.target_role_id ? `与${message.target_role_name || roleName(message.target_role_id)}的私聊已结束。` : message.message);
      updateWhisperStatus({ enabled: true, active_target_role_id: null });
      break;
    case "whisper_message":
      setAvatarAction(
        [
          message.sender_role_id,
          message.conversation_role_id || state.whisper.activeTargetRoleId,
          state.game?.player_role_id,
        ],
        "private",
      );
      addMessage(
        `${message.sender_type === "player" ? "user" : "agent"} private`,
        `${message.sender_type === "player" ? "你" : message.sender_role_name} · 私聊`,
        message.content,
        {
          roleId: message.sender_role_id,
          action: "private",
          isHuman: message.sender_type === "player",
        },
      );
      if (message.sender_type === "agent") {
        setComposerBusy(false);
        loadNotebook(state.game?.id);
      }
      break;
    case "stage_advance":
      els.currentStage.textContent = String(message.stage);
      renderIntel(message.new_info);
      renderDispatch(message.dispatch);
      updateWhisperStatus(message.whisper_status);
      addMessage("dm", "DM Agent", `进入阶段 ${message.stage}，新情报已分别发放。`);
      setCompactGamePanel("intel");
      loadNotebook(state.game?.id);
      break;
    case "stage_resolution":
      renderStageResolution(message.resolution);
      break;
    case "investigation_progress":
      if (state.phaseSummary) {
        state.phaseSummary.end_condition = message.condition;
        state.phaseSummary.end_condition_text = message.end_condition_text;
        const penaltyText = (state.phaseSummary.player_penalties || [])
          .map((penalty) => `${penalty.label}：${penalty.description}`)
          .join("；");
        renderInvestigationRules(state.phaseSummary, penaltyText);
        if (state.currentPhase === "investigation" && message.condition?.met) {
          els.advanceBtn.textContent = "建议目标已达成，发起结束投票";
        }
      }
      break;
    case "investigation_end_vote":
      renderInvestigationEndVote(message.vote);
      addMessage("dm", "DM Agent", message.vote.message);
      toast(message.vote.message);
      if (!message.vote.approved) {
        els.advanceBtn.disabled = false;
        els.advanceBtn.textContent = "再次发起结束投票";
      }
      break;
    case "investigation_condition_met":
      addMessage("dm", "DM Agent", message.message);
      toast(message.message);
      break;
    case "replay":
      showReplay(message);
      break;
    case "hint":
      addMessage("dm", "DM 提示", message.content);
      break;
    case "error":
      clearAgentActivity();
      setComposerBusy(false);
      if (state.currentPhase === "investigation") {
        renderScenePhase(state.phaseSummary);
      } else {
        const labels = {
          briefing: "接收我的角色剧本",
          private_reveal: "我已阅读，进入调查",
          dm_hosting: "继续推进故事",
        };
        const resolutionPending = Boolean(state.stageResolution?.vote?.pending);
        if (resolutionPending) renderStageResolution(state.stageResolution);
        setPhaseContinue(
          resolutionPending ? "完成本幕投票后继续" : labels[state.currentPhase] || "重试",
          !resolutionPending,
        );
      }
      toast(message.message);
      break;
  }
}

function renderGameInit(message) {
  state.game.publicRoles = message.public_roles;
  if (Array.isArray(message.history_events)) {
    els.messages.innerHTML = "";
    restoreEvents(message.history_events);
  }
  state.activeMechanics = message.active_mechanics || [];
  state.notebook.clues = message.clues || [];
  renderOwnedClues();
  els.currentStage.textContent = String(message.stage);
  els.totalStages.textContent = String(message.total_stages);
  els.humanRole.textContent = roleName(message.role_info.role_id);
  els.totalRoles.textContent = String(message.orchestration.total_roles);
  els.agentCount.textContent = String(message.orchestration.ai_agent_count);
  renderCast(message.public_roles, message.role_info.role_id);
  renderPhaseCast(message.public_roles, message.role_info.role_id);
  refreshRoleAvatars();
  renderDispatch(message.dispatch);
  renderScenePhase(message.phase);

  if (message.phase?.phase !== "investigation") {
    renderIntel([]);
    resetWhisper();
    applyActionAvailability();
  }

  const completed = state.game?.status === "completed";
  els.advanceBtn.disabled = completed;
  if (completed) els.advanceBtn.textContent = "本局已完成";
}

function renderIntel(blocks) {
  els.playerIntel.innerHTML = "";
  if (!blocks || !blocks.length) {
    els.playerIntel.innerHTML = '<div class="intel-item">本阶段没有新增私人情报</div>';
    return;
  }
  blocks.forEach((block) => {
    const item = document.createElement("div");
    item.className = "intel-item";
    item.textContent = block.content;
    els.playerIntel.appendChild(item);
  });
}

function renderSearchTargets(mechanics) {
  els.searchTargets.innerHTML = "";
  if (!state.enabledActions.includes("search")) {
    els.searchTargets.innerHTML = '<div class="intel-item">本幕未开放现场搜证</div>';
    return;
  }
  const action = (mechanics || []).flatMap((item) => item.actions || []).find((item) => item.type === "search");
  const currentStage = Number(state.phaseSummary?.stage || 1);
  (action?.targets || [])
    .filter((target) => Number(target.unlock_stage || 1) <= currentStage)
    .forEach((target) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "search-button";
      button.textContent = target.name;
      button.addEventListener("click", () => {
        if (sendGame({ type: "search", target_id: target.id })) {
          setAvatarAction([state.game?.player_role_id], "search");
          setCompactGamePanel("dialogue");
        }
      });
      els.searchTargets.appendChild(button);
    });
  if (!els.searchTargets.children.length) els.searchTargets.innerHTML = '<div class="intel-item">本剧本未启用搜证</div>';
}

function renderWhisperControls(mechanics, roles, humanRoleId, status) {
  const action = (mechanics || [])
    .flatMap((item) => item.actions || [])
    .find((item) => item.type === "whisper_invite");
  const enabled = Boolean(action) && state.enabledActions.includes("whisper");
  state.whisper.enabled = enabled;
  els.whisperSection.classList.toggle("hidden", !enabled);
  els.channelControl.classList.toggle("hidden", !enabled);
  if (!enabled) {
    updateWhisperStatus({ enabled: false, active_target_role_id: null });
    return;
  }

  els.whisperTarget.innerHTML = "";
  roles.filter((role) => role.role_id !== humanRoleId).forEach((role) => {
    const option = document.createElement("option");
    option.value = role.role_id;
    option.textContent = role.role_name;
    els.whisperTarget.appendChild(option);
  });
  updateWhisperStatus(status);
}

function updateWhisperStatus(status = {}) {
  const activeTarget = status.active_target_role_id || null;
  state.whisper.activeTargetRoleId = activeTarget;
  els.whisperTarget.disabled = Boolean(activeTarget);
  els.whisperInviteBtn.classList.toggle("hidden", Boolean(activeTarget));
  els.whisperCloseBtn.classList.toggle("hidden", !activeTarget);
  els.privateChannelBtn.disabled = !activeTarget;

  if (activeTarget) {
    els.whisperTarget.value = activeTarget;
    const remaining = Number.isInteger(status.remaining_sessions) ? `，本阶段还可发起 ${status.remaining_sessions} 次` : "";
    els.whisperStatus.textContent = `正在与${roleName(activeTarget)}私聊${remaining}`;
    renderConversationParticipants(activeTarget);
  } else {
    els.whisperStatus.textContent = status.enabled === false ? "本剧本未启用私聊" : "选择一个角色发出邀请";
    renderConversationParticipants(null);
    setChannel("public");
  }
  renderOwnedClues();
}

function setChannel(channel) {
  if (channel === "private" && !state.whisper.activeTargetRoleId) return;
  state.whisper.channel = channel;
  els.publicChannelBtn.classList.toggle("active", channel === "public");
  els.privateChannelBtn.classList.toggle("active", channel === "private");
  if (channel === "private") {
    const targetName = roleName(state.whisper.activeTargetRoleId);
    els.channelTarget.textContent = `仅你、${targetName}和 DM 可见`;
    els.speechInput.placeholder = `私聊 ${targetName}`;
  } else {
    els.channelTarget.textContent = "当前为公开频道";
    els.speechInput.placeholder = "以角色身份公开发言";
  }
  const enabled = state.currentPhase === "investigation"
    && (
      channel === "private"
        ? state.enabledActions.includes("whisper") && Boolean(state.whisper.activeTargetRoleId)
        : state.enabledActions.includes("public_speech")
    );
  els.speechInput.disabled = state.waitingForAgent || !enabled;
  els.speechSubmitBtn.disabled = state.waitingForAgent || !enabled;
  els.speechForm.classList.toggle("action-locked", !enabled);
}

function resetWhisper() {
  state.whisper.enabled = false;
  state.whisper.activeTargetRoleId = null;
  state.whisper.channel = "public";
  els.whisperSection.classList.add("hidden");
  els.channelControl.classList.add("hidden");
  setChannel("public");
}

function renderCast(roles, humanRoleId) {
  els.castList.innerHTML = "";
  roles.forEach((role) => {
    const item = document.createElement("div");
    item.className = "cast-item";
    const isHuman = role.role_id === humanRoleId;
    item.innerHTML = `${roleAvatarMarkup(role.role_id, role.role_name, {
      isHuman,
      size: "small",
      live: true,
    })}<div><strong>${escapeHtml(role.role_name)}</strong><span>${escapeHtml(role.public_identity)}</span></div><span class="cast-tag">${isHuman ? "玩家" : "Agent"}</span>`;
    els.castList.appendChild(item);
  });
}

function renderDispatch(dispatch) {
  els.dispatchList.innerHTML = "";
  (dispatch?.deliveries || []).forEach((delivery) => {
    const item = document.createElement("div");
    item.className = "dispatch-item";
    item.innerHTML = `<span>${escapeHtml(delivery.role_name)}</span><strong>${delivery.block_count} 条</strong>`;
    els.dispatchList.appendChild(item);
  });
}

function resetNotebook() {
  if (state.notebook.saveTimer) window.clearTimeout(state.notebook.saveTimer);
  state.notebook.automatic = [];
  state.notebook.clues = [];
  state.notebook.manualNotes = "";
  state.notebook.activeSection = "automatic";
  state.notebook.saveTimer = null;
  state.notebook.dirty = false;
  if (!els.notebookAutoEntries) return;
  els.notebookAutoEntries.innerHTML = '<div class="notebook-empty">等待 DM 归档信息</div>';
  els.ownedClues.innerHTML = '<div class="notebook-empty">尚未获得私有搜证线索</div>';
  els.notebookManualNotes.value = "";
  els.notebookSaveState.textContent = "输入内容后自动保存";
  setNotebookSection("automatic");
}

function setNotebookSection(section) {
  if (!["automatic", "clues", "manual"].includes(section)) return;
  state.notebook.activeSection = section;
  const automatic = section === "automatic";
  const clues = section === "clues";
  const manual = section === "manual";
  els.notebookAutoTab.classList.toggle("active", automatic);
  els.notebookCluesTab.classList.toggle("active", clues);
  els.notebookManualTab.classList.toggle("active", manual);
  els.notebookAutoTab.setAttribute("aria-selected", String(automatic));
  els.notebookCluesTab.setAttribute("aria-selected", String(clues));
  els.notebookManualTab.setAttribute("aria-selected", String(manual));
  els.notebookAutoPane.classList.toggle("hidden", !automatic);
  els.notebookCluesPane.classList.toggle("hidden", !clues);
  els.notebookManualPane.classList.toggle("hidden", !manual);
}

async function loadNotebook(gameId) {
  if (!gameId || state.game?.id !== gameId) return;
  try {
    const notebook = await api(`/api/games/${gameId}/notebook`);
    if (state.game?.id !== gameId) return;
    state.notebook.automatic = notebook.automatic || [];
    state.notebook.clues = notebook.clues || [];
    renderNotebookEntries();
    renderOwnedClues();
    if (!state.notebook.dirty) {
      state.notebook.manualNotes = notebook.manual_notes || "";
      els.notebookManualNotes.value = state.notebook.manualNotes;
      els.notebookSaveState.textContent = notebook.manual_updated_at
        ? "已保存"
        : "输入内容后自动保存";
    }
  } catch (error) {
    if (state.game?.id === gameId) {
      els.notebookAutoEntries.innerHTML = `<div class="notebook-empty">${escapeHtml(error.message)}</div>`;
    }
  }
}

function renderNotebookEntries() {
  els.notebookAutoEntries.innerHTML = "";
  if (!state.notebook.automatic.length) {
    els.notebookAutoEntries.innerHTML = '<div class="notebook-empty">暂无自动归档线索</div>';
    return;
  }
  state.notebook.automatic.forEach((entry) => {
    const item = document.createElement("article");
    item.className = "notebook-entry";
    item.innerHTML = `
      <span>${escapeHtml(notebookStageLabel(entry))} · ${escapeHtml(notebookSourceLabel(entry.source_type))}</span>
      <strong>${escapeHtml(entry.title)}</strong>
      <p>${escapeHtml(entry.content)}</p>`;
    els.notebookAutoEntries.appendChild(item);
  });
}

function renderOwnedClues() {
  if (!els.ownedClues) return;
  els.ownedClues.innerHTML = "";
  if (!state.notebook.clues.length) {
    els.ownedClues.innerHTML = '<div class="notebook-empty">尚未获得私有搜证线索</div>';
    return;
  }
  const canShare = state.currentPhase === "investigation";
  state.notebook.clues.forEach((clue) => {
    const item = document.createElement("article");
    item.className = `owned-clue ${clue.disclosure_mode || "private"}`;
    const status = {
      private: "仅你与 DM 知道",
      truthful: "最近一次已如实分享",
      distorted: "最近一次使用了改写说法",
    }[clue.disclosure_mode] || "仅你与 DM 知道";
    const audienceOptions = ['<option value="public">公开给所有人</option>'];
    if (state.whisper.activeTargetRoleId) {
      audienceOptions.push(
        `<option value="private:${escapeHtml(state.whisper.activeTargetRoleId)}">私下给 ${escapeHtml(roleName(state.whisper.activeTargetRoleId))}</option>`,
      );
    }
    const previousDisclosure = clue.shared_content
      ? `<div class="clue-previous-claim"><span>已发布说法</span><p>${escapeHtml(clue.shared_content)}</p></div>`
      : "";
    item.innerHTML = `
      <header>
        <span>ACT ${String(clue.stage).padStart(2, "0")} · ${escapeHtml(clue.target_name)}</span>
        <b>${escapeHtml(status)}</b>
      </header>
      <p class="clue-truth">${escapeHtml(clue.truth_content)}</p>
      ${previousDisclosure}
      <label class="clue-audience">
        <span>分享范围</span>
        <select aria-label="选择线索分享范围">${audienceOptions.join("")}</select>
      </label>
      <div class="clue-share-actions">
        <button type="button" data-clue-action="truthful" ${canShare ? "" : "disabled"}>如实分享</button>
        <button type="button" data-clue-action="distort" ${canShare ? "" : "disabled"}>改写后分享</button>
      </div>
      <div class="clue-distort-editor hidden">
        <textarea maxlength="300" placeholder="输入你准备让其他角色相信的说法..."></textarea>
        <div>
          <button type="button" data-clue-action="publish-distorted">发布说法</button>
          <button class="icon-button" type="button" data-clue-action="cancel-distorted" title="取消改写" aria-label="取消改写">×</button>
        </div>
      </div>`;
    item.querySelector('[data-clue-action="truthful"]').addEventListener(
      "click",
      () => shareOwnedClue(clue, "truthful", item),
    );
    item.querySelector('[data-clue-action="distort"]').addEventListener("click", () => {
      item.querySelector(".clue-distort-editor").classList.remove("hidden");
      item.querySelector(".clue-distort-editor textarea").focus();
    });
    item.querySelector('[data-clue-action="cancel-distorted"]').addEventListener("click", () => {
      item.querySelector(".clue-distort-editor").classList.add("hidden");
    });
    item.querySelector('[data-clue-action="publish-distorted"]').addEventListener(
      "click",
      () => shareOwnedClue(clue, "distorted", item),
    );
    els.ownedClues.appendChild(item);
  });
}

function shareOwnedClue(clue, mode, item) {
  const audience = item.querySelector(".clue-audience select").value;
  const [scope, targetRoleId] = audience.split(":");
  const content = mode === "distorted"
    ? item.querySelector(".clue-distort-editor textarea").value.trim()
    : "";
  if (mode === "distorted" && content.length < 2) {
    toast("先写下至少 2 个字符的对外说法");
    return;
  }
  sendGame({
    type: "share_clue",
    clue_id: clue.clue_id,
    mode,
    content,
    scope,
    target_role_id: targetRoleId || null,
  });
}

function notebookSourceLabel(sourceType) {
  return {
    story_background: "案件背景",
    public_briefing: "DM 公开通报",
    public_tasks: "DM 公开任务",
    public_information: "DM 公开信息",
    dm_hosting: "DM 主持归档",
    dm_narration: "DM 公布",
    role_script: "角色剧本",
    personal_task: "个人任务",
    search: "现场搜证",
    clue_claim: "线索声明",
    clue_disclosure: "线索披露",
    public_conversation: "公开交流",
    private_conversation: "私下交流",
    agent_hypothesis: "推理结论",
    manual: "玩家手记",
    public_speech: "公开发言",
    public_response: "公开回应",
    autonomous_public_speech: "主动公开询问",
    autonomous_public_response: "主动公开回应",
    private_speech: "私聊发言",
    private_response: "私聊回应",
    autonomous_private_speech: "主动私聊",
    autonomous_private_response: "主动私聊回应",
    whisper_accepted: "接受私聊",
    whisper_declined: "拒绝私聊",
    whisper_closed: "结束私聊",
    stage_resolution: "阶段结算",
    stage_vote: "阶段投票",
    final_vote: "最终指认",
  }[sourceType] || sourceType;
}

function queueManualNotebookSave() {
  const gameId = state.game?.id;
  if (!gameId) return;
  const content = els.notebookManualNotes.value;
  state.notebook.manualNotes = content;
  state.notebook.dirty = true;
  els.notebookSaveState.textContent = "等待保存";
  if (state.notebook.saveTimer) window.clearTimeout(state.notebook.saveTimer);
  state.notebook.saveTimer = window.setTimeout(
    () => saveManualNotebook(gameId, content),
    650,
  );
}

async function saveManualNotebook(gameId, content) {
  if (!gameId) return;
  els.notebookSaveState.textContent = "保存中";
  try {
    await api(`/api/games/${gameId}/notebook/manual`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    });
    if (state.game?.id === gameId && els.notebookManualNotes.value === content) {
      state.notebook.dirty = false;
      els.notebookSaveState.textContent = "已保存";
    }
  } catch (error) {
    if (state.game?.id === gameId) {
      els.notebookSaveState.textContent = "保存失败";
      toast(error.message);
    }
  }
}

async function openRoleRecords() {
  const gameId = state.game?.id;
  if (!gameId) return;
  try {
    const records = await api(`/api/games/${gameId}/role-records`);
    state.roleRecords = records;
    els.auditRoleTabs.innerHTML = "";
    records.roles.forEach((role, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.role = "tab";
      button.innerHTML = `
        <span>${role.controller === "human" ? "PLAYER" : "AGENT"}</span>
        <strong>${escapeHtml(role.role_name)}</strong>`;
      button.addEventListener("click", () => renderRoleRecord(role.role_id));
      els.auditRoleTabs.appendChild(button);
      if (index === 0) button.classList.add("active");
    });
    if (records.roles.length) renderRoleRecord(records.roles[0].role_id);
    els.roleRecordsModal.classList.remove("hidden");
    document.body.classList.add("modal-open");
  } catch (error) {
    toast(error.message);
  }
}

function renderRoleRecord(roleId) {
  const role = state.roleRecords?.roles?.find((item) => item.role_id === roleId);
  if (!role) return;
  [...els.auditRoleTabs.children].forEach((button, index) => {
    const selected = state.roleRecords.roles[index]?.role_id === roleId;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
  });
  renderAuditClues(role.clues || []);
  renderAuditEntries(
    els.auditAutomaticEntries,
    role.automatic_notebook,
    "该角色没有自动线索记录",
  );
  renderAuditEntries(
    els.auditReasoningEntries,
    role.reasoning_notebook,
    "该角色没有留下推理记录",
  );
  renderAuditStageResults(role.stage_results || []);
  renderAgentContextAudits(role.agent_context_audits || []);
  els.auditOperations.innerHTML = "";
  if (!role.operations.length) {
    els.auditOperations.innerHTML = '<div class="audit-empty">该角色没有执行操作</div>';
  } else {
    role.operations.forEach((operation) => {
      const item = document.createElement("article");
      item.innerHTML = `
        <span>ACT ${String(operation.stage).padStart(2, "0")} · ${escapeHtml(operation.channel)}</span>
        <strong>${escapeHtml(notebookSourceLabel(operation.event_type))}</strong>
        <p>${escapeHtml(operation.summary)}</p>`;
      els.auditOperations.appendChild(item);
    });
  }
}

function renderAgentContextAudits(audits) {
  els.auditAgentContexts.innerHTML = "";
  if (!audits.length) {
    els.auditAgentContexts.innerHTML = '<div class="audit-empty">该角色没有 Agent 调用记录</div>';
    return;
  }
  audits.forEach((audit) => {
    const context = audit.context || {};
    const messages = Array.isArray(context.messages) ? context.messages : [];
    const transcript = [
      `[SYSTEM · ROLE PRIVATE]\n${context.system_prompt || ""}`,
      ...messages.map((message) => (
        `[${String(message.scope || "unknown").toUpperCase()} · ${message.source_type || "unknown"}]\n`
        + `${message.role || "user"}: ${message.content || ""}`
      )),
    ].join("\n\n");
    const item = document.createElement("article");
    item.classList.toggle("failed", audit.status !== "completed");
    item.innerHTML = `
      <span>ACT ${String(audit.stage).padStart(2, "0")} · ${escapeHtml(audit.channel)}</span>
      <strong>${escapeHtml(audit.purpose)} · ${escapeHtml({ completed: "已完成", failed: "调用失败", canceled: "已取消", running: "结果待确认" }[audit.status] || "未知状态")}</strong>
      <p>${escapeHtml(context.prompt_version || "旧版记录")} · ${context.latency_ms == null ? "耗时未记录" : `${escapeHtml(context.latency_ms)} ms`} · ${context.input_tokens == null ? "用量未返回" : `输入 ${escapeHtml(context.input_tokens)} / 输出 ${escapeHtml(context.output_tokens ?? "未知")} tokens`}${audit.gameplay_committed === false ? " · 游戏结果未提交" : ""}</p>
      <details>
        <summary>${context.input_prepared === false ? "查看输入准备记录" : "查看实际输入"} · ${messages.length + 1} 段</summary>
        <pre>${escapeHtml(transcript)}</pre>
      </details>
      ${audit.error ? `<p>${escapeHtml(audit.error)}</p>` : ""}`;
    els.auditAgentContexts.appendChild(item);
  });
}

function renderAuditStageResults(stageResults) {
  els.auditStageResults.innerHTML = "";
  if (!stageResults.length) return;
  stageResults.forEach((stageResult) => {
    const result = stageResult.result;
    if (!result) return;
    const metric = stageResult.metric || { label: "阶段成果", unit: "" };
    const vote = stageResult.vote;
    const item = document.createElement("article");
    item.innerHTML = `
      <span>ACT ${String(stageResult.stage).padStart(2, "0")} · STAGE SETTLEMENT</span>
      <strong>${escapeHtml(stageResult.title)}</strong>
      <p>本幕 ${Number(result.delta) >= 0 ? "+" : ""}${escapeHtml(result.delta)} ${escapeHtml(metric.unit)}，累计${escapeHtml(metric.label)} ${escapeHtml(result.total)} ${escapeHtml(metric.unit)}。${
        vote?.outcome_text ? `\n${escapeHtml(vote.outcome_text)}` : ""
      }</p>${taskResultMarkup(result.task_results)}`;
    els.auditStageResults.appendChild(item);
  });
}

function taskResultMarkup(tasks) {
  const labels = { completed: "已完成", failed: "未完成", manual_review: "需人工评审" };
  if (!Array.isArray(tasks) || !tasks.length) return "";
  return `<ul class="task-results">${tasks.map((task) => `<li>
    <span>${escapeHtml(task.label)}</span><strong>${escapeHtml(labels[task.status] || "待判定")}</strong>
    ${task.description ? `<p>${escapeHtml(task.description)}</p>` : ""}
    ${task.minimum ? `<small>${escapeHtml(task.count)} / ${escapeHtml(task.minimum)}</small>` : ""}
  </li>`).join("")}</ul>`;
}

function renderAuditClues(clues) {
  els.auditClues.innerHTML = "";
  if (!clues.length) {
    els.auditClues.innerHTML = '<div class="audit-empty">该角色没有取得搜证线索</div>';
    return;
  }
  clues.forEach((clue) => {
    const modeLabel = {
      private: "全程保密",
      truthful: "如实披露",
      distorted: "扭曲披露",
    }[clue.disclosure_mode] || "全程保密";
    const audience = clue.shared_scope === "public"
      ? "公开给所有角色"
      : (
        clue.target_role_id
          ? `私下给 ${roleName(clue.target_role_id)}`
          : "未对外分享"
      );
    const claim = clue.shared_content
      ? `<div class="audit-claim"><span>对外说法</span><p>${escapeHtml(clue.shared_content)}</p></div>`
      : '<div class="audit-claim muted"><span>对外说法</span><p>未分享</p></div>';
    const item = document.createElement("article");
    item.className = `audit-clue ${clue.disclosure_mode || "private"}`;
    item.innerHTML = `
      <span>ACT ${String(clue.stage).padStart(2, "0")} · ${escapeHtml(clue.target_name)}</span>
      <strong>${escapeHtml(modeLabel)} · ${escapeHtml(audience)}</strong>
      <div class="audit-truth"><span>DM 原始线索</span><p>${escapeHtml(clue.truth_content)}</p></div>
      ${claim}`;
    els.auditClues.appendChild(item);
  });
}

function renderAuditEntries(container, entries, emptyText) {
  container.innerHTML = "";
  if (!entries?.length) {
    container.innerHTML = `<div class="audit-empty">${escapeHtml(emptyText)}</div>`;
    return;
  }
  entries.forEach((entry) => {
    const item = document.createElement("article");
    item.innerHTML = `
      <span>${escapeHtml(notebookStageLabel(entry))} · ${escapeHtml(notebookSourceLabel(entry.source_type))}</span>
      <strong>${escapeHtml(entry.title)}</strong>
      <p>${escapeHtml(entry.content)}</p>`;
    container.appendChild(item);
  });
}

function notebookStageLabel(entry) {
  if (!Number.isInteger(entry.stage) || entry.stage < 1) return "幕次未记录";
  return `ACT ${String(entry.stage).padStart(2, "0")}${entry.phase === "replay" ? " · 终局修订" : ""}`;
}

function closeRoleRecords() {
  if (!els.roleRecordsModal) return;
  els.roleRecordsModal.classList.add("hidden");
  document.body.classList.remove("modal-open");
}

function restoreEvents(events) {
  events.forEach((event) => {
    const payload = event.payload || {};
    if (event.type === "human_speech_echo") {
      addMessage(
        "user",
        "你",
        payload.content,
        {
          roleId: payload.role_id || state.game?.player_role_id,
          action: "public",
          isHuman: true,
        },
      );
    }
    if (event.type === "ai_speech") {
      addMessage(
        "agent",
        roleName(payload.role_id),
        payload.content,
        { roleId: payload.role_id, action: "public" },
      );
    }
    if (event.type === "ai_proactive_speech") {
      addMessage(
        "agent proactive",
        `${payload.role_name || payload.role_id} · 主动询问 ${payload.target_role_name || payload.target_role_id}`,
        payload.content,
        { roleId: payload.role_id, action: "public" },
      );
    }
    if (event.type === "agent_private_exchange") {
      addMessage("dm ambient", "DM 动态", payload.summary);
    }
    if (event.type === "search_result" && payload.clue) {
      addMessage(
        "search",
        `搜证 · ${payload.actor_role_name || roleName(payload.actor_role_id || state.game?.player_role_id)}`,
        payload.clue.content,
        {
          roleId: payload.actor_role_id || state.game?.player_role_id,
          action: "search",
          isHuman: true,
        },
      );
    }
    if (event.type === "whisper_accepted") addMessage("dm", "DM 私聊", `${payload.target_role_name || payload.target_role_id}接受了私聊邀请`);
    if (event.type === "whisper_declined") addMessage("dm", "DM 私聊", payload.message);
    if (event.type === "whisper_closed" && payload.target_role_id) addMessage("dm", "DM 私聊", `与${payload.target_role_name || payload.target_role_id}的私聊已结束`);
    if (event.type === "whisper_message") {
      addMessage(
        `${payload.sender_type === "player" ? "user" : "agent"} private`,
        `${payload.sender_type === "player" ? "你" : payload.sender_role_name || payload.sender_role_id} · 私聊`,
        payload.content,
        {
          roleId: payload.sender_role_id,
          action: "private",
          isHuman: payload.sender_type === "player",
        },
      );
    }
    if (event.type === "stage_advance") addMessage("dm", "DM Agent", `已进入阶段 ${payload.stage}`);
    if (event.type === "replay") addMessage("dm", "终局复盘", payload.full_story);
  });
}

function addMessage(type, speaker, content, options = {}) {
  if (!content) return null;
  const item = document.createElement("article");
  item.className = `message ${type}`;
  const roleId = options.roleId || "dm";
  item.innerHTML = `
    <div class="message-avatar-wrap">
      ${roleAvatarMarkup(roleId, options.avatarLabel || speaker, {
        isHuman: Boolean(options.isHuman),
        action: options.action || (type.includes("private") ? "private" : ""),
      })}
    </div>
    <div class="message-body">
      <span class="speaker">${escapeHtml(speaker)}</span>
      <div class="content">${escapeHtml(content)}</div>
    </div>`;
  els.messages.appendChild(item);
  els.messages.scrollTop = els.messages.scrollHeight;
  return item;
}

function showAgentActivity(message) {
  clearAgentActivity();
  setAvatarAction(
    [message.actor_role_id, message.target_role_id],
    message.channel === "private" ? "private" : "public",
  );
  if (!message.target_role_id) {
    state.agentActivityNode = addMessage(
      "agent activity",
      "角色正在自主行动",
      `${message.actor_role_name || roleName(message.actor_role_id)}正在评估线索并选择交流对象...`,
      {
        roleId: message.actor_role_id,
        avatarLabel: message.actor_role_name,
        action: "public",
      },
    );
    return;
  }
  const channel = message.channel === "private" ? "私下接触" : "公开询问";
  state.agentActivityNode = addMessage(
    "agent activity",
    "角色正在自主行动",
    `${message.actor_role_name || roleName(message.actor_role_id)}正在${channel}${
      message.target_role_name || roleName(message.target_role_id)
    }...`,
    {
      roleId: message.actor_role_id,
      avatarLabel: message.actor_role_name,
      action: message.channel === "private" ? "private" : "public",
    },
  );
}

function clearAgentActivity() {
  if (state.agentActivityNode?.isConnected) state.agentActivityNode.remove();
  state.agentActivityNode = null;
}

function roleName(roleId) {
  return state.game?.publicRoles?.find((role) => role.role_id === roleId)?.role_name || roleId;
}

function roleAvatarMarkup(roleId, label, options = {}) {
  const normalizedRoleId = String(roleId || "dm");
  const normalizedLabel = String(label || roleName(normalizedRoleId) || "DM");
  const knownRoleName = state.game?.publicRoles?.find(
    (role) => role.role_id === normalizedRoleId,
  )?.role_name;
  const identityLabel = knownRoleName
    || normalizedLabel.split("·", 1)[0].trim()
    || normalizedLabel;
  const initial = normalizedRoleId === "dm"
    ? "DM"
    : [...identityLabel.replace(/\s/g, "")].slice(-1).join("") || "?";
  const tone = avatarTone(normalizedRoleId);
  const classes = [
    "role-avatar",
    `avatar-tone-${tone}`,
    options.size === "small" ? "role-avatar-small" : "",
    options.isHuman ? "role-avatar-human" : "",
    options.action ? `avatar-${options.action}` : "",
    options.session ? "avatar-private-session" : "",
  ].filter(Boolean).join(" ");
  return `
    <span class="${classes}" data-role-avatar="${escapeHtml(normalizedRoleId)}"${options.live ? ' data-avatar-live="true"' : ""} title="${escapeHtml(normalizedLabel)}">
      <i aria-hidden="true"></i><b>${escapeHtml(initial)}</b><em aria-hidden="true"></em>
    </span>`;
}

function avatarTone(roleId) {
  let hash = 0;
  for (const character of String(roleId || "")) {
    hash = ((hash << 5) - hash + character.codePointAt(0)) | 0;
  }
  return Math.abs(hash) % 5;
}

function setAvatarAction(roleIds, action, duration = 1450) {
  const ids = new Set(roleIds.filter(Boolean).map(String));
  if (!ids.size) return;
  document.querySelectorAll('[data-role-avatar][data-avatar-live="true"]').forEach((avatar) => {
    if (!ids.has(avatar.dataset.roleAvatar)) return;
    const previousTimer = avatarActionTimers.get(avatar);
    if (previousTimer) window.clearTimeout(previousTimer);
    avatar.classList.remove("avatar-public", "avatar-private", "avatar-search");
    void avatar.offsetWidth;
    avatar.classList.add(`avatar-${action}`);
    const timer = window.setTimeout(() => {
      if (avatar.isConnected) avatar.classList.remove(`avatar-${action}`);
      avatarActionTimers.delete(avatar);
    }, duration);
    avatarActionTimers.set(avatar, timer);
  });
}

function refreshRoleAvatars() {
  document.querySelectorAll("[data-role-avatar]").forEach((avatar) => {
    const roleId = avatar.dataset.roleAvatar;
    if (!roleId || roleId === "dm") return;
    const name = roleName(roleId);
    if (!name || name === roleId) return;
    const initial = [...name.replace(/\s/g, "")].slice(-1).join("");
    const label = avatar.querySelector("b");
    if (label && initial) label.textContent = initial;
    avatar.title = name;
  });
}

function renderConversationParticipants(targetRoleId) {
  if (!els.conversationParticipants) return;
  if (!targetRoleId) {
    els.conversationParticipants.classList.add("hidden");
    els.conversationParticipants.innerHTML = "";
    return;
  }
  const humanRoleId = state.game?.player_role_id;
  els.conversationParticipants.innerHTML = `
    ${roleAvatarMarkup(humanRoleId, roleName(humanRoleId), {
      isHuman: true,
      size: "small",
      session: true,
      live: true,
    })}
    <span><i></i><b>PRIVATE</b><i></i></span>
    ${roleAvatarMarkup(targetRoleId, roleName(targetRoleId), {
      size: "small",
      session: true,
      live: true,
    })}`;
  els.conversationParticipants.classList.remove("hidden");
}

function sendGame(payload) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
    toast("游戏连接尚未就绪");
    return false;
  }
  const command = buildCommandEnvelope(Number(state.game.id), payload);
  try {
    commandOutbox.retain(command, commandContext());
    state.ws.send(JSON.stringify(command));
  } catch (error) {
    toast(error.message || "操作尚未发送，请稍后重试");
    return false;
  }
  return true;
}

function commandContext() {
  return { gameId: Number(state.game.id), stage: Number(state.phaseSummary?.stage || 1), phase: state.currentPhase };
}

function closeGameSocket() {
  commandOutbox.clear();
  if (state.reconnectTimer) window.clearTimeout(state.reconnectTimer);
  state.reconnectTimer = null;
  state.reconnectAttempts = 0;
  if (state.ws) {
    state.expectedSocketClosures.add(state.ws);
    state.ws.close();
  }
  state.ws = null;
  stopCountdown();
  clearAgentActivity();
  setComposerBusy(false);
}

function setComposerBusy(busy) {
  state.waitingForAgent = busy;
  const actionEnabled = state.currentPhase === "investigation"
    && (
      state.whisper.channel === "private"
        ? state.enabledActions.includes("whisper") && Boolean(state.whisper.activeTargetRoleId)
        : state.enabledActions.includes("public_speech")
    );
  els.speechInput.disabled = busy || !actionEnabled;
  els.speechSubmitBtn.disabled = busy || !actionEnabled;
  els.speechSubmitBtn.textContent = busy ? "整理中" : "发送";
  if (busy) {
    els.speechInput.placeholder = "角色正在整理证词...";
  } else if (!actionEnabled) {
    els.speechInput.placeholder = state.currentPhase === "investigation"
      ? "本幕未开放当前询问方式"
      : "等待 DM 开放调查";
  } else {
    setChannel(state.whisper.channel);
  }
}

let toastTimer;
function toast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => els.toast.classList.remove("show"), 2600);
}

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = String(value ?? "");
  return node.innerHTML;
}

function animateView(element) {
  element.classList.remove("view-enter");
  requestAnimationFrame(() => element.classList.add("view-enter"));
  window.setTimeout(() => element.classList.remove("view-enter"), 500);
}

const glassInteractiveSelector = [
  "button",
  ".role-option",
  ".upload-zone",
].join(",");

document.addEventListener("pointerdown", (event) => {
  const target = event.target.closest(glassInteractiveSelector);
  if (!target || target.matches(":disabled")) return;

  const rect = target.getBoundingClientRect();
  const x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 100;
  const y = ((event.clientY - rect.top) / Math.max(rect.height, 1)) * 100;
  target.style.setProperty("--press-x", `${x}%`);
  target.style.setProperty("--press-y", `${y}%`);
  target.classList.remove("glass-pressed");
  requestAnimationFrame(() => target.classList.add("glass-pressed"));
  window.setTimeout(() => target.classList.remove("glass-pressed"), 680);
});

appEvents.on("auth:authenticated", ({ user }) => {
  enterApp(user).catch((error) => toast(error.message || "进入调查室失败"));
});
appEvents.on("auth:logout", ({ preserveReturnPath, broadcast }) => {
  showAuth(preserveReturnPath);
  if (broadcast) authChannel?.postMessage({ type: "logout" });
});
appEvents.on("navigation:view", ({ view }) => showPage(view));
appEvents.on("sidebar:set", ({ collapsed, focusTarget }) => {
  setSidebarCollapsed(collapsed, focusTarget);
});
appEvents.on("records:open", ({ gameId }) => {
  void openGame(gameId);
});
appEvents.on("records:deleted", ({ gameId, title }) => {
  if (state.game?.id === gameId) {
    state.game = null;
    state.roleRecords = null;
    resetNotebook();
  }
  toast(`已删除案件“${title}”`);
});
appEvents.on("toast:show", ({ message }) => toast(message));
els.expandSidebarBtn.addEventListener("click", () => setSidebarCollapsed(false, true));
document.querySelectorAll(".compact-game-tab").forEach((button) => {
  button.addEventListener("click", () => setCompactGamePanel(button.dataset.panel));
  button.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...document.querySelectorAll(".compact-game-tab")];
    const current = tabs.indexOf(button);
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const next = tabs[(current + direction + tabs.length) % tabs.length];
    setCompactGamePanel(next.dataset.panel);
    next.focus();
  });
});
compactGameMedia.addEventListener("change", syncCompactGamePanel);
els.chooseFileBtn.addEventListener("click", () => els.scriptFileInput.click());
els.uploadZone.addEventListener("dblclick", () => els.scriptFileInput.click());
els.uploadZone.addEventListener("keydown", (event) => { if (event.key === "Enter") els.scriptFileInput.click(); });
els.scriptFileInput.addEventListener("change", () => readScriptFile(els.scriptFileInput.files[0]));
for (const eventName of ["dragenter", "dragover"]) els.uploadZone.addEventListener(eventName, (event) => { event.preventDefault(); els.uploadZone.classList.add("dragging"); });
for (const eventName of ["dragleave", "drop"]) els.uploadZone.addEventListener(eventName, (event) => { event.preventDefault(); els.uploadZone.classList.remove("dragging"); });
els.uploadZone.addEventListener("drop", (event) => readScriptFile(event.dataTransfer.files[0]));
els.exampleScriptBtn.addEventListener("click", async () => {
  try {
    const preview = await api("/api/scripts/example");
    state.script = null;
    state.builtinScriptId = preview.script_id;
    els.uploadTitle.textContent = "fog_harbor_clocktower.json";
    els.uploadMeta.textContent = "内置悬疑案件 · JSON";
    await inspectScript();
  } catch (error) { els.scriptError.textContent = error.message; }
});
els.startGameBtn.addEventListener("click", startGame);
els.leaveGameBtn.addEventListener("click", () => showPage("records"));
els.notebookAutoTab.addEventListener("click", () => setNotebookSection("automatic"));
els.notebookCluesTab.addEventListener("click", () => setNotebookSection("clues"));
els.notebookManualTab.addEventListener("click", () => setNotebookSection("manual"));
els.notebookManualNotes.addEventListener("input", queueManualNotebookSave);
els.closeRoleRecordsBtn.addEventListener("click", closeRoleRecords);
els.roleRecordsModal.addEventListener("click", (event) => {
  if (event.target === els.roleRecordsModal) closeRoleRecords();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !els.roleRecordsModal.classList.contains("hidden")) {
    closeRoleRecords();
  }
});
els.speechForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.waitingForAgent) return;
  const content = els.speechInput.value.trim();
  if (!content) return;
  const sent = sendGame({
    type: state.whisper.channel === "private" ? "whisper_speech" : "player_speech",
    content,
  });
  if (sent) {
    els.speechInput.value = "";
    setComposerBusy(true);
    setAvatarAction(
      [
        state.game?.player_role_id,
        state.whisper.channel === "private"
          ? state.whisper.activeTargetRoleId
          : null,
      ],
      state.whisper.channel === "private" ? "private" : "public",
    );
  }
});
els.whisperInviteBtn.addEventListener("click", () => {
  if (!els.whisperTarget.value) return;
  sendGame({ type: "whisper_invite", target_role_id: els.whisperTarget.value });
});
els.whisperCloseBtn.addEventListener("click", () => sendGame({ type: "whisper_close" }));
els.publicChannelBtn.addEventListener("click", () => setChannel("public"));
els.privateChannelBtn.addEventListener("click", () => setChannel("private"));
els.phaseContinueBtn.addEventListener("click", () => {
  if (state.currentPhase === "replay") {
    openRoleRecords();
    return;
  }
  if (state.stageResolution?.vote?.pending) {
    toast("请先完成本幕投票或最终指认");
    setPhaseContinue("完成本幕投票后继续", false);
    return;
  }
  if (sendGame({ type: "advance_phase" })) setPhaseContinue("DM 正在切换环节", false);
});
els.submitStageVoteBtn.addEventListener("click", () => {
  if (!state.selectedVoteRoleId) return;
  if (sendGame({
    type: "stage_vote",
    target_role_id: state.selectedVoteRoleId,
  })) {
    els.submitStageVoteBtn.disabled = true;
    els.submitStageVoteBtn.innerHTML = "<span>DM 正在汇总全部投票</span><b>·</b>";
  }
});
els.advanceBtn.addEventListener("click", () => {
  if (sendGame({ type: "request_phase_end" })) {
    els.advanceBtn.disabled = true;
    els.advanceBtn.textContent = "正在征询所有角色";
    els.investigationEndVoteStatus.className = "end-vote-status pending";
    els.investigationEndVoteStatus.innerHTML = "<strong>结束投票进行中</strong><p>真人已投同意票，角色 Agent 正在独立表态。</p>";
  }
});
syncCompactGamePanel();

authChannel?.addEventListener("message", (event) => {
  if (event.data?.type === "logout") showAuth(false);
});

window.addEventListener("pageshow", async (event) => {
  if (!event.persisted || !state.user) return;
  try {
    const user = await api("/api/me");
    authStore.setSession(user);
    state.csrfToken = authStore.csrfToken;
    state.user = authStore.user;
  } catch (_) {
    showAuth();
  }
});

window.addEventListener("popstate", () => {
  if (state.user) {
    restoreRoute();
  } else {
    const route = appRouter.current();
    if (route.name !== "register" && route.name !== "login") {
      showAuth(true);
    }
  }
});

(async function bootstrap() {
  localStorage.removeItem("ai_mm_token");
  try {
    const user = await api("/api/me");
    await enterApp(user);
  } catch (_) {
    showAuth();
  }
})();
}
