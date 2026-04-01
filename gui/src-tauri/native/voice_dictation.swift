import AVFoundation
import Foundation

struct CaptureResult: Codable {
  let audioPath: String?
  let error: String?
}

enum CaptureError: LocalizedError {
  case microphoneNotAuthorized
  case microphoneRestricted
  case recorderUnavailable
  case noSpeechDetected

  var errorDescription: String? {
    switch self {
    case .microphoneNotAuthorized:
      return "Microphone permission is denied for LLMOS."
    case .microphoneRestricted:
      return "Microphone access is restricted on this Mac."
    case .recorderUnavailable:
      return "Native audio capture is unavailable right now."
    case .noSpeechDetected:
      return "No speech was detected."
    }
  }
}

struct Options {
  var maxDuration = TimeInterval(10)
  var silenceTimeout = TimeInterval(1.2)
  var speechThresholdDb = Float(-28)

  init(arguments: [String]) {
    var index = 0
    while index < arguments.count {
      let argument = arguments[index]
      switch argument {
      case "--max-duration-ms":
        if index + 1 < arguments.count, let value = Double(arguments[index + 1]) {
          maxDuration = value / 1000
          index += 1
        }
      case "--silence-timeout-ms":
        if index + 1 < arguments.count, let value = Double(arguments[index + 1]) {
          silenceTimeout = value / 1000
          index += 1
        }
      case "--speech-threshold-db":
        if index + 1 < arguments.count, let value = Float(arguments[index + 1]) {
          speechThresholdDb = value
          index += 1
        }
      default:
        break
      }
      index += 1
    }
  }
}

final class AudioCaptureRunner: NSObject, AVAudioRecorderDelegate {
  private let options: Options
  private var recorder: AVAudioRecorder?
  private var timer: Timer?
  private var startedAt = Date()
  private var lastSpeechAt: Date?
  private var detectedSpeech = false
  private var completed = false
  private var outputURL: URL?

  init(options: Options) {
    self.options = options
  }

  func run() {
    requestMicrophoneAuthorization { [weak self] result in
      guard let self else { return }
      switch result {
      case .success:
        self.startRecording()
      case .failure(let error):
        self.finish(withError: error.localizedDescription)
      }
    }

    RunLoop.main.run()
  }

  private func requestMicrophoneAuthorization(
    completion: @escaping (Result<Void, Error>) -> Void
  ) {
    switch AVCaptureDevice.authorizationStatus(for: .audio) {
    case .authorized:
      completion(.success(()))
    case .denied:
      completion(.failure(CaptureError.microphoneNotAuthorized))
    case .restricted:
      completion(.failure(CaptureError.microphoneRestricted))
    case .notDetermined:
      AVCaptureDevice.requestAccess(for: .audio) { granted in
        DispatchQueue.main.async {
          if granted {
            completion(.success(()))
          } else {
            completion(.failure(CaptureError.microphoneNotAuthorized))
          }
        }
      }
    @unknown default:
      completion(.failure(CaptureError.microphoneNotAuthorized))
    }
  }

  private func startRecording() {
    let outputURL = FileManager.default.temporaryDirectory
      .appendingPathComponent("llmos-voice-\(UUID().uuidString)")
      .appendingPathExtension("wav")

    let settings: [String: Any] = [
      AVFormatIDKey: kAudioFormatLinearPCM,
      AVSampleRateKey: 16_000,
      AVNumberOfChannelsKey: 1,
      AVLinearPCMBitDepthKey: 16,
      AVLinearPCMIsBigEndianKey: false,
      AVLinearPCMIsFloatKey: false,
      AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
    ]

    do {
      let recorder = try AVAudioRecorder(url: outputURL, settings: settings)
      recorder.delegate = self
      recorder.isMeteringEnabled = true

      guard recorder.prepareToRecord(), recorder.record() else {
        finish(withError: CaptureError.recorderUnavailable.localizedDescription)
        return
      }

      self.outputURL = outputURL
      self.recorder = recorder
      self.startedAt = Date()
      self.lastSpeechAt = nil
      self.detectedSpeech = false

      timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
        self?.pollRecording()
      }
    } catch {
      finish(withError: "Failed to start audio capture: \(error.localizedDescription)")
    }
  }

  private func pollRecording() {
    guard let recorder else {
      finish(withError: CaptureError.recorderUnavailable.localizedDescription)
      return
    }

    if completed {
      return
    }

    recorder.updateMeters()
    let averagePower = recorder.averagePower(forChannel: 0)
    let now = Date()

    if averagePower >= options.speechThresholdDb {
      detectedSpeech = true
      lastSpeechAt = now
    }

    if now.timeIntervalSince(startedAt) >= options.maxDuration {
      stopAndFinalize()
      return
    }

    if detectedSpeech,
       let lastSpeechAt,
       now.timeIntervalSince(lastSpeechAt) >= options.silenceTimeout {
      stopAndFinalize()
    }
  }

  private func stopAndFinalize() {
    guard !completed else { return }
    recorder?.stop()
    finishCapture()
  }

  private func finishCapture() {
    guard !completed else { return }

    cleanup()

    guard detectedSpeech, let outputURL else {
      finish(withError: CaptureError.noSpeechDetected.localizedDescription)
      return
    }

    emitAndExit(CaptureResult(audioPath: outputURL.path, error: nil), exitCode: 0)
  }

  private func cleanup() {
    guard !completed else { return }
    completed = true

    timer?.invalidate()
    timer = nil

    recorder?.stop()
    recorder = nil
  }

  private func finish(withError error: String?) {
    let path = outputURL?.path
    cleanup()

    if let path {
      try? FileManager.default.removeItem(atPath: path)
    }

    emitAndExit(CaptureResult(audioPath: nil, error: error ?? "Native audio capture failed."), exitCode: 1)
  }

  private func emitAndExit(_ result: CaptureResult, exitCode: Int32) {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.withoutEscapingSlashes]

    if let data = try? encoder.encode(result),
       let string = String(data: data, encoding: .utf8) {
      FileHandle.standardOutput.write(Data(string.utf8))
      FileHandle.standardOutput.write(Data("\n".utf8))
    }

    CFRunLoopStop(CFRunLoopGetMain())
    exit(exitCode)
  }

  func audioRecorderEncodeErrorDidOccur(_ recorder: AVAudioRecorder, error: Error?) {
    finish(withError: error?.localizedDescription ?? "Audio recorder failed.")
  }
}

let options = Options(arguments: Array(CommandLine.arguments.dropFirst()))
AudioCaptureRunner(options: options).run()
