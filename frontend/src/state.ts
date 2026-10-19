export function createAppState() {
  return {
    authMode: "login",
    csrfToken: "",
    user: null,
    game: null,
    ws: null,
    expectedSocketClosures: new WeakSet<WebSocket>(),
    reconnectTimer: null,
    reconnectAttempts: 0,
    lastEventId: 0,
    waitingForAgent: false,
    currentPhase: "investigation",
    phaseSummary: null,
    activeMechanics: [],
    enabledActions: ["public_speech", "search", "whisper"],
    countdownTimer: null,
    countdownDeadline: null,
    agentActivityNode: null,
    notebook: {
      automatic: [],
      clues: [],
      manualNotes: "",
      activeSection: "automatic",
      saveTimer: null,
      dirty: false,
    },
    roleRecords: null,
    stageResolution: null,
    selectedVoteRoleId: null,
    sidebarCollapsed: false,
    compactPanel: "dialogue",
    whisper: {
      enabled: false,
      activeTargetRoleId: null,
      channel: "public",
    },
  };
}

export type AppState = ReturnType<typeof createAppState>;
