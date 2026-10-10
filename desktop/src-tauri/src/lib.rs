use serde_json::{json, Value};
use std::{collections::HashMap, path::PathBuf, process::Stdio, sync::{atomic::{AtomicU64, Ordering}, Arc, Mutex}};
use tauri::{AppHandle, Emitter, Manager, State};
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, ChildStdout, Command},
    sync::{oneshot, watch},
};

#[derive(Default)]
struct PendingConfirmations(Mutex<HashMap<String, oneshot::Sender<bool>>>);

struct BridgeSession {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

#[derive(Default)]
struct AgentBridge(tokio::sync::Mutex<Option<BridgeSession>>);

struct VoiceSession {
    id: String,
    stdin: ChildStdin,
}

#[derive(Default)]
struct VoiceCapture(tokio::sync::Mutex<Option<VoiceSession>>);

#[derive(Default)]
struct WakeWordListener(tokio::sync::Mutex<Option<watch::Sender<bool>>>);

#[derive(Default)]
struct VoiceConversationState {
    cancel: Option<watch::Sender<bool>>,
    resume: Option<oneshot::Sender<()>>,
}

#[derive(Default)]
struct VoiceConversation(tokio::sync::Mutex<VoiceConversationState>);

static VOICE_SESSION_ID: AtomicU64 = AtomicU64::new(1);

fn project_root() -> Result<PathBuf, String> {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .map_err(|_| "无法定位 JARVIS 项目目录".to_string())
}

#[tauri::command]
async fn respond_confirmation(
    id: String,
    approved: bool,
    pending: State<'_, PendingConfirmations>,
) -> Result<(), String> {
    let sender = pending.0.lock().map_err(|_| "确认队列不可用")?.remove(&id);
    match sender {
        Some(sender) => sender.send(approved).map_err(|_| "该确认请求已结束".to_string()),
        None => Err("未找到待处理的本机确认请求".to_string()),
    }
}

#[tauri::command]
async fn memory_action(action: String, id: Option<i64>) -> Result<Value, String> {
    let valid = matches!(action.as_str(), "snapshot" | "clear_short_term" | "delete_fact" | "delete_task");
    if !valid || (matches!(action.as_str(), "delete_fact" | "delete_task") && id.unwrap_or(0) <= 0) {
        return Err("无效的记忆操作".to_string());
    }

    let root = project_root()?;
    let mut child = Command::new(root.join(".venv/bin/python"))
        .args(["-m", "app.desktop_bridge"])
        .current_dir(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true)
        .spawn()
        .map_err(|_| "无法启动本机记忆服务".to_string())?;
    let mut stdin = child.stdin.take().ok_or("无法连接本机记忆服务")?;
    let request = json!({ "type": "memory_action", "action": action, "id": id });
    stdin.write_all(format!("{request}\n").as_bytes()).await.map_err(|_| "无法发送记忆操作")?;
    drop(stdin);

    let stdout = child.stdout.take().ok_or("无法读取本机记忆服务")?;
    let mut lines = BufReader::new(stdout).lines();
    let line = lines.next_line().await.map_err(|_| "读取本机记忆服务失败")?
        .ok_or("本机记忆服务没有返回结果")?;
    let event: Value = serde_json::from_str(&line).map_err(|_| "本机记忆服务返回无效数据")?;
    let status = child.wait().await.map_err(|_| "本机记忆服务退出状态不可用")?;
    if !status.success() {
        return Err("本机记忆服务异常退出".to_string());
    }
    if event["type"] == "error" {
        return Err(event["message"].as_str().unwrap_or("记忆操作失败").to_string());
    }
    if event["type"] != "memory_snapshot" {
        return Err("本机记忆服务返回了意外结果".to_string());
    }
    Ok(event.get("payload").cloned().unwrap_or(Value::Null))
}

#[tauri::command]
async fn prepare_voice(install: bool) -> Result<String, String> {
    let root = project_root()?;
    let mut child = Command::new(root.join(".venv/bin/python"))
        .args(["-m", "app.desktop_bridge"])
        .current_dir(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true)
        .spawn()
        .map_err(|_| "无法启动本机语音服务".to_string())?;
    let mut stdin = child.stdin.take().ok_or("无法连接本机语音服务")?;
    let request = json!({ "type": "voice_prepare", "install": install });
    stdin.write_all(format!("{request}\n").as_bytes()).await.map_err(|_| "无法发送语音准备请求")?;
    drop(stdin);

    let stdout = child.stdout.take().ok_or("无法读取本机语音服务")?;
    let mut lines = BufReader::new(stdout).lines();
    let mut status = None;
    while let Some(line) = lines.next_line().await.map_err(|_| "读取语音准备结果失败")? {
        let event: Value = serde_json::from_str(&line).map_err(|_| "语音服务返回无效数据")?;
        match event["type"].as_str().unwrap_or("") {
            "voice_prepared" => status = event["status"].as_str().map(str::to_owned),
            "error" => return Err(event["message"].as_str().unwrap_or("语音准备失败").to_string()),
            _ => {}
        }
    }
    let exit = child.wait().await.map_err(|_| "语音准备服务退出状态不可用")?;
    if !exit.success() {
        return Err("语音准备服务异常退出".to_string());
    }
    status.ok_or_else(|| "语音准备服务没有返回状态".to_string())
}

#[tauri::command]
async fn start_voice(app: AppHandle, capture: State<'_, VoiceCapture>) -> Result<(), String> {
    let mut active = capture.0.lock().await;
    if active.is_some() {
        return Err("语音录音已经在进行中".to_string());
    }
    let root = project_root()?;
    let executable = root.join(".build/JARVIS Voice.app/Contents/MacOS/JARVISVoice");
    let mut child = Command::new(executable)
        .args(["transcribe", "zh-CN"])
        .current_dir(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .map_err(|_| "无法启动本机语音辅助程序".to_string())?;
    let stdin = child.stdin.take().ok_or("无法连接语音辅助程序")?;
    let stdout = child.stdout.take().ok_or("无法读取语音识别结果")?;
    let stderr = child.stderr.take().ok_or("无法读取语音辅助程序状态")?;
    let id = VOICE_SESSION_ID.fetch_add(1, Ordering::Relaxed).to_string();
    *active = Some(VoiceSession { id: id.clone(), stdin });
    app.emit("voice-state", json!({ "state": "starting" })).map_err(|e| e.to_string())?;
    drop(active);

    let task_app = app.clone();
    tokio::spawn(async move {
        let output_task = tokio::spawn(async move {
            let mut output = Vec::new();
            let mut reader = BufReader::new(stdout);
            let _ = reader.read_to_end(&mut output).await;
            output
        });
        let stderr_app = task_app.clone();
        let stderr_task = tokio::spawn(async move {
            let mut diagnostics = Vec::new();
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                if line.contains("录音中") {
                    let _ = stderr_app.emit("voice-state", json!({ "state": "recording" }));
                }
                diagnostics.push(line);
            }
            diagnostics.join("\n")
        });
        let status = child.wait().await;
        let output = output_task.await.unwrap_or_default();
        let diagnostics = stderr_task.await.unwrap_or_default();
        match status {
            Ok(status) if status.success() => {
                let text = String::from_utf8_lossy(&output).trim().to_string();
                if text.is_empty() {
                    let _ = task_app.emit("voice-error", json!({ "message": "没有识别到语音文字，请再试一次。" }));
                } else {
                    let _ = task_app.emit("voice-transcript", json!({ "text": text }));
                }
            }
            _ => {
                let message = if diagnostics.is_empty() { "本机语音识别失败，请检查麦克风权限。" } else { &diagnostics };
                let _ = task_app.emit("voice-error", json!({ "message": message }));
            }
        }
        let state = task_app.state::<VoiceCapture>();
        let mut active = state.0.lock().await;
        if active.as_ref().is_some_and(|session| session.id == id) {
            active.take();
        }
    });
    Ok(())
}

#[tauri::command]
async fn stop_voice(capture: State<'_, VoiceCapture>) -> Result<(), String> {
    let mut active = capture.0.lock().await;
    let session = active.take().ok_or_else(|| "当前没有正在进行的语音录音".to_string())?;
    let mut stdin = session.stdin;
    stdin.write_all(b"stop\n").await.map_err(|_| "无法停止语音录音".to_string())?;
    stdin.flush().await.map_err(|_| "无法提交语音录音")?;
    Ok(())
}

#[tauri::command]
async fn start_voice_conversation(
    app: AppHandle,
    conversation: State<'_, Arc<VoiceConversation>>,
    initial_text: Option<String>,
) -> Result<(), String> {
    let root = project_root()?;
    let executable = root.join(".build/JARVIS Voice.app/Contents/MacOS/JARVISVoice");
    let mut state = conversation.0.lock().await;
    if state.cancel.is_some() {
        return Err("语音对话已经开启".to_string());
    }
    let (cancel_tx, mut cancel_rx) = watch::channel(false);
    state.cancel = Some(cancel_tx);
    state.resume = None;
    drop(state);

    let task_app = app.clone();
    let control = Arc::clone(&conversation);
    tokio::spawn(async move {
        if let Some(text) = initial_text.map(|text| text.trim().to_string()).filter(|text| !text.is_empty()) {
            let (resume_tx, resume_rx) = oneshot::channel();
            {
                let mut state = control.0.lock().await;
                if state.cancel.is_none() { return; }
                state.resume = Some(resume_tx);
            }
            let _ = task_app.emit("voice-state", json!({ "state": "thinking" }));
            let _ = task_app.emit("voice-turn", json!({ "text": text }));
            tokio::select! {
                _ = resume_rx => {},
                _ = cancel_rx.changed() => {},
            }
        }
        loop {
            if *cancel_rx.borrow() { break; }
            let _ = task_app.emit("voice-state", json!({ "state": "starting" }));
            let spawned = Command::new(&executable)
                .args(["transcribe-auto", "zh-CN"])
                .current_dir(&root)
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .kill_on_drop(true)
                .spawn();
            let mut child = match spawned {
                Ok(child) => child,
                Err(_) => {
                    let _ = task_app.emit("voice-error", json!({ "message": "无法启动本机语音识别。请重启应用后重试。" }));
                    break;
                }
            };
            let stdout = match child.stdout.take() { Some(value) => value, None => break };
            let stderr = match child.stderr.take() { Some(value) => value, None => break };
            let output_task = tokio::spawn(async move {
                let mut bytes = Vec::new();
                let mut reader = BufReader::new(stdout);
                let _ = reader.read_to_end(&mut bytes).await;
                bytes
            });
            let status_app = task_app.clone();
            let stderr_task = tokio::spawn(async move {
                let mut diagnostics = Vec::new();
                let mut lines = BufReader::new(stderr).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    if line.contains("录音中") {
                        let _ = status_app.emit("voice-state", json!({ "state": "listening" }));
                    }
                    diagnostics.push(line);
                }
                diagnostics.join("\n")
            });
            let status = tokio::select! {
                status = child.wait() => Some(status),
                _ = cancel_rx.changed() => {
                    let _ = child.kill().await;
                    None
                }
            };
            let output = output_task.await.unwrap_or_default();
            let diagnostics = stderr_task.await.unwrap_or_default();
            if status.is_none() || *cancel_rx.borrow() { break; }

            let exit_detail = match &status {
                Some(Ok(exit)) => format!("退出码 {}", exit.code().unwrap_or(-1)),
                Some(Err(error)) => format!("等待语音辅助程序退出失败：{error}"),
                None => "语音对话已停止".to_string(),
            };
            let status_ok = status.as_ref()
                .and_then(|result| result.as_ref().ok())
                .is_some_and(|status| status.success());
            let text = String::from_utf8_lossy(&output).trim().to_string();
            if status_ok && !text.is_empty() {
                let (resume_tx, resume_rx) = oneshot::channel();
                {
                    let mut state = control.0.lock().await;
                    if state.cancel.is_none() || *cancel_rx.borrow() { break; }
                    state.resume = Some(resume_tx);
                }
                let _ = task_app.emit("voice-state", json!({ "state": "thinking" }));
                let _ = task_app.emit("voice-turn", json!({ "text": text }));
                tokio::select! {
                    _ = resume_rx => {},
                    _ = cancel_rx.changed() => break,
                }
                continue;
            }

            if !status_ok && !diagnostics.contains("没有识别出文字") && !diagnostics.contains("没有采集到音频") {
                let message = if diagnostics.is_empty() {
                    format!("本机语音识别失败（{exit_detail}），请检查麦克风权限和语音模型。")
                } else {
                    diagnostics
                };
                let _ = task_app.emit("voice-error", json!({ "message": message }));
                break;
            }
            tokio::select! {
                _ = tokio::time::sleep(std::time::Duration::from_millis(250)) => {},
                _ = cancel_rx.changed() => break,
            }
        }
        let mut state = control.0.lock().await;
        state.cancel = None;
        state.resume = None;
        let _ = task_app.emit("voice-state", json!({ "state": "idle" }));
    });
    Ok(())
}

fn normalized_wake_text(text: &str) -> String {
    text.chars().filter(|character| character.is_alphanumeric()).flat_map(char::to_lowercase).collect()
}

#[cfg(test)]
mod wake_word_tests {
    use super::normalized_wake_text;

    #[test]
    fn ignores_chinese_and_ascii_punctuation_in_wake_phrase() {
        let phrase = normalized_wake_text("贾维斯·零");
        assert!(normalized_wake_text("贾维斯，零，帮我查天气").contains(&phrase));
        assert!(!normalized_wake_text("贾维斯你好").contains(&phrase));
    }
}

#[tauri::command]
async fn start_wake_word_listener(
    app: AppHandle,
    listener: State<'_, WakeWordListener>,
    phrase: String,
    engine: Option<String>,
) -> Result<(), String> {
    let engine = engine.unwrap_or_else(|| "asr".to_string());
    if engine != "asr" && engine != "sherpa" {
        return Err("不支持的唤醒检测方式".to_string());
    }
    let phrase = normalized_wake_text(&phrase);
    if phrase.len() < 2 || phrase.len() > 64 {
        return Err("唤醒词长度无效".to_string());
    }
    let root = project_root()?;
    let executable = root.join(".build/JARVIS Voice.app/Contents/MacOS/JARVISVoice");
    let mut active = listener.0.lock().await;
    if active.is_some() { return Err("语音唤醒已经开启".to_string()); }
    let (cancel_tx, mut cancel_rx) = watch::channel(false);
    *active = Some(cancel_tx);
    drop(active);

    // Publish startup before spawning the listener so a fast microphone
    // startup cannot emit `listening` and then be overwritten by `starting`.
    let _ = app.emit("wake-word-state", json!({ "state": "starting" }));
    let task_app = app.clone();
    let state_app = app.clone();
    tokio::spawn(async move {
        loop {
            if *cancel_rx.borrow() { break; }
            let kws_app = root.join(".build/JARVIS KWS Candidate.app");
            let spawned = if engine == "sherpa" {
                Command::new(kws_app.join("Contents/MacOS/JarvisKWS"))
                    .current_dir(&root)
                    .env("JARVIS_KWS_MODEL_DIR", kws_app.join("Contents/Resources/KWSModel"))
                    .env("JARVIS_KWS_KEYWORDS", kws_app.join("Contents/Resources/KWSModel/jarvis-keywords.txt"))
                    .stdin(Stdio::null())
                    .stdout(Stdio::piped())
                    .stderr(Stdio::piped())
                    .kill_on_drop(true)
                    .spawn()
            } else {
                Command::new(&executable)
                    .args(["transcribe-auto", "zh-CN"])
                    .current_dir(&root)
                    .stdin(Stdio::null())
                    .stdout(Stdio::piped())
                    .stderr(Stdio::piped())
                    .kill_on_drop(true)
                    .spawn()
            };
            let mut child = match spawned {
                Ok(child) => child,
                Err(_) => {
                    let message = if engine == "sherpa" {
                        "无法启动 Sherpa 关键词检测器。请先运行 scripts/setup_kws_model.py 和 scripts/build_kws_helper.py。"
                    } else {
                        "无法启动本机唤醒词监听。请检查语音辅助程序。"
                    };
                    let _ = task_app.emit("voice-error", json!({ "message": message }));
                    break;
                }
            };
            let stdout = match child.stdout.take() { Some(value) => value, None => break };
            let stderr = match child.stderr.take() { Some(value) => value, None => break };
            let output_task = tokio::spawn(async move {
                let mut bytes = Vec::new();
                let mut reader = BufReader::new(stdout);
                let _ = reader.read_to_end(&mut bytes).await;
                bytes
            });
            let status_app = task_app.clone();
            let stderr_task = tokio::spawn(async move {
                let mut diagnostics = Vec::new();
                let mut lines = BufReader::new(stderr).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    if line.contains("专用关键词检测正在监听") || line.contains("录音中") {
                        let _ = status_app.emit("wake-word-state", json!({ "state": "listening" }));
                    }
                    diagnostics.push(line);
                }
                diagnostics.join("\n")
            });
            let status = tokio::select! {
                status = child.wait() => Some(status),
                _ = cancel_rx.changed() => {
                    let _ = child.kill().await;
                    None
                }
            };
            let output = output_task.await.unwrap_or_default();
            let diagnostics = stderr_task.await.unwrap_or_default();
            if status.is_none() || *cancel_rx.borrow() { break; }
            let raw_text = String::from_utf8_lossy(&output).trim().to_string();
            let text = if engine == "sherpa" {
                raw_text.strip_prefix("WAKE_WORD_DETECTED:").unwrap_or("").trim().to_string()
            } else {
                raw_text
            };
            let status_ok = status.as_ref().and_then(|value| value.as_ref().ok()).is_some_and(|value| value.success());
            if status_ok && !text.is_empty()
                && (engine == "sherpa" || normalized_wake_text(&text).contains(&phrase)) {
                let _ = task_app.emit("wake-word-detected", json!({ "text": text }));
                break;
            }
            if status_ok && !text.is_empty() {
                // Keep the listener's ASR result visible so a missed wake word
                // can be distinguished from a microphone or permission failure.
                let _ = task_app.emit("wake-word-observation", json!({ "text": text }));
            }
            if !status_ok && !diagnostics.contains("没有识别出文字") && !diagnostics.contains("没有采集到音频") {
                let message = if diagnostics.is_empty() { "本机唤醒词监听失败，请检查麦克风权限和语音模型。".to_string() } else { diagnostics };
                let _ = task_app.emit("voice-error", json!({ "message": message }));
                break;
            }
        }
        let state = state_app.state::<WakeWordListener>();
        let mut active = state.0.lock().await;
        active.take();
        let _ = task_app.emit("wake-word-state", json!({ "state": "idle" }));
    });
    Ok(())
}

#[tauri::command]
async fn stop_wake_word_listener(listener: State<'_, WakeWordListener>) -> Result<(), String> {
    let mut active = listener.0.lock().await;
    let cancel = active.take().ok_or_else(|| "语音唤醒尚未开启".to_string())?;
    let _ = cancel.send(true);
    Ok(())
}

#[tauri::command]
async fn continue_voice_conversation(conversation: State<'_, Arc<VoiceConversation>>) -> Result<(), String> {
    let mut state = conversation.0.lock().await;
    let resume = state.resume.take().ok_or_else(|| "当前没有等待继续的语音对话轮次".to_string())?;
    resume.send(()).map_err(|_| "语音对话已经结束".to_string())
}

#[tauri::command]
async fn stop_voice_conversation(conversation: State<'_, Arc<VoiceConversation>>) -> Result<(), String> {
    {
        let mut state = conversation.0.lock().await;
        let cancel = state.cancel.as_ref().ok_or_else(|| "语音对话尚未开启".to_string())?;
        let _ = cancel.send(true);
        if let Some(resume) = state.resume.take() { let _ = resume.send(()); }
    }
    for _ in 0..80 {
        if conversation.0.lock().await.cancel.is_none() { return Ok(()); }
        tokio::time::sleep(std::time::Duration::from_millis(25)).await;
    }
    Err("等待语音识别进程停止超时".to_string())
}

#[tauri::command]
async fn speak_response(app: AppHandle, text: String) -> Result<(), String> {
    let trimmed = text.trim();
    if trimmed.is_empty() || trimmed.chars().count() > 16_000 {
        return Err("朗读内容长度必须为 1–16000 个字符".to_string());
    }
    app.emit("voice-state", json!({ "state": "speaking" })).map_err(|e| e.to_string())?;
    let result: Result<std::process::ExitStatus, String> = async {
        let root = project_root()?;
        let executable = root.join(".build/JARVIS Voice.app/Contents/MacOS/JARVISVoice");
        let mut child = Command::new(executable)
        .arg("speak")
        .current_dir(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .kill_on_drop(true)
        .spawn()
        .map_err(|_| "无法启动本机高品质中文语音".to_string())?;
        let mut stdin = child.stdin.take().ok_or_else(|| "无法连接本机语音合成".to_string())?;
        stdin.write_all(trimmed.as_bytes()).await.map_err(|_| "无法发送朗读文本".to_string())?;
        drop(stdin);
        child.wait().await.map_err(|_| "本机语音合成未能结束".to_string())
    }.await;
    let _ = app.emit("voice-state", json!({ "state": "idle" }));
    match result {
        Ok(status) if status.success() => Ok(()),
        Ok(_) => Err("macOS 语音朗读失败。".to_string()),
        Err(error) => Err(error),
    }
}

#[tauri::command]
async fn run_agent(
    app: AppHandle,
    pending: State<'_, PendingConfirmations>,
    bridge: State<'_, AgentBridge>,
    message: String,
) -> Result<(), String> {
    if message.trim().is_empty() || message.chars().count() > 16_000 {
        return Err("请输入 1–16000 个字符".to_string());
    }

    let mut active = bridge.0.lock().await;
    if let Some(session) = active.as_mut() {
        if session.child.try_wait().map_err(|_| "无法检查 Agent 服务状态")?.is_some() {
            active.take();
        }
    }
    if active.is_none() {
        let root = project_root()?;
        let mut child = Command::new(root.join(".venv/bin/python"))
            .args(["-m", "app.desktop_bridge"])
            .current_dir(&root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .map_err(|_| "无法启动项目虚拟环境中的 Python Agent".to_string())?;
        let stdin = child.stdin.take().ok_or("无法连接 Agent 输入")?;
        let stdout = child.stdout.take().ok_or("无法连接 Agent 输出")?;
        *active = Some(BridgeSession { child, stdin, stdout: BufReader::new(stdout) });
    }

    let request = json!({ "type": "run", "text": message });
    let session = active.as_mut().ok_or("Agent 服务没有启动")?;
    session.stdin
        .write_all(format!("{request}\n").as_bytes())
        .await
        .map_err(|_| "无法向 Agent 发送请求".to_string())?;

    loop {
        let mut line = String::new();
        if session.stdout.read_line(&mut line).await.map_err(|_| "读取 Agent 事件失败")? == 0 {
            active.take();
            return Err("Agent 服务意外退出".to_string());
        }
        let event: Value = serde_json::from_str(&line).map_err(|_| "Agent 返回了无效事件")?;
        match event["type"].as_str().unwrap_or("") {
            "agent_event" => {
                let payload = event.get("payload").cloned().unwrap_or(Value::Null);
                app.emit("agent-event", payload).map_err(|e| e.to_string())?;
            }
            "mcp_status" => {
                app.emit("mcp-status", json!({
                    "connected": event["connected"],
                    "configured": event["configured"],
                })).map_err(|e| e.to_string())?;
            }
            "confirmation_required" => {
                let id = event["id"].as_str().unwrap_or("").to_string();
                if id.is_empty() {
                    continue;
                }
                let (sender, receiver) = oneshot::channel();
                pending
                    .0
                    .lock()
                    .map_err(|_| "确认队列不可用")?
                    .insert(id.clone(), sender);
                app.emit(
                    "confirmation-required",
                    json!({ "id": id, "name": event["name"], "args": event["args"] }),
                )
                .map_err(|e| e.to_string())?;
                let approved = receiver.await.unwrap_or(false);
                let reply = json!({ "type": "confirmation_response", "id": id, "approved": approved });
                session.stdin
                    .write_all(format!("{reply}\n").as_bytes())
                    .await
                    .map_err(|_| "无法回传确认结果".to_string())?;
            }
            "response" => {
                app.emit("agent-response", json!({ "text": event["text"] }))
                    .map_err(|e| e.to_string())?;
            }
            "error" => {
                app.emit("agent-error", json!({ "message": event["message"] }))
                    .map_err(|e| e.to_string())?;
            }
            "request_complete" => break,
            _ => {}
        }
    }
    if session.child.try_wait().map_err(|_| "无法检查 Agent 服务状态")?.is_some() {
        active.take();
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(PendingConfirmations::default())
        .manage(AgentBridge::default())
        .manage(VoiceCapture::default())
        .manage(WakeWordListener::default())
        .manage(Arc::new(VoiceConversation::default()))
        .invoke_handler(tauri::generate_handler![run_agent, respond_confirmation, memory_action, prepare_voice, start_voice, stop_voice, start_voice_conversation, continue_voice_conversation, stop_voice_conversation, start_wake_word_listener, stop_wake_word_listener, speak_response])
        .run(tauri::generate_context!())
        .expect("error while running JARVIS desktop pet");
}
