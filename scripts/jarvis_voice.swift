import AVFoundation
import AppKit
import ApplicationServices
import Foundation
import Speech

// The microphone is active only while wake listening or voice chat is enabled.

final class SpeechCompletion: NSObject, AVSpeechSynthesizerDelegate {
    var continuation: CheckedContinuation<Void, Never>?

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        continuation?.resume()
        continuation = nil
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        continuation?.resume()
        continuation = nil
    }
}

func fail(_ message: String, _ status: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(status)
}

func makeTranscriber(_ localeID: String) async throws -> SpeechTranscriber {
    guard let locale = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: localeID)) else {
        throw NSError(domain: "JARVISVoice", code: 1,
                      userInfo: [NSLocalizedDescriptionKey: "macOS SpeechTranscriber 不支持语言 \(localeID)。"])
    }
    return SpeechTranscriber(locale: locale, preset: .transcription)
}

func assetStatus(_ localeID: String) async throws -> String {
    let transcriber = try await makeTranscriber(localeID)
    let status = await AssetInventory.status(forModules: [transcriber])
    switch status {
    case .installed: return "installed"
    case .supported: return "supported"
    case .downloading: return "downloading"
    case .unsupported: return "unsupported"
    @unknown default: return "unknown"
    }
}

func installAssets(_ localeID: String) async throws {
    let transcriber = try await makeTranscriber(localeID)
    guard let request = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) else { return }
    try await request.downloadAndInstall()
}

func speechFriendlyText(_ text: String) -> String {
    var value = text
    value = value.replacingOccurrences(of: #"(?s)```.*?```"#, with: " ", options: .regularExpression)
    value = value.replacingOccurrences(of: #"`([^`]+)`"#, with: "$1", options: .regularExpression)
    value = value.replacingOccurrences(of: #"\[([^\]]+)\]\([^)]+\)"#, with: "$1", options: .regularExpression)
    value = value.replacingOccurrences(of: #"https?://[^\s]+"#, with: "", options: .regularExpression)
    value = value.replacingOccurrences(of: #"(?m)^\s{0,3}(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+)"#, with: "", options: .regularExpression)
    value = value.replacingOccurrences(of: #"\*\*(.*?)\*\*|__(.*?)__|\*(.*?)\*|_(.*?)_"#, with: "$1$2$3$4", options: .regularExpression)
    return value
        .components(separatedBy: .newlines)
        .map { $0.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ") }
        .filter { !$0.isEmpty }
        .joined(separator: "\n")
}

func speakLocally(_ text: String) async {
    let cleanedText = speechFriendlyText(text)
    guard !cleanedText.isEmpty else { return }
    let utterance = AVSpeechUtterance(string: cleanedText)
    utterance.voice = AVSpeechSynthesisVoice(identifier: "com.apple.ttsbundle.gryphon-neural_Linfei_zh-CN_premium")
        ?? AVSpeechSynthesisVoice(language: "zh-CN")
    utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.92
    utterance.pitchMultiplier = 1.02
    utterance.preUtteranceDelay = 0.04
    utterance.postUtteranceDelay = 0.12

    let synthesizer = AVSpeechSynthesizer()
    let completion = SpeechCompletion()
    synthesizer.delegate = completion
    await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
        completion.continuation = continuation
        synthesizer.speak(utterance)
    }
}

func ensureMicrophonePermission() async throws {
    let status = AVCaptureDevice.authorizationStatus(for: .audio)
    if status == .notDetermined {
        let granted = await withCheckedContinuation { continuation in
            AVCaptureDevice.requestAccess(for: .audio) { continuation.resume(returning: $0) }
        }
        guard granted else {
            throw NSError(domain: "JARVISVoice", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "麦克风权限未授予；请在系统设置 → 隐私与安全性 → 麦克风中允许 JARVIS Voice（通过 CLI 启动时允许 Terminal）。"])
        }
    } else if status != .authorized {
        throw NSError(domain: "JARVISVoice", code: 2,
                      userInfo: [NSLocalizedDescriptionKey: "麦克风权限未授予；请在系统设置 → 隐私与安全性 → 麦克风中允许 JARVIS Voice（通过 CLI 启动时允许 Terminal）。"])
    }
}

func transcribe(_ localeID: String, autoStopSilence: Bool = false) async throws -> String {
    try await ensureMicrophonePermission()
    let transcriber = try await makeTranscriber(localeID)
    guard await AssetInventory.status(forModules: [transcriber]) == .installed else {
        throw NSError(domain: "JARVISVoice", code: 3,
                      userInfo: [NSLocalizedDescriptionKey: "本机语音模型尚未安装。请重新运行 /voice 并同意下载模型。"])
    }
    guard let analyzerFormat = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcriber]) else {
        throw NSError(domain: "JARVISVoice", code: 4,
                      userInfo: [NSLocalizedDescriptionKey: "macOS 没有为该语言提供可用的本机音频格式。"])
    }

    let (inputSequence, inputBuilder) = AsyncStream.makeStream(of: AnalyzerInput.self)
    let analyzer = SpeechAnalyzer(modules: [transcriber])
    let converter = AnalyzerInputConverter(analyzerFormat: analyzerFormat)
    let resultsTask = Task { () throws -> String in
        var parts: [String] = []
        for try await result in transcriber.results {
            let text = String(result.text.characters).trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty { parts.append(text) }
        }
        return parts.joined(separator: " ")
    }
    let analysisTask = Task { try await analyzer.analyzeSequence(inputSequence) }

    let engine = AVAudioEngine()
    let input = engine.inputNode
    let captureFormat = input.outputFormat(forBus: 0)
    guard captureFormat.sampleRate > 0, captureFormat.channelCount > 0 else {
        await analyzer.cancelAndFinishNow()
        throw NSError(domain: "JARVISVoice", code: 5,
                      userInfo: [NSLocalizedDescriptionKey: "没有可用的麦克风输入设备。"])
    }

    let stateLock = NSLock()
    var capturedBuffers = 0
    var conversionError: String?
    var detectedSpeech = false
    var lastSpeechAt = DispatchTime.now().uptimeNanoseconds
    let recordingStartedAt = DispatchTime.now().uptimeNanoseconds
    input.installTap(onBus: 0, bufferSize: 2048, format: captureFormat) { buffer, audioTime in
        var squareSum: Float = 0
        var sampleCount = 0
        if let channels = buffer.floatChannelData {
            let frames = Int(buffer.frameLength)
            for channel in 0..<Int(captureFormat.channelCount) {
                for frame in 0..<frames {
                    let sample = channels[channel][frame]
                    squareSum += sample * sample
                }
            }
            sampleCount = frames * Int(captureFormat.channelCount)
        }
        let rms = sampleCount > 0 ? (squareSum / Float(sampleCount)).squareRoot() : 0
        let now = DispatchTime.now().uptimeNanoseconds
        stateLock.lock()
        capturedBuffers += 1
        if rms > 0.009 {
            detectedSpeech = true
            lastSpeechAt = now
        }
        stateLock.unlock()
        do {
            for item in try converter.convert(buffer, at: audioTime) {
                inputBuilder.yield(item)
            }
        } catch {
            stateLock.lock()
            conversionError = error.localizedDescription
            stateLock.unlock()
        }
    }
    do {
        engine.prepare()
        try engine.start()
    } catch {
        input.removeTap(onBus: 0)
        inputBuilder.finish()
        await analyzer.cancelAndFinishNow()
        throw NSError(domain: "JARVISVoice", code: 6,
                      userInfo: [NSLocalizedDescriptionKey: "无法启动麦克风录音：\(error.localizedDescription)"])
    }

    FileHandle.standardError.write(Data((autoStopSilence ? "录音中。检测到说话后会在短暂停顿时自动提交；最长 25 秒。\n" : "录音中。说完后按回车停止；最长 30 秒。\n").utf8))
    let stopLock = NSLock()
    var didStop = false
    let (stoppedSequence, stoppedContinuation) = AsyncStream<Void>.makeStream()
    let stopRecording = {
        stopLock.lock()
        guard !didStop else { stopLock.unlock(); return }
        didStop = true
        stopLock.unlock()
        if engine.isRunning { engine.stop() }
        input.removeTap(onBus: 0)
        do {
            for item in try converter.flush() { inputBuilder.yield(item) }
        } catch {
            stateLock.lock()
            conversionError = error.localizedDescription
            stateLock.unlock()
        }
        inputBuilder.finish()
        stoppedContinuation.yield(())
        stoppedContinuation.finish()
    }
    if autoStopSilence {
        func checkForTurnEnd() {
            let now = DispatchTime.now().uptimeNanoseconds
            stateLock.lock()
            let heardSpeech = detectedSpeech
            let silence = now - lastSpeechAt
            let elapsed = now - recordingStartedAt
            stateLock.unlock()
            if (heardSpeech && silence >= 1_500_000_000) || (!heardSpeech && elapsed >= 10_000_000_000) || elapsed >= 25_000_000_000 {
                stopRecording()
            } else {
                DispatchQueue.global().asyncAfter(deadline: .now() + 0.15, execute: checkForTurnEnd)
            }
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.15, execute: checkForTurnEnd)
        for await _ in stoppedSequence { break }
    } else {
        DispatchQueue.global().asyncAfter(deadline: .now() + 30, execute: stopRecording)
        _ = readLine()
        stopRecording()
    }

    let lastSampleTime: CMTime?
    do {
        lastSampleTime = try await analysisTask.value
        if let lastSampleTime {
            try await analyzer.finalizeAndFinish(through: lastSampleTime)
        } else {
            await analyzer.cancelAndFinishNow()
        }
    } catch {
        await analyzer.cancelAndFinishNow()
        throw NSError(domain: "JARVISVoice", code: 7,
                      userInfo: [NSLocalizedDescriptionKey: "SpeechAnalyzer 处理音频失败：\(error.localizedDescription)"])
    }

    let transcript = try await resultsTask.value.trimmingCharacters(in: .whitespacesAndNewlines)
    func captureSnapshot() -> (Int, String?) {
        stateLock.lock()
        defer { stateLock.unlock() }
        return (capturedBuffers, conversionError)
    }
    let (bufferCount, converterError) = captureSnapshot()
    guard bufferCount > 0 else {
        throw NSError(domain: "JARVISVoice", code: 8,
                      userInfo: [NSLocalizedDescriptionKey: "麦克风没有采集到音频。请检查 Terminal 的麦克风权限并在录音时说话。"])
    }
    if let converterError {
        throw NSError(domain: "JARVISVoice", code: 9,
                      userInfo: [NSLocalizedDescriptionKey: "音频格式转换失败：\(converterError)"])
    }
    guard !transcript.isEmpty else {
        throw NSError(domain: "JARVISVoice", code: 10,
                      userInfo: [NSLocalizedDescriptionKey: "麦克风已采到音频，但 SpeechAnalyzer 没有识别出文字。请靠近麦克风再说一句完整短句。"])
    }
    return transcript
}

struct AccessibilityRequest: Decodable {
    var command: String
    var processID: pid_t?
    var windowIndex: Int?
    var path: [Int]?
    var action: String?
    var value: String?
    var expectedRole: String?
    var expectedIdentifier: String?
    var expectedTitle: String?
    var expectedDescription: String?
    var expectedBundleID: String?
}

func axValue(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return nil }
    return value
}

func axText(_ element: AXUIElement, _ name: String) -> String? {
    guard let value = axValue(element, name) else { return nil }
    if let text = value as? String { return String(text.prefix(300)) }
    if let number = value as? NSNumber { return number.stringValue }
    return nil
}

func axElement(_ raw: CFTypeRef) -> AXUIElement { raw as! AXUIElement }

func axWindows(_ app: AXUIElement) -> [AXUIElement] {
    guard let raw = axValue(app, kAXWindowsAttribute as String),
          let values = raw as? [AXUIElement] else { return [] }
    return values
}

func focusedApplication() throws -> (AXUIElement, pid_t) {
    let system = AXUIElementCreateSystemWide()
    guard let raw = axValue(system, kAXFocusedApplicationAttribute as String) else {
        throw NSError(domain: "JARVISAccessibility", code: 1,
                      userInfo: [NSLocalizedDescriptionKey: "无法读取当前应用。请先打开一个普通应用窗口，并授予 JARVIS Voice 辅助功能权限。"])
    }
    let app = axElement(raw)
    var pid: pid_t = 0
    guard AXUIElementGetPid(app, &pid) == .success, pid > 0 else {
        throw NSError(domain: "JARVISAccessibility", code: 2,
                      userInfo: [NSLocalizedDescriptionKey: "无法读取当前应用进程。"])
    }
    return (app, pid)
}

func inspectAccessibilityTree() throws -> [String: Any] {
    guard AXIsProcessTrusted() else {
        throw NSError(domain: "JARVISAccessibility", code: 3,
                      userInfo: [NSLocalizedDescriptionKey: "JARVIS Voice 尚未获得辅助功能权限。请在系统设置 → 隐私与安全性 → 辅助功能中启用 JARVIS Voice，然后重启 JARVIS。"])
    }
    let (app, pid) = try focusedApplication()
    let windows = axWindows(app)
    guard !windows.isEmpty else {
        throw NSError(domain: "JARVISAccessibility", code: 4,
                      userInfo: [NSLocalizedDescriptionKey: "当前应用没有可访问的窗口。"])
    }
    let focusedWindow = axValue(app, kAXFocusedWindowAttribute as String).map(axElement)
    let windowIndex = focusedWindow.flatMap { focused in
        windows.firstIndex(where: { CFEqual($0 as CFTypeRef, focused as CFTypeRef) })
    } ?? 0
    let window = windows[windowIndex]
    let workspaceApp = NSRunningApplication(processIdentifier: pid)
    var nodes: [[String: Any]] = []
    func walk(_ element: AXUIElement, _ path: [Int], _ depth: Int) {
        guard nodes.count < 100, depth <= 6 else { return }
        let role = axText(element, kAXRoleAttribute as String) ?? "unknown"
        let identifier = axText(element, kAXIdentifierAttribute as String)
        let title = axText(element, kAXTitleAttribute as String)
        let label = axText(element, kAXDescriptionAttribute as String)
        let secure = axText(element, kAXSubroleAttribute as String) == (kAXSecureTextFieldSubrole as String)
        var node: [String: Any] = ["path": path, "role": role]
        if let identifier, !identifier.isEmpty { node["identifier"] = identifier }
        if let title, !title.isEmpty { node["title"] = title }
        if let label, !label.isEmpty { node["description"] = label }
        if !secure, let value = axText(element, kAXValueAttribute as String), !value.isEmpty {
            node["value"] = value
        }
        if let enabled = axValue(element, kAXEnabledAttribute as String) as? NSNumber {
            node["enabled"] = enabled.boolValue
        }
        nodes.append(node)
        guard depth < 6, let raw = axValue(element, kAXChildrenAttribute as String),
              let children = raw as? [AXUIElement] else { return }
        for (index, child) in children.prefix(40).enumerated() {
            walk(child, path + [index], depth + 1)
            if nodes.count >= 100 { break }
        }
    }
    walk(window, [], 0)
    return ["process_id": pid,
            "application": workspaceApp?.localizedName ?? "未知应用",
            "bundle_id": workspaceApp?.bundleIdentifier ?? "",
            "window_index": windowIndex,
            "window": axText(window, kAXTitleAttribute as String) ?? "",
            "elements": nodes,
            "truncated": nodes.count >= 100]
}

func performAccessibilityAction(_ request: AccessibilityRequest) throws -> [String: Any] {
    guard AXIsProcessTrusted() else {
        throw NSError(domain: "JARVISAccessibility", code: 5,
                      userInfo: [NSLocalizedDescriptionKey: "JARVIS Voice 尚未获得辅助功能权限。"])
    }
    guard let pid = request.processID, let path = request.path else {
        throw NSError(domain: "JARVISAccessibility", code: 6,
                      userInfo: [NSLocalizedDescriptionKey: "缺少目标应用或控件路径。"])
    }
    let app = AXUIElementCreateApplication(pid)
    let windows = axWindows(app)
    let windowIndex = request.windowIndex ?? 0
    guard windows.indices.contains(windowIndex) else {
        throw NSError(domain: "JARVISAccessibility", code: 7,
                      userInfo: [NSLocalizedDescriptionKey: "目标窗口已变化，请重新检查当前窗口。"])
    }
    var target = windows[windowIndex]
    for index in path {
        guard let raw = axValue(target, kAXChildrenAttribute as String),
              let children = raw as? [AXUIElement], children.indices.contains(index) else {
            throw NSError(domain: "JARVISAccessibility", code: 8,
                          userInfo: [NSLocalizedDescriptionKey: "目标控件已变化，请重新检查当前窗口。"])
        }
        target = children[index]
    }
    let role = axText(target, kAXRoleAttribute as String) ?? "unknown"
    let identifier = axText(target, kAXIdentifierAttribute as String) ?? ""
    let title = axText(target, kAXTitleAttribute as String) ?? ""
    let description = axText(target, kAXDescriptionAttribute as String) ?? ""
    let actualBundleID = NSRunningApplication(processIdentifier: pid)?.bundleIdentifier ?? ""
    let hasStableLabel = !(request.expectedIdentifier ?? "").isEmpty
        || !(request.expectedTitle ?? "").isEmpty
        || !(request.expectedDescription ?? "").isEmpty
    guard request.expectedRole == role,
          request.expectedIdentifier == nil || request.expectedIdentifier == identifier,
          request.expectedTitle == nil || request.expectedTitle == title,
          request.expectedDescription == nil || request.expectedDescription == description,
          request.expectedBundleID == nil || request.expectedBundleID == actualBundleID,
          hasStableLabel || !description.isEmpty else {
        throw NSError(domain: "JARVISAccessibility", code: 9,
                      userInfo: [NSLocalizedDescriptionKey: "目标控件与检查时不一致，请重新检查后再操作。"])
    }
    switch request.action ?? "" {
    case "press":
        let result = AXUIElementPerformAction(target, kAXPressAction as CFString)
        guard result == .success else {
            throw NSError(domain: "JARVISAccessibility", code: 10,
                          userInfo: [NSLocalizedDescriptionKey: "当前控件不支持辅助功能点击（错误码 \(result.rawValue)）。"])
        }
    case "focus":
        let result = AXUIElementSetAttributeValue(target, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        guard result == .success else {
            throw NSError(domain: "JARVISAccessibility", code: 11,
                          userInfo: [NSLocalizedDescriptionKey: "无法将焦点移到该控件（错误码 \(result.rawValue)）。"])
        }
    case "set_text":
        let subrole = axText(target, kAXSubroleAttribute as String) ?? ""
        guard (role == (kAXTextFieldRole as String) || role == (kAXTextAreaRole as String) || role == (kAXComboBoxRole as String)),
              subrole != (kAXSecureTextFieldSubrole as String),
              let value = request.value, value.count <= 500 else {
            throw NSError(domain: "JARVISAccessibility", code: 12,
                          userInfo: [NSLocalizedDescriptionKey: "只允许向普通文本框、文本区域或组合框输入最多 500 个字符。"])
        }
        var settable = DarwinBoolean(false)
        let check = AXUIElementIsAttributeSettable(target, kAXValueAttribute as CFString, &settable)
        guard check == .success, settable.boolValue else {
            throw NSError(domain: "JARVISAccessibility", code: 13,
                          userInfo: [NSLocalizedDescriptionKey: "目标控件不允许设置文字。"])
        }
        let result = AXUIElementSetAttributeValue(target, kAXValueAttribute as CFString, value as CFTypeRef)
        guard result == .success else {
            throw NSError(domain: "JARVISAccessibility", code: 14,
                          userInfo: [NSLocalizedDescriptionKey: "输入文字失败（错误码 \(result.rawValue)）。"])
        }
    default:
        throw NSError(domain: "JARVISAccessibility", code: 15,
                      userInfo: [NSLocalizedDescriptionKey: "不支持的控件操作。"])
    }
    return ["ok": true, "action": request.action ?? "", "role": role]
}

func runAccessibilityCommand() throws {
    let data = FileHandle.standardInput.readDataToEndOfFile()
    let request = try JSONDecoder().decode(AccessibilityRequest.self, from: data)
    let response: [String: Any]
    switch request.command {
    case "status":
        response = ["accessibility": AXIsProcessTrusted(),
                    "screen_capture": CGPreflightScreenCaptureAccess(),
                    "input_control": CGPreflightPostEventAccess()]
    case "inspect": response = try inspectAccessibilityTree()
    case "act": response = try performAccessibilityAction(request)
    default:
        throw NSError(domain: "JARVISAccessibility", code: 16,
                      userInfo: [NSLocalizedDescriptionKey: "不支持的辅助功能命令。"])
    }
    let output = try JSONSerialization.data(withJSONObject: response, options: [.sortedKeys])
    FileHandle.standardOutput.write(output)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

@main
struct VoiceHelper {
    static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 2 else { fail("用法错误") }
        let command = args[1]
        let localeID = args.count > 2 ? args[2] : "zh-CN"
        do {
            switch command {
            case "asset-status": print(try await assetStatus(localeID))
            case "install-assets": try await installAssets(localeID)
            case "transcribe": print(try await transcribe(localeID))
            case "transcribe-auto": print(try await transcribe(localeID, autoStopSilence: true))
            case "speak":
                let data = FileHandle.standardInput.readDataToEndOfFile()
                guard let text = String(data: data, encoding: .utf8), !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                    fail("没有可朗读的文字。")
                }
                await speakLocally(text)
            case "permissions":
                print("microphone=\(AVCaptureDevice.authorizationStatus(for: .audio).rawValue)")
                let locales = await SpeechTranscriber.installedLocales.map(\.identifier).joined(separator: ",")
                print("transcriber_locales=\(locales)")
            case "accessibility": try runAccessibilityCommand()
            default: fail("用法错误")
            }
        } catch {
            fail(error.localizedDescription)
        }
    }
}
