<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { cursorPosition, getCurrentWindow } from "@tauri-apps/api/window";

type Message = { role: "user" | "assistant"; text: string };
type AgentEvent = { name: string; state: string; detail: string };
type PendingConfirmation = { id: string; name: string; args: Record<string, unknown> };
type MemoryState = { shortTerm: number; shortLimit: number; longTerm: number; taskCount: number; facts: { id: number; fact: string }[]; tasks: { id: number; title: string; note: string }[]; history: { role: "user" | "assistant"; content: string }[][]; provider: string; model: string };

const open = ref(false);
const panel = ref<"chat" | "memory">("chat");
const busy = ref(false);
const state = ref("待命");
const voiceState = ref<"idle" | "preparing" | "starting" | "recording" | "transcribing" | "speaking" | "listening" | "thinking">("idle");
const conversationMode = ref(false);
const wakeWordEnabled = ref(false);
const wakeWordStarting = ref(false);
const wakeWordEngine = ref<"asr" | "sherpa">("asr");
const draft = ref("");
const error = ref("");
const notice = ref("");
const autoSpeak = ref(localStorage.getItem("jarvis-auto-speak") !== "false");
const messages = ref<Message[]>([{ role: "assistant", text: "嗨，我在这里。需要帮忙时，随时叫我。" }]);
const pending = ref<PendingConfirmation | null>(null);
const memory = ref<MemoryState | null>(null);
const memoryLoading = ref(false);
const chatBody = ref<HTMLElement | null>(null);
const windowRoot = ref<HTMLElement | null>(null);
const stateLabel = computed(() => state.value || "待命");
const petMotionClass = computed(() => {
  if (voiceState.value === "speaking") return "motion-speaking";
  if (busy.value || voiceState.value === "thinking") return "motion-thinking";
  if (voiceState.value === "listening" || wakeWordEnabled.value) return "motion-listening";
  if (wakeWordStarting.value || voiceState.value === "preparing" || voiceState.value === "starting") return "motion-waking";
  return "motion-idle";
});
let unlisteners: UnlistenFn[] = [];
let pointerRoutingTimer: number | undefined;
let cursorEventsIgnored: boolean | null = null;
let pointerRoutingBusy = false;
let wakeRecoveryTimer: number | undefined;
let wakeRecoveryStabilityTimer: number | undefined;
let wakeRecoveryAttempts = 0;
let wakeRecoveryRequested = false;
let resumeWakeAfterVisualConfirmation = false;
const MAX_WAKE_RECOVERY_ATTEMPTS = 3;

onMounted(async () => {
  unlisteners = await Promise.all([
    listen<AgentEvent>("agent-event", ({ payload }) => {
      state.value = payload.state || "处理中";
      if (payload.name === "agent.tool_called" && payload.detail) state.value = `正在处理 · ${payload.detail}`;
    }),
    listen<{ connected: number; configured: number }>("mcp-status", ({ payload }) => {
      notice.value = `MCP 外部工具已连接 ${payload.connected}/${payload.configured} 个；每次调用仍需确认。`;
    }),
    listen<{ text: string }>("agent-response", async ({ payload }) => {
      messages.value.push({ role: "assistant", text: payload.text });
      busy.value = false;
      state.value = "待命";
      scrollChat();
      if (autoSpeak.value || conversationMode.value) await speakResponse(payload.text);
      if (conversationMode.value) await continueVoiceConversation();
      else await resumeWakeAfterVisualConfirmationIfNeeded();
    }),
    listen<PendingConfirmation>("confirmation-required", ({ payload }) => {
      pending.value = payload;
      panel.value = "chat";
      open.value = true;
      state.value = "等待确认";
      if (conversationMode.value) void requestVoiceConfirmation(payload);
    }),
    listen<{ message: string }>("agent-error", ({ payload }) => {
      error.value = payload.message || "任务未能完成。";
      busy.value = false;
      state.value = "待命";
      if (conversationMode.value) void continueVoiceConversation();
      else void resumeWakeAfterVisualConfirmationIfNeeded();
    }),
    listen<{ state: "idle" | "starting" | "recording" | "speaking" | "listening" | "thinking" }>("voice-state", ({ payload }) => {
      voiceState.value = payload.state;
      state.value = payload.state === "listening" ? "正在听你说话" : payload.state === "recording" ? "正在录音" : payload.state === "thinking" ? "正在整理你的话" : payload.state === "speaking" ? "正在语音回答" : payload.state === "starting" ? "正在准备语音对话" : "待命";
    }),
    listen<{ text: string }>("voice-turn", ({ payload }) => {
      if (pending.value) void handleVoiceConfirmation(payload.text);
      else void handleVoiceTurn(payload.text);
    }),
    listen<{ text: string }>("wake-word-detected", async ({ payload }) => {
      wakeWordEnabled.value = false;
      wakeWordStarting.value = false;
      conversationMode.value = true;
      voiceState.value = "thinking";
      const command = payload.text.replace(/贾维斯[，,、。．.\s]*零/gi, "").trim();
      try {
        await speakResponse("收到。");
        await invoke("start_voice_conversation", { initialText: command || null });
      } catch (reason) {
        conversationMode.value = false;
        voiceState.value = "idle";
        error.value = String(reason);
        scheduleWakeWordRecovery(error.value);
      }
    }),
    listen<{ text: string }>("wake-word-observation", ({ payload }) => {
      notice.value = `唤醒监听刚才识别为：“${payload.text}”。如果没有匹配到“贾维斯·零”，请按屏幕显示的识别结果调整说法。`;
    }),
    listen<{ state: "idle" | "starting" | "listening" }>("wake-word-state", ({ payload }) => {
      wakeWordStarting.value = payload.state === "starting";
      wakeWordEnabled.value = payload.state === "listening";
      if (wakeWordStarting.value) state.value = "正在启动本机唤醒监听";
      else if (wakeWordEnabled.value) state.value = wakeWordEngine.value === "sherpa" ? "等待唤醒词“贾维斯·零”（Sherpa 测试）" : "等待唤醒词“贾维斯·零”";
      else if (wakeRecoveryRequested) state.value = "正在恢复唤醒监听";
      else if (!conversationMode.value && voiceState.value === "idle") state.value = "待命";
    }),
    listen<{ text: string }>("voice-transcript", ({ payload }) => {
      voiceState.value = "idle";
      state.value = "待命";
      draft.value = payload.text;
      error.value = "";
      notice.value = "已识别语音。需要查看文字时，可手动展开对话；录音和识别在本机完成。";
    }),
    listen<{ message: string }>("voice-error", ({ payload }) => {
      const shouldRecoverWake = wakeWordEnabled.value || conversationMode.value || wakeRecoveryRequested;
      conversationMode.value = false;
      wakeWordEnabled.value = false;
      wakeWordStarting.value = false;
      voiceState.value = "idle";
      state.value = "待命";
      error.value = payload.message || "语音输入失败。";
      if (shouldRecoverWake) scheduleWakeWordRecovery(error.value);
    }),
  ]);
  void loadMemory();
  pointerRoutingTimer = window.setInterval(() => void updateCursorRouting(), 80);
  void updateCursorRouting();
  window.setTimeout(() => void toggleWakeWord(false, "sherpa"), 800);
});

onBeforeUnmount(() => {
  unlisteners.forEach((unlisten) => unlisten());
  if (pointerRoutingTimer !== undefined) window.clearInterval(pointerRoutingTimer);
  clearWakeRecovery();
  void getCurrentWindow().setIgnoreCursorEvents(false);
});

function clearWakeRecovery(resetAttempts = true) {
  if (wakeRecoveryTimer !== undefined) window.clearTimeout(wakeRecoveryTimer);
  if (wakeRecoveryStabilityTimer !== undefined) window.clearTimeout(wakeRecoveryStabilityTimer);
  wakeRecoveryTimer = undefined;
  wakeRecoveryStabilityTimer = undefined;
  wakeRecoveryRequested = false;
  if (resetAttempts) wakeRecoveryAttempts = 0;
}

function scheduleWakeWordRecovery(reason: string) {
  wakeRecoveryRequested = true;
  if (wakeRecoveryTimer !== undefined) return;
  if (wakeRecoveryAttempts >= MAX_WAKE_RECOVERY_ATTEMPTS) {
    wakeRecoveryRequested = false;
    state.value = "唤醒监听需要检查";
    notice.value = "唤醒监听连续恢复失败。请检查麦克风权限和本机语音模型后，手动重新开启。最近错误：" + reason;
    return;
  }

  wakeRecoveryAttempts += 1;
  const attempt = wakeRecoveryAttempts;
  const delayMs = 1000 * 2 ** (attempt - 1);
  state.value = "正在恢复唤醒监听";
  notice.value = "语音监听出现问题，" + Math.round(delayMs / 1000) + " 秒后尝试恢复（" + attempt + "/" + MAX_WAKE_RECOVERY_ATTEMPTS + "）。";
  wakeRecoveryTimer = window.setTimeout(async () => {
    wakeRecoveryTimer = undefined;
    if (!wakeRecoveryRequested || busy.value || pending.value || conversationMode.value || wakeWordEnabled.value || wakeWordStarting.value) {
      wakeRecoveryRequested = false;
      state.value = pending.value ? "等待确认" : "待命";
      return;
    }
    try {
      const status = await invoke<string>("prepare_voice", { install: false });
      if (status !== "installed") throw new Error("本机语音模型不可用（" + status + "）。");
      wakeWordStarting.value = true;
      state.value = "正在启动本机唤醒监听";
      await invoke("start_wake_word_listener", { phrase: "贾维斯·零", engine: wakeWordEngine.value });
      voiceState.value = "idle";
      error.value = "";
      notice.value = "唤醒监听已恢复。";
      wakeRecoveryRequested = false;
      if (wakeRecoveryStabilityTimer !== undefined) window.clearTimeout(wakeRecoveryStabilityTimer);
      wakeRecoveryStabilityTimer = window.setTimeout(() => {
        wakeRecoveryStabilityTimer = undefined;
        wakeRecoveryAttempts = 0;
      }, 15_000);
    } catch (failure) {
      wakeWordStarting.value = false;
      error.value = String(failure);
      if (wakeRecoveryAttempts < MAX_WAKE_RECOVERY_ATTEMPTS) scheduleWakeWordRecovery(error.value);
      else {
        wakeRecoveryRequested = false;
        state.value = "唤醒监听需要检查";
        notice.value = "唤醒监听连续恢复失败。请检查麦克风权限和本机语音模型后，手动重新开启。最近错误：" + error.value;
      }
    }
  }, delayMs);
}

async function updateCursorRouting() {
  if (pointerRoutingBusy || !windowRoot.value) return;
  pointerRoutingBusy = true;
  try {
    const [cursor, origin, scale] = await Promise.all([
      cursorPosition(),
      getCurrentWindow().innerPosition(),
      getCurrentWindow().scaleFactor(),
    ]);
    const x = (cursor.x - origin.x) / scale;
    const y = (cursor.y - origin.y) / scale;
    const bounds = windowRoot.value.getBoundingClientRect();
    const insideWindow = x >= bounds.left && x < bounds.right && y >= bounds.top && y < bounds.bottom;
    const interactive = insideWindow
      && document.elementFromPoint(x, y)?.closest(".speech, .chat-panel, .companion-button, .pet-tools, .drag-hint");
    const shouldIgnore = !interactive;
    if (cursorEventsIgnored !== shouldIgnore) {
      await getCurrentWindow().setIgnoreCursorEvents(shouldIgnore);
      cursorEventsIgnored = shouldIgnore;
    }
  } catch {
    // Keep the window interactive if cursor routing is unavailable.
    if (cursorEventsIgnored === true) {
      try {
        await getCurrentWindow().setIgnoreCursorEvents(false);
        cursorEventsIgnored = false;
      } catch { /* The next polling pass can retry. */ }
    }
  } finally {
    pointerRoutingBusy = false;
  }
}

async function loadMemory() {
  if (memoryLoading.value) return;
  memoryLoading.value = true;
  error.value = "";
  notice.value = "";
  try {
    memory.value = await invoke<MemoryState>("memory_action", { action: "snapshot" });
    const history = memory.value.history.flat().map((message) => ({ role: message.role, text: message.content }));
    if (!busy.value && history.length) messages.value = history;
  } catch (reason) {
    error.value = String(reason);
  } finally {
    memoryLoading.value = false;
  }
}

async function runMemoryAction(action: string, id?: number) {
  error.value = "";
  try {
    memory.value = await invoke<MemoryState>("memory_action", { action, id });
    if (action === "clear_short_term") {
      messages.value = [{ role: "assistant", text: "短期对话记忆已清除；长期记忆和任务笔记保留。" }];
    }
  } catch (reason) {
    error.value = String(reason);
  }
}

function deleteMemory(action: "delete_fact" | "delete_task", id: number, label: string) {
  if (window.confirm(`要永久删除这条记忆吗？\n\n${label}\n\n此操作无法撤销。`)) {
    void runMemoryAction(action, id);
  }
}

function scrollChat() {
  requestAnimationFrame(() => chatBody.value?.scrollTo({ top: chatBody.value.scrollHeight, behavior: "smooth" }));
}

async function send() {
  const text = draft.value.trim();
  if (!text || busy.value || pending.value || voiceState.value !== "idle") return;
  messages.value.push({ role: "user", text });
  draft.value = "";
  busy.value = true;
  error.value = "";
  notice.value = "";
  state.value = "正在思考";
  open.value = true;
  scrollChat();
  try {
    await invoke("run_agent", { message: text });
  } catch (reason) {
    error.value = String(reason);
    busy.value = false;
    state.value = "待命";
  }
}

async function answerConfirmation(approved: boolean) {
  if (!pending.value) return;
  const id = pending.value.id;
  pending.value = null;
  state.value = approved ? "正在执行" : "已拒绝";
  try {
    await invoke("respond_confirmation", { id, approved });
  } catch (reason) {
    error.value = String(reason);
  }
}

async function resumeWakeAfterVisualConfirmationIfNeeded() {
  if (!resumeWakeAfterVisualConfirmation || pending.value || busy.value) return;
  resumeWakeAfterVisualConfirmation = false;
  await toggleWakeWord(false);
}

const highImpactVoiceConfirmationTools = new Set([
  "write_workspace_file", "click_screen", "type_screen_text", "press_screen_key", "operate_ui_element",
  "read_workspace_file", "read_screen_text", "inspect_active_window",
]);
const privateArgumentName = /password|secret|token|api[_-]?key|credential/i;

function confirmationNeedsVisualReview(item: PendingConfirmation) {
  return Object.entries(item.args).some(([key, value]) =>
    privateArgumentName.test(key) || JSON.stringify(value).length > 160,
  );
}

function confirmationSummary(item: PendingConfirmation) {
  const args = item.args || {};
  const value = (key: string) => {
    const entry = args[key];
    return typeof entry === "string" || typeof entry === "number" ? String(entry) : "";
  };
  const label = value("expected_title") || value("expected_description") || value("expected_identifier") || value("expected_role");
  const actionLabels: Record<string, string> = { press: "按下控件", focus: "聚焦控件", set_text: "在控件中输入文字" };
  switch (item.name) {
    case "open_application": return "打开应用 " + (value("app") || "（未提供名称）");
    case "open_installed_application": return "打开应用 " + (value("app_name") || "（未提供名称）");
    case "run_terminal": return "运行诊断命令 " + (value("command") || "（未提供命令）");
    case "browser_open": return "在受限浏览器中打开 " + (value("url") || "（未提供网址）");
    case "browser_read_page": return "读取当前网页标题和正文，并发送给当前模型";
    case "list_workspace": return "列出工作区目录 " + (value("path") || ".");
    case "read_workspace_file": return "读取工作区文件 " + value("path") + "，文件内容会发送给当前模型";
    case "write_workspace_file": return "向工作区文件 " + value("path") + " 写入内容：“" + value("content") + "”";
    case "read_screen_text": return "读取主显示器文字；屏幕内容会发送给当前模型";
    case "inspect_active_window": return "读取当前应用窗口控件和文字；可能包含私人信息并发送给当前模型";
    case "click_screen": return "单击屏幕坐标 " + value("x") + "，" + value("y");
    case "type_screen_text": return "向当前焦点输入：“" + value("text") + "”";
    case "press_screen_key": return "按下键盘按键 " + value("key");
    case "operate_ui_element": {
      const app = value("expected_bundle_id") || "当前应用";
      const operation = actionLabels[value("action")] || value("action") || "操作控件";
      const text = value("value");
      return app + " 中的“" + (label || "已检查控件") + "”："
        + operation + (text ? "，输入内容：“" + text + "”" : "");
    }
    default: {
      const printable = Object.entries(args)
        .filter(([key]) => !privateArgumentName.test(key))
        .map(([key, entry]) => key + " " + (typeof entry === "string" ? entry : JSON.stringify(entry)))
        .join("；");
      return (item.name.startsWith("mcp_") ? "调用外部工具 " : "") + item.name
        + (printable ? "，参数：" + printable : "");
    }
  }
}

function voiceConfirmationPhrase(item: PendingConfirmation) {
  return highImpactVoiceConfirmationTools.has(item.name) || item.name.startsWith("mcp_")
    ? "确认执行这项操作"
    : "确认执行";
}

async function requestVoiceConfirmation(item: PendingConfirmation) {
  const summary = confirmationSummary(item);
  if (confirmationNeedsVisualReview(item)) {
    notice.value = "该操作包含较长或敏感参数，需要先在确认卡中核对完整内容。";
    await speakResponse("需要确认的操作是：" + summary
      + "。参数较长或可能包含敏感信息，我不会仅凭语音确认执行。请查看桌面确认卡，再点击允许或拒绝。");
    resumeWakeAfterVisualConfirmation = true;
    conversationMode.value = false;
    voiceState.value = "idle";
    try { await invoke("stop_voice_conversation"); } catch (reason) { error.value = String(reason); }
    return;
  }
  const phrase = voiceConfirmationPhrase(item);
  notice.value = "等待语音确认：" + summary + "。请说“" + phrase + "”或“取消”。";
  const caution = highImpactVoiceConfirmationTools.has(item.name) || item.name.startsWith("mcp_")
    ? "这是需要谨慎确认的操作。" : "";
  await speakResponse("需要确认的操作是：" + summary + "。" + caution
    + "如果同意，请完整说“" + phrase + "”；不同意请说“取消”。");
  if (conversationMode.value && pending.value) await continueVoiceConversation();
}

async function handleVoiceConfirmation(text: string) {
  const normalized = text.replace(/[\s，。！？、,.!?；;：:“”‘’]/g, "").replace(/^(好的|好|我|请)/, "");
  const approve = pending.value !== null && normalized === voiceConfirmationPhrase(pending.value);
  const deny = ["取消", "拒绝", "拒绝这次", "不允许", "不要执行", "停止执行"].includes(normalized);
  if (approve || deny) {
    notice.value = approve ? "已收到语音确认，正在执行。" : "已收到语音拒绝。";
    await answerConfirmation(approve);
    return;
  }
  notice.value = `没有识别为“确认执行”或“取消”：${text}`;
  await speakResponse("我没听清。请明确说“确认执行”或“取消”。");
  if (conversationMode.value && pending.value) await continueVoiceConversation();
}

function resetChat() {
  if (busy.value || pending.value) return;
  messages.value = [{ role: "assistant", text: "已清空当前窗口显示；不会删除已保存的记忆。" }];
  error.value = "";
  notice.value = "";
}

function toggleChat() {
  if (pending.value) {
    panel.value = "chat";
    open.value = true;
    return;
  }
  const wasChatOpen = open.value && panel.value === "chat";
  panel.value = "chat";
  open.value = !wasChatOpen;
}

async function startWindowDrag() {
  try {
    await getCurrentWindow().startDragging();
  } catch (reason) {
    error.value = `无法移动伙伴窗口：${String(reason)}`;
  }
}

async function toggleVoice() {
  error.value = "";
  if (conversationMode.value) {
    conversationMode.value = false;
    voiceState.value = "transcribing";
    state.value = "正在结束语音对话";
    try {
      await invoke("stop_voice_conversation");
    } catch (reason) {
      state.value = "待命";
      voiceState.value = "idle";
      error.value = String(reason);
    }
    return;
  }
  if (busy.value || pending.value || ["preparing", "starting", "transcribing", "speaking", "thinking"].includes(voiceState.value)) return;

  voiceState.value = "preparing";
  state.value = "准备本机语音识别";
  open.value = true;
  panel.value = "chat";
  try {
    let status = await invoke<string>("prepare_voice", { install: false });
    if (status !== "installed") {
      if (status === "unsupported") throw new Error("这台 Mac 暂不支持所选语言的本机语音识别。");
      const accepted = window.confirm("需要从 Apple 下载中文本机语音模型，约需一些时间。录音和识别都在本机完成，不会上传音频。现在下载吗？");
      if (!accepted) {
        voiceState.value = "idle";
        state.value = "待命";
        return;
      }
      state.value = "正在下载本机语音模型…";
      status = await invoke<string>("prepare_voice", { install: true });
    }
    if (status !== "installed") throw new Error(`本机语音模型不可用（${status}）。`);
    await invoke("start_voice_conversation", { initialText: null });
    conversationMode.value = true;
    if (voiceState.value === "preparing") voiceState.value = "starting";
  } catch (reason) {
    voiceState.value = "idle";
    state.value = "待命";
    error.value = String(reason);
  }
}

async function toggleWakeWord(showPanel = true, engine: "asr" | "sherpa" = "sherpa") {
  clearWakeRecovery();
  error.value = "";
  notice.value = "";
  if (wakeWordEnabled.value || wakeWordStarting.value) {
    try {
      await invoke("stop_wake_word_listener");
      wakeWordEnabled.value = false;
      wakeWordStarting.value = false;
      voiceState.value = "idle";
      state.value = "待命";
    } catch (reason) {
      error.value = String(reason);
      return;
    }
    if (wakeWordEngine.value === engine) return;
    await new Promise((resolve) => window.setTimeout(resolve, 350));
  }
  if (busy.value || pending.value || conversationMode.value || voiceState.value !== "idle") return;
  voiceState.value = "preparing";
  if (showPanel) {
    open.value = true;
    panel.value = "chat";
  }
  try {
    let status = await invoke<string>("prepare_voice", { install: false });
    if (status !== "installed") {
      if (status === "unsupported") throw new Error("这台 Mac 暂不支持本机中文语音识别。");
      const accepted = window.confirm("语音唤醒需要持续进行本机语音识别。缺少中文模型时，需要先从 Apple 下载。监听仅在本机处理，且默认关闭。现在下载吗？");
      if (!accepted) return;
      status = await invoke<string>("prepare_voice", { install: true });
    }
    if (status !== "installed") throw new Error(`本机语音模型不可用（${status}）。`);
    wakeWordStarting.value = true;
    wakeWordEngine.value = engine;
    state.value = "正在启动本机唤醒监听";
    await invoke("start_wake_word_listener", { phrase: "贾维斯·零", engine });
  } catch (reason) {
    wakeWordStarting.value = false;
    error.value = String(reason);
    voiceState.value = "idle";
    state.value = "待命";
  } finally {
    if (voiceState.value === "preparing") voiceState.value = "idle";
  }
}

function clearShortTerm() {
  if (window.confirm("永久清除所有短期对话记忆？长期记忆和任务笔记不会删除。此操作无法撤销。")) {
    void runMemoryAction("clear_short_term");
  }
}

async function speakResponse(text: string) {
  try {
    await invoke("speak_response", { text });
  } catch (reason) {
    error.value = String(reason);
  }
}

async function continueVoiceConversation() {
  if (!conversationMode.value) return;
  try {
    await invoke("continue_voice_conversation");
  } catch (reason) {
    if (String(reason).includes("没有等待继续的语音对话轮次")) return;
    if (conversationMode.value) {
      error.value = String(reason);
      conversationMode.value = false;
      voiceState.value = "idle";
      scheduleWakeWordRecovery(error.value);
    }
  }
}

async function handleVoiceTurn(text: string) {
  if (!conversationMode.value || busy.value) return;
  const normalized = text.replace(/[\s，。！？、,.!?；;：:“”‘’]/g, "");
  if (["退下吧", "退下", "结束对话", "休息吧"].includes(normalized)) {
    messages.value.push({ role: "user", text });
    messages.value.push({ role: "assistant", text: "好的，我退下了。" });
    busy.value = false;
    error.value = "";
    notice.value = "语音对话已结束，我会继续等待唤醒词“贾维斯·零”。需要查看记录时，可手动展开对话。";
    conversationMode.value = false;
    await speakResponse("好的，我退下了。");
    try {
      await invoke("stop_voice_conversation");
      voiceState.value = "idle";
      await toggleWakeWord(false);
    } catch (reason) {
      error.value = `已结束语音对话，但未能恢复唤醒监听：${String(reason)}`;
    }
    return;
  }
  messages.value.push({ role: "user", text });
  busy.value = true;
  error.value = "";
  notice.value = "已听到你说的话，正在回答。你可以随时结束语音对话。";
  try {
    await invoke("run_agent", { message: text });
  } catch (reason) {
    error.value = String(reason);
    busy.value = false;
    await continueVoiceConversation();
  }
}

function toggleAutoSpeak() {
  autoSpeak.value = !autoSpeak.value;
  localStorage.setItem("jarvis-auto-speak", String(autoSpeak.value));
  notice.value = autoSpeak.value ? "已开启自动朗读；后续回复会由 macOS 在本机读出。" : "已关闭自动朗读；回复只显示文字。";
}
</script>

<template>
  <main ref="windowRoot" class="pet-window">
    <div class="aura"></div>
    <header class="speech" data-tauri-drag-region>
      <div class="speech-top">
        <span class="sigil">J</span>
        <span class="identity">JARVIS <small>· 伙伴模式</small></span>
        <span class="live-state"><i></i>{{ stateLabel }}</span>
      </div>
      <p>{{ conversationMode && voiceState === "listening" ? "我在听。说完一句后停顿一下，我会自动回答。" : conversationMode && voiceState === "thinking" ? "我听到了，正在组织回答…" : voiceState === "speaking" ? "我来为你朗读回复。" : voiceState === "preparing" ? "正在准备本机语音识别…" : busy ? "我正在处理这件事…" : pending ? "等你确认后，我会继续。" : open ? "想做什么？告诉我吧。" : "嗨，我在这里。需要帮忙时，随时叫我。" }}</p>
      <div class="speech-foot"><span>✦ {{ memory ? `记忆 ${memory.shortTerm}/${memory.shortLimit} · ${memory.longTerm} 条长期` : "本机伙伴已就绪" }}</span><button class="collapse" @click="toggleChat" :aria-label="open && panel === 'chat' ? '收起对话' : '展开对话'">{{ open && panel === "chat" ? "收起" : "对话" }}</button></div>
      <div class="tail"></div>
    </header>

    <section v-if="open && panel === 'chat'" class="chat-panel" aria-label="JARVIS 对话">
      <div ref="chatBody" class="chat-messages" aria-live="polite">
        <div v-for="(message, index) in messages" :key="index" class="chat-message" :class="message.role">
          <span class="chat-avatar">{{ message.role === "user" ? "你" : "J" }}</span>
          <p>{{ message.text }}</p>
        </div>
        <div v-if="busy" class="working"><i></i><i></i><i></i><span>{{ stateLabel }}</span></div>
        <div v-if="pending" class="confirm-card">
          <b>需要你确认</b>
          <p>JARVIS 请求执行 <code>{{ pending.name }}</code></p>
          <pre v-if="Object.keys(pending.args).length">{{ JSON.stringify(pending.args, null, 2) }}</pre>
          <div class="confirm-actions"><button @click="answerConfirmation(false)">拒绝</button><button class="approve" @click="answerConfirmation(true)">允许这次</button></div>
        </div>
        <p v-if="error" class="error">{{ error }}</p>
        <p v-if="notice" class="notice">{{ notice }}</p>
      </div>
      <form class="composer" @submit.prevent="send">
        <input v-model="draft" :disabled="busy || !!pending || voiceState !== 'idle'" maxlength="16000" placeholder="输入消息…" aria-label="输入消息" />
        <button type="submit" :disabled="!draft.trim() || busy || !!pending || voiceState !== 'idle'" aria-label="发送消息">↑</button>
      </form>
      <div class="chat-note">消息发给当前配置的模型服务商</div>
    </section>

    <section v-if="open && panel === 'memory'" class="chat-panel memory-panel" aria-label="JARVIS 记忆管理">
      <div class="memory-heading"><b>记忆管理</b><button :disabled="memoryLoading" @click="loadMemory">{{ memoryLoading ? "读取中…" : "刷新" }}</button></div>
      <p v-if="memory" class="memory-note">短期 {{ memory.shortTerm }}/{{ memory.shortLimit }} 轮 · 长期 {{ memory.longTerm }} 条 · 任务 {{ memory.taskCount }} 条<br>保存于本机 SQLite；记忆会进入当前 {{ memory.provider }} / {{ memory.model }} 的上下文。</p>
      <p v-else class="memory-note">正在读取本机记忆…</p>
      <div class="memory-list">
        <div class="memory-section"><b>短期对话</b><button v-if="memory?.shortTerm" class="delete-memory" @click="clearShortTerm">清除</button></div>
        <p v-if="!memory?.shortTerm" class="empty-memory">没有短期对话记忆</p>
        <div v-for="item in memory?.facts || []" :key="`fact-${item.id}`" class="memory-item"><span>{{ item.fact }}</span><button class="delete-memory" aria-label="删除长期记忆" @click="deleteMemory('delete_fact', item.id, item.fact)">删除</button></div>
        <p v-if="memory && !memory.facts.length" class="empty-memory">没有长期记忆</p>
        <div v-for="item in memory?.tasks || []" :key="`task-${item.id}`" class="memory-item"><span><b>{{ item.title }}</b><small>{{ item.note }}</small></span><button class="delete-memory" aria-label="删除任务记忆" @click="deleteMemory('delete_task', item.id, item.title)">删除</button></div>
        <p v-if="memory && !memory.tasks.length" class="empty-memory">没有任务笔记</p>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <div class="chat-note">完整删除控制也可在 CLI 使用 /forget 和 /task delete</div>
    </section>

    <button class="companion-button" :aria-label="open ? '收起伙伴面板' : '打开伙伴面板'" :disabled="!!pending" @click="open = !open"><img class="companion" :class="petMotionClass" src="/assets/jarvis-particle-companion-v2.png" alt="" /></button>
    <div class="idle-caption"><span class="pulse"></span>{{ busy || voiceState !== "idle" ? stateLabel : "安静陪伴中" }}</div>
    <nav class="pet-tools" aria-label="宠物快捷操作">
      <button :class="{ selected: open && panel === 'chat' }" title="对话" aria-label="打开对话" @click="toggleChat">✧</button>
      <button :class="{ selected: open && panel === 'memory' }" title="记忆管理" aria-label="记忆管理" :disabled="!!pending" @click="panel = 'memory'; open = true">◈</button>
      <button title="清空本次显示" aria-label="清空本次显示" :disabled="busy || !!pending" @click="resetChat">↺</button>
      <button :class="{ selected: autoSpeak }" :title="autoSpeak ? '关闭自动朗读回复' : '开启自动朗读回复'" :aria-label="autoSpeak ? '关闭自动朗读回复' : '开启自动朗读回复'" :aria-pressed="autoSpeak" @click="toggleAutoSpeak">◖))</button>
      <button :class="{ selected: (wakeWordEnabled || wakeWordStarting) && wakeWordEngine === 'asr' }" :title="wakeWordEnabled || wakeWordStarting ? '关闭本机语音唤醒' : '开启本机语音唤醒（Apple SpeechAnalyzer）'" :aria-label="wakeWordEnabled || wakeWordStarting ? '关闭本机语音唤醒' : '开启本机语音唤醒（Apple SpeechAnalyzer）'" :aria-pressed="(wakeWordEnabled || wakeWordStarting) && wakeWordEngine === 'asr'" :disabled="busy || !!pending || conversationMode || voiceState !== 'idle'" @click="toggleWakeWord(true, 'asr')">{{ wakeWordStarting && wakeWordEngine === 'asr' ? "…" : wakeWordEnabled && wakeWordEngine === 'asr' ? "⌁" : "唤" }}</button>
      <button :class="{ selected: (wakeWordEnabled || wakeWordStarting) && wakeWordEngine === 'sherpa' }" :title="wakeWordEnabled || wakeWordStarting ? '关闭本机关键词唤醒' : '开启 Sherpa 关键词唤醒测试'" :aria-label="wakeWordEnabled || wakeWordStarting ? '关闭本机关键词唤醒' : '开启 Sherpa 关键词唤醒测试'" :aria-pressed="(wakeWordEnabled || wakeWordStarting) && wakeWordEngine === 'sherpa'" :disabled="busy || !!pending || conversationMode || voiceState !== 'idle'" @click="toggleWakeWord(true, 'sherpa')">{{ wakeWordStarting && wakeWordEngine === 'sherpa' ? "…" : "KWS" }}</button>
      <button :class="{ recording: conversationMode }" :title="conversationMode ? '结束语音对话' : '开始语音对话'" :aria-label="conversationMode ? '结束语音对话' : '开始语音对话'" :aria-pressed="conversationMode" :disabled="(!conversationMode && (busy || !!pending || wakeWordEnabled || voiceState === 'preparing' || voiceState === 'starting' || voiceState === 'transcribing' || voiceState === 'speaking' || voiceState === 'thinking'))" @click="toggleVoice">{{ voiceState === "preparing" || voiceState === "starting" || voiceState === "transcribing" || voiceState === "thinking" ? "…" : conversationMode ? "■" : "♫" }}</button>
    </nav>
    <button class="drag-hint" title="按住并拖动以移动窗口" aria-label="按住并拖动以移动伙伴窗口" @pointerdown.left.prevent="startWindowDrag"><span aria-hidden="true">⠿</span> 按住拖动</button>
  </main>
</template>
