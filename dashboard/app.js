const $ = (selector) => document.querySelector(selector);

const agents = [
  {
    key: "TopicHunter", name: "헌터", role: "토픽 헌터",
    image: "programming-director.png",
    keywords: ["TopicHunter", "TopicGenerator", "후보", "주제"],
    lines: {
      start: "현실 하나에서 시작해 세계관을 흔들 질문을 추적하겠습니다.",
      progress: "그냥 신기한 사실은 버리고, 다음 결과가 있는 주제만 남기고 있어요.",
      done: "사람이 고를 만한 서로 다른 후보 세 개를 잡았습니다.",
    },
  },
  {
    key: "Researcher", name: "연구원", role: "과학·역사 연구원",
    image: "travel-researcher.png",
    keywords: ["ScientificResearcher", "HistoricalResearcher", "Researcher", "과학", "역사", "논문", "기록"],
    lines: {
      start: "과학 논문과 역사 기록을 동시에 조사하겠습니다.",
      progress: "검증된 근거와 아직 모르는 부분을 분리 중입니다.",
      done: "과학·역사 조사를 완료했습니다.",
    },
  },
  {
    key: "KnowledgeScriptWriter", name: "서작가", role: "다큐 작가",
    image: "story-writer.png",
    keywords: ["KnowledgeScriptWriter", "ScriptWriter", "대본"],
    lines: {
      start: "짧은 문장으로 현실에서 존재의 질문까지 가보겠습니다.",
      progress: "설명은 줄이고 증거와 질문이 번갈아 나오게 쓰고 있어요.",
      done: "60초 대본 완성. 마지막 문장은 답보다 오래 남게 했습니다.",
    },
  },
  {
    key: "ShortsAdaptationEditor", name: "컷에디터", role: "쇼츠 각색 에디터",
    image: "comedy-writer.png",
    keywords: ["ShortsAdaptationEditor", "쇼츠 각색", "각색", "쉬운 말"],
    lines: {
      start: "다른 사람 의견은 안 볼게요. 이 대본 하나만 쉬운 말로 바꿉니다.",
      progress: "설명은 짧게, 질문은 앞에. 사실은 한 줄도 버리지 않고 있어요.",
      done: "교과서 냄새를 뺐습니다. 이제 친구가 들려주는 이야기처럼 흘러갑니다.",
    },
  },
  {
    key: "VisualPromptGenerator", name: "비주얼", role: "비주얼 디렉터",
    image: "character-director.png",
    keywords: [
      "VisualPromptGenerator", "SourceResearcher", "MixedMediaPlanner",
      "비주얼", "이미지", "자료", "아카이브", "혼합", "라이선스",
    ],
    lines: {
      start: "스톡 화면보다 실제 증거가 먼저입니다.",
      progress: "기록·논문·유물을 우선 배치하고 빈 장면만 재구성하고 있어요.",
      done: "실제 자료와 AI 재구성의 경계를 장면별로 정리했습니다.",
    },
  },
  {
    key: "FactChecker", name: "팩트", role: "최종 팩트 분류",
    image: "compliance-reviewer.png",
    keywords: ["FactChecker", "팩트", "검증", "사실성"],
    lines: {
      start: "재미는 살리되 사실과 가정의 경계는 제가 긋겠습니다.",
      progress: "이 미스터리는 버릴 필요 없어요. 단정만 고치면 됩니다.",
      done: "사실·학설·추정을 분리했습니다. 중대한 문제만 아니면 제작은 계속됩니다.",
    },
  },
  {
    key: "ProductionManager", name: "한실장", role: "제작관리",
    image: "production-manager.png",
    keywords: ["ProductionManager", "ScheduleManager", "system", "사용자", "편성"],
    lines: {
      start: "좋아요. 저장된 단계는 재사용하고 필요한 담당자만 움직이겠습니다.",
      progress: "담당자 작업은 진행 중입니다. 두 연구원은 동시에 조사할 수 있어요.",
      done: "제작 패키지가 나왔습니다. 사람 승인 전에는 영상도 업로드도 진행하지 않습니다.",
    },
  },
  {
    key: "VideoRenderer", name: "나렌더", role: "영상담당",
    image: "video-studio-director.png",
    keywords: ["VideoRenderer", "VideoRevisionDirector", "영상", "장면 수정"],
    lines: {
      start: "장면 패키지를 받으면 세로 쇼츠 영상으로 조립할게요.",
      progress: "현재는 영상 렌더링 연결을 기다리고 있습니다.",
      done: "영상 렌더링 완료.",
    },
  },
  {
    key: "VoiceProducer", name: "보이스리", role: "음성담당",
    image: "video-studio-director.png",
    keywords: ["VoiceProducer", "음성", "내레이션"],
    lines: {
      start: "지식 다큐 톤으로 너무 빠르지 않게 읽겠습니다.",
      progress: "현재는 내레이션 제작 연결을 기다리고 있습니다.",
      done: "음성 제작 완료.",
    },
  },
  {
    key: "MusicProducer", name: "배경미", role: "음악담당",
    image: "video-studio-director.png",
    keywords: ["MusicProducer", "음악", "BGM"],
    lines: {
      start: "music 폴더의 세 곡 중 주제에 가장 맞는 음악을 고르겠습니다.",
      progress: "내레이션을 가리지 않도록 길이와 음량, 페이드를 맞추고 있어요.",
      done: "로컬 배경음악 선택과 믹싱을 완료했습니다.",
    },
  },
];

const stateLabels = {
  awaiting_topic_selection: "사람의 주제 선택 대기",
  production_running: "선택 주제 제작 중",
  script_revision_running: "사람 피드백 반영 중",
  video_revision_running: "완성 영상 장면 수정 중",
  selection_interrupted: "제작 중단 · 이어서 가능",
  package_ready: "사람 승인 대기",
  rendering: "MP4 영상 제작 중",
  video_ready: "영상 완성",
  video_style_outdated: "스타일 재제작 필요",
  video_failed: "영상 제작 실패",
  approved: "승인 완료",
  no_candidate: "70점 후보 없음",
  candidates_only: "후보만 생성",
  fact_check_rejected: "안전 문제 보류",
};

let currentAgent = agents.find((agent) => agent.key === "ProductionManager");
let running = false;
let currentVideoRunId = null;
const workingAgents = new Set();
const workingMessages = new Map();
let directChatRunId = "";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function buildOffice() {
  const first = $("#agentStage");
  const second = $("#videoStudioStage");
  first.innerHTML = "";
  second.innerHTML = "";
  agents.forEach((agent) => {
    const desk = document.createElement("div");
    desk.className = "agent-desk";
    desk.dataset.agent = agent.key;
    desk.innerHTML = `
      <i class="status-dot"></i>
      <img src="/assets/agents/${agent.image}" alt="${agent.name}">
      <span>${agent.name}</span>
      <b class="mini-bubble"></b>
    `;
    if (["VideoRenderer", "VoiceProducer", "MusicProducer"].includes(agent.key)) {
      second.appendChild(desk);
    } else {
      first.appendChild(desk);
    }
  });
}

function findAgent(event) {
  const exactSource = String(event.source || "").toLowerCase();
  const exactAgent = agents.find((agent) =>
    exactSource.includes(agent.key.toLowerCase())
  );
  if (exactAgent) return exactAgent;
  const text = `${event.source || ""} ${event.message || ""}`.toLowerCase();
  return agents.find((agent) =>
    agent.keywords.some((keyword) => text.includes(keyword.toLowerCase()))
  ) || currentAgent;
}

function setDialogue(agent, message) {
  currentAgent = agent;
  $("#speakerPortrait").src = `/assets/agents/${agent.image}`;
  $("#speakerName").textContent = agent.name;
  $("#speakerRole").textContent = `${agent.role} · ${agent.key}`;
  $("#speakerLine").textContent = message;
  document.querySelectorAll(".agent-desk").forEach((desk) =>
    desk.classList.remove("speaking")
  );
  const desk = document.querySelector(`[data-agent="${agent.key}"]`);
  if (desk) {
    desk.classList.add("speaking");
    desk.querySelector(".mini-bubble").textContent = message;
    setTimeout(() => desk.classList.remove("speaking"), 7000);
  }
}

function setWorking(agent, isWorking, message = "") {
  const desk = document.querySelector(`[data-agent="${agent.key}"]`);
  if (!desk) return;
  desk.classList.toggle("working", isWorking);
  desk.classList.toggle("has-work-message", isWorking && Boolean(message));
  if (isWorking) {
    workingAgents.add(agent.key);
    if (message) {
      workingMessages.set(agent.key, message);
      desk.querySelector(".mini-bubble").textContent = message;
    }
  } else {
    workingAgents.delete(agent.key);
    workingMessages.delete(agent.key);
  }
}

function addConversation(agent, message) {
  const panel = $("#characterConversation");
  panel.querySelector(".conversation-empty")?.remove();
  const card = document.createElement("article");
  card.className = "conversation-card";
  card.innerHTML = `
    <img src="/assets/agents/${agent.image}" alt="">
    <div><strong>${escapeHtml(agent.name)} · ${escapeHtml(agent.role)}</strong>
    <p>${escapeHtml(message)}</p></div>
  `;
  panel.appendChild(card);
  while (panel.children.length > 12) panel.firstChild.remove();
  panel.scrollLeft = panel.scrollWidth;
}

function addDirectTopicMessage(kind, message) {
  const panel = $("#directTopicChat");
  if (!panel || !message) return;
  const last = panel.lastElementChild;
  if (
    last &&
    last.classList.contains(kind === "user" ? "user-message" : "hunter-message") &&
    last.querySelector("p")?.textContent === String(message)
  ) {
    return;
  }
  const card = document.createElement("article");
  card.className = kind === "user" ? "user-message" : "hunter-message";
  card.innerHTML = `
    <strong>${kind === "user" ? "나" : "헌터"}</strong>
    <p>${escapeHtml(message)}</p>
  `;
  panel.appendChild(card);
  while (panel.children.length > 8) panel.firstChild.remove();
  panel.scrollTop = panel.scrollHeight;
}

function addLog(event) {
  const row = document.createElement("div");
  row.className = `log-line ${event.level || ""}`;
  const time = (event.timestamp || "").split("T")[1] || "--:--:--";
  row.innerHTML = `
    <time>${escapeHtml(time)}</time>
    <span class="log-source">${escapeHtml(event.source)}</span>
    <span class="log-message">${escapeHtml(event.message)}</span>
  `;
  $("#logStream").appendChild(row);
  if ($("#autoScroll").checked) $("#logStream").scrollTop = $("#logStream").scrollHeight;
}

function handleEvent(event) {
  const agent = findAgent(event);
  if (event.level === "agent_state") {
    setWorking(agent, event.message === "working", workingMessages.get(agent.key) || "");
    return;
  }
  if (event.level === "agent_progress") {
    let payload;
    try { payload = JSON.parse(event.message); } catch { payload = { percent: 0, message: event.message }; }
    const message = `${payload.message} (${payload.percent}%)`;
    setWorking(agent, true, message);
    setDialogue(agent, message);
    addLog({ ...event, message });
    return;
  }
  if (event.level === "character") {
    setDialogue(agent, event.message);
    addConversation(agent, event.message);
    if (String(event.source || "").startsWith("사용자 → TopicHunter")) {
      addDirectTopicMessage("user", event.message);
    } else if (agent.key === "TopicHunter") {
      addDirectTopicMessage("hunter", event.message);
    }
  } else if (event.level === "success") {
    setDialogue(agent, agent.lines.done);
  } else if (event.level === "error") {
    setDialogue(agent, `문제가 생겼습니다. ${event.message}`);
  }
  addLog(event);
  if (["success", "error"].includes(event.level)) {
    refreshStatus();
    refreshTopicLibrary($("#topicLibrarySearch")?.value.trim() || "");
  }
}

function candidateScore(candidate) {
  const score = candidate.total_score ?? candidate.score?.total ?? 0;
  return score;
}

function buildCandidateCards(run, container, state) {
  const candidates = run.candidates || [];
  candidates.forEach((candidate, index) => {
    const card = document.createElement("article");
    const selected = run.selected_candidate_index === index;
    const rejected = candidate.selection_status === "rejected";
    card.className = `candidate-card${selected ? " selected" : ""}${rejected ? " rejected" : ""}`;
    const distinction = candidate.fact_hypothesis_distinction || "";
    const difficulty = candidate.audience_difficulty || "기존";
    const difficultyLabel = {
      easy: "쉬움",
      medium: "보통",
      hard: "어려움",
    }[difficulty] || difficulty;
    card.innerHTML = `
      <strong>${index + 1}. ${escapeHtml(candidate.title)}</strong>
      <span class="candidate-score">${candidateScore(candidate)}점</span>
      <div class="candidate-meta">
        <span class="difficulty ${escapeHtml(difficulty)}">난이도 ${escapeHtml(difficultyLabel)}</span>
        ${candidate.required_background_seconds !== undefined ? `<span>배경 ${escapeHtml(candidate.required_background_seconds)}초</span>` : ""}
        ${(candidate.unfamiliar_terms || []).length ? `<span>전문용어 ${(candidate.unfamiliar_terms || []).length}개</span>` : ""}
      </div>
      <p>${escapeHtml(candidate.plain_language_summary || candidate.one_line_hook || "")}</p>
      <p>${escapeHtml(distinction)}</p>
      ${rejected ? `<p class="candidate-rejected">선정 제외: ${escapeHtml(candidate.rejection_reason || "기준 미달")}</p>` : ""}
    `;
    if (
      !rejected && (
      state === "awaiting_topic_selection" ||
      (state === "selection_interrupted" && selected)
      )
    ) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent =
        state === "selection_interrupted" ? "이 주제로 이어서 제작" : "이 주제로 제작";
      button.addEventListener("click", () =>
        selectRun(run.run_id, index, candidate.title, button)
      );
      card.appendChild(button);
    } else if (selected) {
      const selectedLabel = document.createElement("p");
      selectedLabel.textContent = "✓ 사람이 채택한 제작 주제";
      selectedLabel.style.color = "var(--green)";
      card.appendChild(selectedLabel);
    }
    container.appendChild(card);
  });
}

function renderRuns(data) {
  const list = $("#knowledgeRunList");
  const runs = data.knowledge_runs || [];
  $("#totalCount").textContent = `총 ${data.total || 0}건`;
  if (!runs.length) {
    list.innerHTML = `<div class="episode-row"><span>아직 생성된 지식 쇼츠가 없습니다.</span></div>`;
    return;
  }
  list.innerHTML = "";
  runs.slice(0, 12).forEach((run) => {
    const row = document.createElement("article");
    row.className = "episode-row knowledge-run";
    const state = run.production_status || run.state || "candidates_only";
    row.innerHTML = `
      <div>
        <code>${escapeHtml(run.run_id || run.production_date)}</code>
        <strong class="run-title">${escapeHtml(run.selected_title || run.category || "후보 평가 결과")}</strong>
        <small>${escapeHtml(run.category || "")}</small>
        ${run.background_music_title ? `<small>🎵 ${escapeHtml(run.background_music_title)}</small>` : ""}
      </div>
      <span class="state ${state}">${escapeHtml(stateLabels[state] || state)}</span>
      <div class="candidate-list"></div>
      <div class="episode-actions"></div>
    `;
    buildCandidateCards(run, row.querySelector(".candidate-list"), state);
    const actions = row.querySelector(".episode-actions");
    if (run.final_package) {
      const download = document.createElement("a");
      download.className = "package-link";
      download.href = `/api/knowledge/${run.run_id}/package`;
      download.textContent = "JSON 제작 패키지";
      download.setAttribute("download", "");
      actions.appendChild(download);
      const approve = document.createElement("button");
      approve.className = "upload";
      if (state === "package_ready" || state === "video_failed") {
        approve.textContent =
          state === "video_failed" ? "대본 확인 후 영상 재시도" : "최종 대본 검토";
        approve.addEventListener("click", () =>
          openScriptReview(run.run_id, run.selected_title)
        );
        actions.appendChild(approve);
      } else if (state === "rendering") {
        approve.textContent = "영상 제작 진행 중";
        approve.disabled = true;
        actions.appendChild(approve);
      }
    }
    if (
      state === "video_ready" ||
      state === "video_style_outdated" ||
      run.final_video
    ) {
      const play = document.createElement("button");
      play.className = "play";
      play.textContent = "▶ 완성 영상 재생";
      play.addEventListener("click", () => openVideo(run.run_id, run.selected_title));
      actions.appendChild(play);
      const rerender = document.createElement("button");
      rerender.className = "upload";
      rerender.textContent = "레퍼런스 스타일로 재제작";
      rerender.addEventListener("click", () => rerenderRun(run.run_id, rerender));
      actions.appendChild(rerender);
      const editScript = document.createElement("button");
      editScript.className = "upload";
      editScript.textContent = "시나리오 수정 후 재제작";
      editScript.addEventListener("click", () =>
        openScriptReview(run.run_id, run.selected_title)
      );
      editScript.textContent = "대본 피드백·수정";
      editScript.title = "대본과 내레이션 내용을 수정합니다. 화면 교체는 영상 플레이어의 장면 피드백을 사용하세요.";
      actions.appendChild(editScript);
    }
    list.appendChild(row);
  });
}

function renderStatus(data) {
  $("#completedCount").textContent = data.completed || 0;
  $("#runningCount").textContent = data.in_progress || 0;
  $("#waitingCount").textContent = data.waiting || 0;
  $("#blockedCount").textContent = data.blocked || 0;
  const schedule = data.schedule || {};
  $("#scheduleDate").textContent = schedule.production_date || "-";
  $("#scheduleCategory").textContent = schedule.category || "편성 없음";
  $("#scheduleReason").textContent = schedule.schedule_reason || "";
  $("#referenceStatus").textContent =
    `✓ 채널 마스터 규칙 ${data.master_reference_available ? "적용" : "미발견"} · 영상 레퍼런스 ${data.reference_video_count || 0}개 + 사고 설계 레퍼런스 ${data.concept_reference_count || 0}개`;
  running = Boolean(data.control_process?.running);
  const active = $("#activeJob");
  active.classList.toggle("idle", !running);
  active.querySelector("strong").textContent =
    data.control_process?.label || "대기 중";
  $("#officeState").textContent = running ? "제작 진행 중" : "현재 작업 없음";
  $("#officeState").className = `office-state ${running ? "working" : "idle"}`;
  const latestDirectRun = (data.knowledge_runs || []).find(
    (run) => run.discovery_mode === "direct_topic"
  );
  if (latestDirectRun && latestDirectRun.run_id !== directChatRunId) {
    directChatRunId = latestDirectRun.run_id;
    const panel = $("#directTopicChat");
    panel.innerHTML = "";
    addDirectTopicMessage("user", latestDirectRun.direct_topic_request);
    addDirectTopicMessage(
      "hunter",
      latestDirectRun.topic_hunter_reply ||
        "주제를 다듬고 있습니다. 정리가 끝나면 바로 조사와 대본 제작으로 넘기겠습니다."
    );
  }
  renderRuns(data);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "요청을 처리하지 못했습니다.");
  return data;
}

async function refreshStatus() {
  try {
    const data = await api("/api/status");
    renderStatus(data);
    $("#topicLibraryCount").textContent = `총 ${data.topic_library_count || 0}개`;
    $("#connectionBadge").textContent = "관제실 연결됨";
    $("#connectionBadge").className = "connection online";
  } catch (error) {
    $("#connectionBadge").textContent = "연결 끊김";
    $("#connectionBadge").className = "connection offline";
  }
}

function renderTopicLibrary(data) {
  const list = $("#topicLibraryList");
  $("#topicLibraryCount").textContent = `총 ${data.total || 0}개`;
  if (!data.items?.length) {
    list.innerHTML = `<p class="idea-empty">검색 조건에 맞는 소재가 없습니다.</p>`;
    return;
  }
  list.innerHTML = "";
  data.items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "topic-library-item";
    const directions = item.requested_directions || [];
    card.innerHTML = `
      <header>
        <strong>${escapeHtml(item.title)}</strong>
        <span class="topic-score">${escapeHtml(item.highest_score ?? item.total_score ?? 0)}점</span>
      </header>
      <p>${escapeHtml(item.one_line_hook || "")}</p>
      <div class="topic-library-meta">
        <span>${escapeHtml(item.category || "")}</span>
        <span>${item.discovery_mode === "automatic" ? "자동 발굴" : "지정 발굴"}</span>
        <span>발견 ${escapeHtml(item.occurrence_count || 1)}회</span>
        ${directions.map((direction) => `<span>${escapeHtml(direction)}</span>`).join("")}
        ${item.library_status === "selected" ? `<span class="selected">제작 채택됨</span>` : ""}
      </div>
    `;
    list.appendChild(card);
  });
}

async function refreshTopicLibrary(query = "") {
  try {
    const data = await api(`/api/topics?q=${encodeURIComponent(query)}&limit=100`);
    renderTopicLibrary(data);
  } catch (error) {
    $("#topicLibraryList").innerHTML =
      `<p class="idea-empty">${escapeHtml(error.message)}</p>`;
  }
}

async function refreshConversation() {
  try {
    const data = await api("/api/conversation");
    if (!data.comments?.length) return;
    $("#conversationEpisode").textContent = data.run_id;
    const panel = $("#characterConversation");
    panel.innerHTML = "";
    data.comments.forEach((comment) => {
      const agent = agents.find((item) => item.key === comment.role) || currentAgent;
      addConversation(agent, comment.comment);
    });
  } catch {}
}

async function sendCommand(command) {
  const feedback = $("#commandFeedback");
  feedback.textContent = "지시 전달 중...";
  feedback.classList.remove("error");
  try {
    const data = await api("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command }),
    });
    feedback.textContent = data.message;
    await refreshStatus();
  } catch (error) {
    feedback.textContent = error.message;
    feedback.classList.add("error");
  }
}

async function startGeneration() {
  const button = $("#generateKnowledgeButton");
  const direction = $("#topicDirection").value.trim();
  button.disabled = true;
  try {
    const data = await api("/api/knowledge/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ direction }),
    });
    $("#commandFeedback").textContent = data.message;
    setDialogue(currentAgent, "AI는 후보 세 개까지만 만듭니다. 완성되면 하나를 직접 골라주세요.");
    await refreshStatus();
  } catch (error) {
    $("#commandFeedback").textContent = error.message;
    $("#commandFeedback").classList.add("error");
  } finally {
    button.disabled = false;
  }
}

async function uploadScript() {
  const title = $("#uploadScriptTitle").value.trim();
  const narration = $("#uploadScriptNarration").value.trim();
  const button = $("#uploadScriptButton");
  const feedback = $("#uploadScriptFeedback");
  if (!title) {
    feedback.textContent = "제목을 입력해주세요.";
    feedback.classList.add("error");
    return;
  }
  if (!narration || narration.length < 10) {
    feedback.textContent = "내레이션을 10자 이상 입력해주세요.";
    feedback.classList.add("error");
    return;
  }
  button.disabled = true;
  feedback.classList.remove("error");
  feedback.textContent = "대본 업로드 중...";
  try {
    const data = await api("/api/knowledge/upload-script", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, narration }),
    });
    feedback.textContent = data.message;
    $("#uploadScriptTitle").value = "";
    $("#uploadScriptNarration").value = "";
    await refreshStatus();
  } catch (error) {
    feedback.textContent = error.message;
    feedback.classList.add("error");
  } finally {
    button.disabled = false;
  }
}

async function startDirectTopic() {
  const prompt = $("#directTopicPrompt").value.trim();
  const button = $("#directTopicButton");
  const feedback = $("#directTopicFeedback");
  if (!prompt) {
    feedback.textContent = "대략적인 주제를 먼저 입력해주세요.";
    feedback.classList.add("error");
    return;
  }
  button.disabled = true;
  feedback.classList.remove("error");
  feedback.textContent = "토픽헌터에게 전달 중...";
  addDirectTopicMessage("user", prompt);
  try {
    const data = await api("/api/knowledge/direct-topic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    feedback.textContent = data.message;
    setDialogue(
      agents.find((agent) => agent.key === "TopicHunter"),
      "좋아요. 핵심은 건드리지 않고, 바로 영상이 되는 질문으로 정리해볼게요."
    );
    await refreshStatus();
  } catch (error) {
    feedback.textContent = error.message;
    feedback.classList.add("error");
  } finally {
    button.disabled = false;
  }
}

async function selectRun(runId, candidateIndex, title, button) {
  if (!window.confirm(`‘${title}’을 제작 주제로 채택할까요?`)) return;
  document.querySelectorAll(".candidate-card button").forEach((item) => {
    item.disabled = true;
  });
  try {
    const data = await api(`/api/knowledge/${runId}/select`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate_index: candidateIndex }),
    });
    $("#commandFeedback").textContent = data.message;
    await refreshStatus();
    await refreshTopicLibrary($("#topicLibrarySearch").value.trim());
  } catch (error) {
    button.disabled = false;
    $("#commandFeedback").textContent = error.message;
    $("#commandFeedback").classList.add("error");
  }
}

async function approveRun(runId, button) {
  if (!window.confirm("승인하면 이미지·음성 API를 사용해 실제 MP4 영상 제작을 시작합니다.")) return;
  button.disabled = true;
  try {
    const data = await api(`/api/knowledge/${runId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fit_to_60_seconds: Boolean($("#fitTo60Seconds")?.checked),
      }),
    });
    $("#commandFeedback").textContent = data.message;
    $("#scriptReviewModal").hidden = true;
    await refreshStatus();
  } catch (error) {
    button.disabled = false;
    $("#commandFeedback").textContent = error.message;
  }
}

let reviewRunId = null;
let reviewData = null;

function scriptSection(label, value) {
  return `
    <article class="script-section">
      <strong>${escapeHtml(label)}</strong>
      <p>${escapeHtml(value || "내용 없음")}</p>
    </article>
  `;
}

function directScriptEditor(data) {
  const script = data.script || {};
  const timed = script.timed_script || {};
  const scenes = data.visual_scenes || [];
  return `
    <section id="directScriptEditor" class="direct-script-editor" hidden>
      <div class="direct-edit-notice">
        <strong>직접 수정 모드</strong>
        <p>영상에서는 아래 장면별 내레이션을 실제 TTS가 순서대로 읽습니다. 마지막 장면에 결론·반전·마지막 질문이 들어 있는지 확인해주세요.</p>
      </div>
      <label>
        영상 제목
        <input id="manualScriptTitle" value="${escapeHtml(script.title || data.title || "")}">
      </label>
      <label>
        도입 후킹
        <textarea id="manualHook" rows="2">${escapeHtml(timed.hook_0_3 || "")}</textarea>
      </label>
      <label>
        배경 설명
        <textarea id="manualBackground" rows="3">${escapeHtml(timed.background_3_12 || "")}</textarea>
      </label>
      <label>
        핵심 사실 2~3개 <small>한 줄에 하나씩 입력</small>
        <textarea id="manualFacts" rows="5">${escapeHtml((timed.facts_12_35 || []).join("\n"))}</textarea>
      </label>
      <label>
        미스터리·반전
        <textarea id="manualMystery" rows="3">${escapeHtml(timed.mystery_35_50 || "")}</textarea>
      </label>
      <label>
        결론·마지막 질문
        <textarea id="manualClose" rows="3">${escapeHtml(timed.close_50_60 || "")}</textarea>
      </label>
      <div class="manual-scene-list">
        <div class="manual-scene-heading">
          <strong>실제 영상 장면별 TTS 대사</strong>
          <span>${scenes.length}개 장면</span>
        </div>
        ${scenes.map((scene) => `
          <article class="manual-scene" data-scene-number="${scene.scene_number}">
            <header>
              <strong>${scene.scene_number}번 장면</strong>
              <input class="manual-time-range" value="${escapeHtml(scene.time_range || "")}" aria-label="${scene.scene_number}번 장면 시간">
            </header>
            <label>
              화면 자막
              <textarea class="manual-subtitle" rows="2">${escapeHtml(scene.subtitle || "")}</textarea>
            </label>
            <label>
              내레이션
              <textarea class="manual-narration" rows="4">${escapeHtml(scene.narration || "")}</textarea>
            </label>
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

async function openScriptReview(runId, title) {
  reviewRunId = runId;
  reviewData = null;
  const modal = $("#scriptReviewModal");
  const feedbackButton = $("#submitScriptFeedback");
  const approveButton = $("#approveReviewedScript");
  const editButton = $("#toggleDirectScriptEdit");
  const saveButton = $("#saveDirectScriptEdit");
  feedbackButton.disabled = false;
  feedbackButton.textContent = "피드백 반영 요청";
  approveButton.disabled = false;
  $("#fitTo60Seconds").checked = false;
  editButton.disabled = false;
  editButton.textContent = "직접 수정하기";
  saveButton.hidden = true;
  saveButton.disabled = false;
  $("#scriptReviewTitle").textContent = title || "최종 대본 검토";
  $("#scriptReviewBody").innerHTML = `<p class="review-loading">대본을 불러오고 있습니다.</p>`;
  $("#scriptFeedback").value = "";
  $("#scriptReviewFeedback").textContent = "";
  modal.hidden = false;
  try {
    const data = await api(`/api/knowledge/${runId}/review`);
    reviewData = data;
    $("#fitTo60Seconds").checked = Boolean(
      data?.human_approval?.render_options?.fit_to_60_seconds
    );
    const script = data.script || {};
    const timed = script.timed_script || {};
    const audience = data.audience_simulation || {};
    const fact = data.fact_check || {};
    const adaptation = data.shorts_adaptation || {};
    const factLabels = script.fact_hypothesis_labels || [];
    const patterns = script.reference_patterns_used || [];
    const feedbacks = data.feedback_history || [];
    const videoVersions = data.video_versions || [];
    const feedbackHistory = feedbacks.length
      ? `
        <details class="script-review-details feedback-history">
          <summary>이전 피드백과 반영 기록 ${feedbacks.length}개</summary>
          ${feedbacks.map((item) => `
            <article>
              <strong>${escapeHtml(item.feedback_number || "-")}차 피드백 · ${escapeHtml(item.status || "확인 중")}</strong>
              <p>${escapeHtml(item.feedback || "")}</p>
              ${item.writer_report ? `<p><b>작가 반영 보고:</b> ${escapeHtml(item.writer_report)}</p>` : ""}
              ${item.after_hook ? `<p><b>수정된 첫 문장:</b> ${escapeHtml(item.after_hook)}</p>` : ""}
            </article>
          `).join("")}
        </details>
      `
      : "";
    $("#scriptReviewBody").innerHTML = `
      <div class="script-score-row">
        ${videoVersions.length ? `<span>이전 영상 ${videoVersions.length}개 보관</span>` : ""}
        <span>예상 유지율 ${escapeHtml(audience.predicted_retention_score ?? "-")}점</span>
        <span>댓글 반응 ${escapeHtml(audience.predicted_comment_score ?? "-")}점</span>
        <span>팩트 검수 ${escapeHtml(fact.verdict || "-")}</span>
        <span>${adaptation.adapted_script ? "쇼츠 각색 완료" : "직접 편집본"}</span>
        <span>수정 ${feedbacks.length}회</span>
      </div>
      <div class="script-timeline">
        ${scriptSection("0~3초 · 후킹", timed.hook_0_3)}
        ${scriptSection("3~12초 · 배경", timed.background_3_12)}
        ${scriptSection("12~35초 · 핵심 사실", (timed.facts_12_35 || []).join(" "))}
        ${scriptSection("35~50초 · 미스터리/반전", timed.mystery_35_50)}
        ${scriptSection("50~60초 · 결말", timed.close_50_60)}
      </div>
      <section class="full-narration">
        <strong>실제 TTS가 읽을 최종 내레이션</strong>
        <p>${escapeHtml(script.full_narration || "")}</p>
      </section>
      <details class="script-review-details">
        <summary>사실성 표시와 적용 레퍼런스 확인</summary>
        <p><b>사실성:</b> ${escapeHtml(factLabels.join(" · ") || "없음")}</p>
        <p><b>사고 패턴:</b> ${escapeHtml(patterns.join(" · ") || "기록 없음")}</p>
        <p><b>시청자 평가:</b> ${escapeHtml(audience.reference_pattern_assessment || audience.character_comment || "")}</p>
      </details>
      ${adaptation.character_comment ? `
        <details class="script-review-details">
          <summary>컷에디터 각색 보고</summary>
          <p>${escapeHtml(adaptation.character_comment)}</p>
          <p><b>독립 작업:</b> 검색 없음 · 다른 AI 의견 없음 · 기존 사실 유지</p>
        </details>
      ` : ""}
      ${feedbackHistory}
      ${directScriptEditor(data)}
    `;
  } catch (error) {
    $("#scriptReviewBody").innerHTML =
      `<p class="review-error">${escapeHtml(error.message)}</p>`;
  }
}

function toggleDirectScriptEdit() {
  const editor = $("#directScriptEditor");
  if (!editor) return;
  const opening = editor.hidden;
  editor.hidden = !opening;
  $("#saveDirectScriptEdit").hidden = !opening;
  $("#toggleDirectScriptEdit").textContent =
    opening ? "직접 수정 닫기" : "직접 수정하기";
  if (opening) editor.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function saveDirectScriptEdit() {
  if (!reviewRunId || !reviewData) return;
  const editor = $("#directScriptEditor");
  if (!editor) return;
  const facts = $("#manualFacts").value
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
  const scenes = [...editor.querySelectorAll(".manual-scene")].map((scene) => ({
    scene_number: Number(scene.dataset.sceneNumber),
    time_range: scene.querySelector(".manual-time-range").value.trim(),
    subtitle: scene.querySelector(".manual-subtitle").value.trim(),
    narration: scene.querySelector(".manual-narration").value.trim(),
  }));
  const payload = {
    title: $("#manualScriptTitle").value.trim(),
    hook_0_3: $("#manualHook").value.trim(),
    background_3_12: $("#manualBackground").value.trim(),
    facts_12_35: facts,
    mystery_35_50: $("#manualMystery").value.trim(),
    close_50_60: $("#manualClose").value.trim(),
    scenes,
  };
  if (!payload.title || !payload.hook_0_3 || !payload.close_50_60) {
    $("#scriptReviewFeedback").textContent =
      "제목, 도입 후킹, 결론은 비워둘 수 없습니다.";
    return;
  }
  if (facts.length < 2 || facts.length > 3) {
    $("#scriptReviewFeedback").textContent =
      "핵심 사실은 줄바꿈으로 구분해 2~3개를 입력해주세요.";
    return;
  }
  if (scenes.some((scene) => !scene.narration)) {
    $("#scriptReviewFeedback").textContent =
      "모든 장면의 내레이션을 입력해주세요.";
    return;
  }
  if (!window.confirm("직접 수정한 시나리오를 저장할까요? 기존 완성 영상은 버전 보관함에 남고, 승인 후 새 영상으로 다시 제작됩니다.")) return;

  const button = $("#saveDirectScriptEdit");
  button.disabled = true;
  button.textContent = "수정본 저장 중...";
  try {
    const data = await api(`/api/knowledge/${reviewRunId}/manual-script`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("#scriptReviewFeedback").textContent = data.message;
    await refreshStatus();
    await openScriptReview(reviewRunId, payload.title);
    $("#scriptReviewFeedback").textContent =
      "직접 수정본을 저장했습니다. 내용을 다시 확인하고 승인하면 새 영상을 제작합니다.";
  } catch (error) {
    $("#scriptReviewFeedback").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "수정본 저장";
  }
}

async function submitScriptFeedback() {
  if (!reviewRunId) return;
  const feedback = $("#scriptFeedback").value.trim();
  if (!feedback) {
    $("#scriptReviewFeedback").textContent = "수정할 내용을 입력해주세요.";
    return;
  }
  if (!window.confirm("피드백을 작가 AI에게 전달하면 대본과 검수·장면 설계를 다시 생성합니다.")) return;
  const button = $("#submitScriptFeedback");
  button.disabled = true;
  button.textContent = "피드백 전달 중...";
  try {
    const data = await api(`/api/knowledge/${reviewRunId}/script-feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feedback }),
    });
    $("#scriptReviewFeedback").textContent = data.message;
    $("#scriptReviewModal").hidden = true;
    await refreshStatus();
  } catch (error) {
    $("#scriptReviewFeedback").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "피드백 반영 요청";
  }
}

async function rerenderRun(runId, button) {
  if (!window.confirm("기존 이미지 자료는 유지하고 자막·화면 연출·내레이션을 새 스타일로 다시 제작합니다.")) return;
  button.disabled = true;
  try {
    const data = await api(`/api/knowledge/${runId}/rerender`, { method: "POST" });
    $("#commandFeedback").textContent = data.message;
    await refreshStatus();
  } catch (error) {
    button.disabled = false;
    $("#commandFeedback").textContent = error.message;
    $("#commandFeedback").classList.add("error");
  }
}

function openVideo(runId, title) {
  currentVideoRunId = runId;
  const modal = $("#videoModal");
  const video = $("#knowledgeVideo");
  $("#videoModalTitle").textContent = title || "완성된 지식 쇼츠";
  video.src = `/api/knowledge/${runId}/video?v=${Date.now()}`;
  $("#videoSceneFeedback").value = "";
  $("#videoFeedbackMessage").textContent = "";
  $("#videoSceneGuide").textContent = "장면 목록을 불러오는 중...";
  api(`/api/knowledge/${runId}/review`)
    .then((data) => {
      const scenes = data.visual_scenes || [];
      $("#videoSceneGuide").innerHTML = scenes
        .map((scene) => `<span title="${escapeHtml(scene.subtitle || "")}">${scene.scene_number}번 · ${escapeHtml(scene.subtitle || "화면")}</span>`)
        .join("");
    })
    .catch(() => {
      $("#videoSceneGuide").textContent = "장면 목록을 불러오지 못했습니다.";
    });
  modal.hidden = false;
  video.play().catch(() => {});
}

async function submitVideoFeedback() {
  if (!currentVideoRunId) return;
  const feedback = $("#videoSceneFeedback").value.trim();
  if (!feedback) {
    $("#videoFeedbackMessage").textContent = "장면 번호와 수정 내용을 입력해주세요.";
    return;
  }
  if (!window.confirm("현재 영상을 보관하고 지목한 장면만 교체해 다시 제작할까요?")) return;
  const button = $("#submitVideoFeedback");
  button.disabled = true;
  button.textContent = "영상감독에게 전달 중...";
  try {
    const data = await api(`/api/knowledge/${currentVideoRunId}/video-feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feedback }),
    });
    $("#videoFeedbackMessage").textContent = data.message;
    $("#knowledgeVideo").pause();
    $("#videoModal").hidden = true;
    await refreshStatus();
  } catch (error) {
    $("#videoFeedbackMessage").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "장면 수정 후 다시 제작";
  }
}

function connectEvents() {
  const source = new EventSource("/api/events");
  source.onmessage = (message) => handleEvent(JSON.parse(message.data));
  source.onerror = () => {
    $("#connectionBadge").textContent = "재연결 중";
    $("#connectionBadge").className = "connection pending";
  };
  source.onopen = () => {
    $("#connectionBadge").textContent = "관제실 연결됨";
    $("#connectionBadge").className = "connection online";
  };
}

buildOffice();
$("#refreshButton").addEventListener("click", () => {
  refreshStatus();
  refreshConversation();
});
$("#generateKnowledgeButton").addEventListener("click", startGeneration);
$("#uploadScriptButton").addEventListener("click", uploadScript);
$("#uploadScriptNarration").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    uploadScript();
  }
});
$("#directTopicButton").addEventListener("click", startDirectTopic);
$("#directTopicPrompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    startDirectTopic();
  }
});
$("#topicLibrarySearchButton").addEventListener("click", () =>
  refreshTopicLibrary($("#topicLibrarySearch").value.trim())
);
$("#topicLibrarySearch").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    refreshTopicLibrary(event.target.value.trim());
  }
});
$("#sendCommand").addEventListener("click", () => {
  const command = $("#managerCommand").value.trim();
  if (command) sendCommand(command);
});
$("#managerCommand").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("#sendCommand").click();
  }
});
document.querySelectorAll("[data-command]").forEach((button) =>
  button.addEventListener("click", () => sendCommand(button.dataset.command))
);
$("#clearLog").addEventListener("click", async () => {
  $("#logStream").innerHTML = "";
  await api("/api/logs/clear", { method: "POST" });
});
$("#closeVideoModal").addEventListener("click", () => {
  const video = $("#knowledgeVideo");
  video.pause();
  video.removeAttribute("src");
  video.load();
  $("#videoModal").hidden = true;
  currentVideoRunId = null;
});
$("#submitVideoFeedback").addEventListener("click", submitVideoFeedback);
$("#closeScriptReview").addEventListener("click", () => {
  $("#submitScriptFeedback").disabled = false;
  $("#submitScriptFeedback").textContent = "피드백 반영 요청";
  $("#saveDirectScriptEdit").hidden = true;
  $("#toggleDirectScriptEdit").textContent = "직접 수정하기";
  $("#scriptReviewModal").hidden = true;
});
$("#toggleDirectScriptEdit").addEventListener("click", toggleDirectScriptEdit);
$("#saveDirectScriptEdit").addEventListener("click", saveDirectScriptEdit);
$("#submitScriptFeedback").addEventListener("click", submitScriptFeedback);
$("#approveReviewedScript").addEventListener("click", (event) => {
  if (!reviewRunId) return;
  approveRun(reviewRunId, event.currentTarget);
});

Promise.all([
  refreshStatus(),
  refreshTopicLibrary(),
  refreshConversation(),
  api("/api/events/recent").then((data) => data.events.forEach(addLog)).catch(() => {}),
]).finally(connectEvents);
setInterval(refreshStatus, 5000);
setInterval(refreshConversation, 15000);
