import AVFoundation
import Foundation
import Speech
import SherpaOnnx

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

func requiredPath(_ key: String) -> String {
    guard let value = ProcessInfo.processInfo.environment[key], !value.isEmpty else {
        fail("缺少环境变量 \(key)")
    }
    return value
}

@available(macOS 27, *)
func transcribeBufferedAudio(_ samples: [Float]) async throws -> String {
    guard let locale = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: "zh-CN")) else {
        throw NSError(domain: "JarvisKWS", code: 1, userInfo: [NSLocalizedDescriptionKey: "macOS 不支持中文本机语音识别。"])
    }
    let transcriber = SpeechTranscriber(locale: locale, preset: .transcription)
    guard await AssetInventory.status(forModules: [transcriber]) == .installed else {
        throw NSError(domain: "JarvisKWS", code: 2, userInfo: [NSLocalizedDescriptionKey: "中文本机语音模型尚未安装；请先在 JARVIS 桌面应用中启用一次中文语音识别。"])
    }
    guard let analyzerFormat = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcriber]),
          let sourceFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false),
          let buffer = AVAudioPCMBuffer(pcmFormat: sourceFormat, frameCapacity: AVAudioFrameCount(samples.count)) else {
        throw NSError(domain: "JarvisKWS", code: 3, userInfo: [NSLocalizedDescriptionKey: "无法准备本机语音识别音频格式。"])
    }
    buffer.frameLength = buffer.frameCapacity
    samples.withUnsafeBufferPointer { source in
        if let base = source.baseAddress, let target = buffer.floatChannelData?[0] {
            target.update(from: base, count: source.count)
        }
    }

    let (sequence, builder) = AsyncStream.makeStream(of: AnalyzerInput.self)
    let analyzer = SpeechAnalyzer(modules: [transcriber])
    let converter = AnalyzerInputConverter(analyzerFormat: analyzerFormat)
    let resultsTask = Task { () -> String in
        var results: [String] = []
        for try await result in transcriber.results {
            let text = String(result.text.characters).trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty { results.append(text) }
        }
        return results.joined(separator: " ")
    }
    let analysisTask = Task { try await analyzer.analyzeSequence(sequence) }
    do {
        for item in try converter.convert(buffer, at: nil) { builder.yield(item) }
        for item in try converter.flush() { builder.yield(item) }
        builder.finish()
        if let lastSampleTime = try await analysisTask.value {
            try await analyzer.finalizeAndFinish(through: lastSampleTime)
        } else {
            await analyzer.cancelAndFinishNow()
        }
    } catch {
        builder.finish()
        await analyzer.cancelAndFinishNow()
        throw error
    }
    return try await resultsTask.value
}

func run() throws {
    let model = requiredPath("JARVIS_KWS_MODEL_DIR")
    let keywords = requiredPath("JARVIS_KWS_KEYWORDS")
    let encoder = URL(fileURLWithPath: model).appendingPathComponent("encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx").path
    let decoder = URL(fileURLWithPath: model).appendingPathComponent("decoder-epoch-13-avg-2-chunk-16-left-64.onnx").path
    let joiner = URL(fileURLWithPath: model).appendingPathComponent("joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx").path
    let tokens = URL(fileURLWithPath: model).appendingPathComponent("tokens.txt").path
    for path in [encoder, decoder, joiner, tokens, keywords] where !FileManager.default.fileExists(atPath: path) {
        fail("关键词模型文件不存在：\(path)")
    }

    let transducer = sherpaOnnxOnlineTransducerModelConfig(encoder: encoder, decoder: decoder, joiner: joiner)
    let modelConfig = sherpaOnnxOnlineModelConfig(tokens: tokens, transducer: transducer, numThreads: 2, provider: "cpu")
    let featureConfig = sherpaOnnxFeatureConfig(sampleRate: 16000, featureDim: 80)
    var config = sherpaOnnxKeywordSpotterConfig(
        featConfig: featureConfig,
        modelConfig: modelConfig,
        keywordsFile: keywords
    )
    let spotter = SherpaOnnxKeywordSpotterWrapper(config: &config)

    let engine = AVAudioEngine()
    let input = engine.inputNode
    let sourceFormat = input.outputFormat(forBus: 0)
    guard sourceFormat.sampleRate > 0, sourceFormat.channelCount > 0,
          let targetFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false),
          let converter = AVAudioConverter(from: sourceFormat, to: targetFormat) else {
        fail("无法建立麦克风音频格式转换器")
    }

    let queue = DispatchQueue(label: "com.jarvis.kws.decode")
    let ringLock = NSLock()
    var recentSamples: [Float] = []
    var detectedAt: DispatchTime?
    var lastSpeechAt: UInt64?
    var finishing = false
    input.installTap(onBus: 0, bufferSize: 2048, format: sourceFormat) { buffer, _ in
        let ratio = 16000.0 / sourceFormat.sampleRate
        let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * ratio) + 16)
        guard let converted = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity) else { return }
        var supplied = false
        var conversionError: NSError?
        let status = converter.convert(to: converted, error: &conversionError) { _, outStatus in
            if supplied {
                outStatus.pointee = .noDataNow
                return nil
            }
            supplied = true
            outStatus.pointee = .haveData
            return buffer
        }
        guard status != .error, let samples = converted.floatChannelData?[0], converted.frameLength > 0 else { return }
        let chunk = Array(UnsafeBufferPointer(start: samples, count: Int(converted.frameLength)))
        let rms = (chunk.reduce(Float.zero) { $0 + $1 * $1 } / Float(chunk.count)).squareRoot()
        let now = DispatchTime.now().uptimeNanoseconds
        ringLock.lock()
        if !finishing {
            recentSamples.append(contentsOf: chunk)
            if detectedAt != nil && rms > 0.008 { lastSpeechAt = now }
            let maxSamples = 12 * 16000
            if recentSamples.count > maxSamples {
                recentSamples.removeFirst(recentSamples.count - maxSamples)
            }
        }
        ringLock.unlock()
        queue.async {
            ringLock.lock()
            let currentTime = DispatchTime.now().uptimeNanoseconds
            let shouldFinish = detectedAt.map { triggerTime in
                let sinceTrigger = currentTime - triggerTime.uptimeNanoseconds
                if sinceTrigger >= 8_000_000_000 { return true }
                if let lastSpeechAt { return currentTime - lastSpeechAt >= 1_000_000_000 }
                return sinceTrigger >= 1_500_000_000
            } ?? false
            if shouldFinish && !finishing { finishing = true }
            let shouldTranscribe = finishing && shouldFinish
            let audio = shouldTranscribe ? recentSamples : []
            ringLock.unlock()
            if shouldTranscribe {
                engine.stop()
                input.removeTap(onBus: 0)
                Task {
                    do {
                        guard #available(macOS 27, *) else {
                            fail("唤醒词检测成功，但无损交接同句语音需要 macOS 27 或更新版本。")
                        }
                        let transcript = try await transcribeBufferedAudio(audio)
                        FileHandle.standardOutput.write(Data(("WAKE_WORD_DETECTED:\(transcript)\n").utf8))
                        fflush(stdout)
                        exit(0)
                    } catch {
                        fail("唤醒后本机语音识别失败：\(error.localizedDescription)")
                    }
                }
                return
            }
            spotter.acceptWaveform(samples: chunk, sampleRate: 16000)
            while spotter.isReady() {
                spotter.decode()
                let keyword = spotter.getResult().keyword
                if !keyword.isEmpty {
                    spotter.reset()
                    ringLock.lock()
                    if detectedAt == nil { detectedAt = .now() }
                    ringLock.unlock()
                }
            }
        }
    }
    do {
        try engine.start()
    } catch {
        input.removeTap(onBus: 0)
        throw error
    }
    FileHandle.standardError.write(Data("专用关键词检测正在监听。按 Ctrl+C 停止。\n".utf8))
    dispatchMain()
}

do {
    try run()
} catch {
    fail("关键词检测启动失败：\(error.localizedDescription)")
}
