use serde::Serialize;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};

const STATUS_EVENT: &str = "voice://status-changed";
const WAKE_EVENT: &str = "voice://wake-detected";
const DEFAULT_WAKE_PHRASE: &str = "Hey Shell";

#[derive(Default)]
pub struct VoiceState(Mutex<VoiceStateInner>);

#[derive(Clone, Debug)]
struct VoiceStateInner {
    enabled: bool,
    wake_phrase: String,
    last_error: Option<String>,
}

impl Default for VoiceStateInner {
    fn default() -> Self {
        Self {
            enabled: false,
            wake_phrase: DEFAULT_WAKE_PHRASE.to_string(),
            last_error: None,
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct VoiceStatusPayload {
    supported: bool,
    enabled: bool,
    wake_phrase: String,
    last_error: Option<String>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct VoiceWakePayload {
    phrase: String,
}

impl VoiceState {
    fn snapshot(&self) -> VoiceStatusPayload {
        self.0.lock().unwrap().to_payload(platform::is_supported())
    }
}

impl VoiceStateInner {
    fn to_payload(&self, supported: bool) -> VoiceStatusPayload {
        VoiceStatusPayload {
            supported,
            enabled: self.enabled,
            wake_phrase: self.wake_phrase.clone(),
            last_error: self.last_error.clone(),
        }
    }
}

#[tauri::command]
pub fn voice_get_status(state: State<'_, VoiceState>) -> VoiceStatusPayload {
    state.snapshot()
}

#[tauri::command]
pub fn voice_set_enabled(
    app: AppHandle,
    state: State<'_, VoiceState>,
    enabled: bool,
) -> Result<VoiceStatusPayload, String> {
    let wake_phrase = {
        let guard = state.0.lock().unwrap();
        guard.wake_phrase.clone()
    };

    let result = platform::set_enabled(app.clone(), enabled, wake_phrase);

    let mut guard = state.0.lock().unwrap();
    match result {
        Ok(()) => {
            guard.enabled = enabled;
            guard.last_error = None;
        }
        Err(ref error) => {
            guard.enabled = false;
            guard.last_error = Some(error.clone());
        }
    }

    let payload = guard.to_payload(platform::is_supported());
    drop(guard);

    let _ = app.emit(STATUS_EVENT, &payload);

    result.map(|_| payload)
}

#[tauri::command]
pub async fn voice_transcribe_once(app: AppHandle) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || platform::transcribe_once(&app))
        .await
        .map_err(|error| format!("Native dictation task failed: {error}"))?
}

pub fn shutdown(app: &AppHandle) {
    let _ = platform::set_enabled(app.clone(), false, DEFAULT_WAKE_PHRASE.to_string());
}

fn reveal_main_window(app: &AppHandle) {
    #[cfg(target_os = "macos")]
    let _ = app.show();

    if let Some(window) = app.get_webview_window("main") {
        let _ = window.center();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn emit_wake_detected(app: &AppHandle, phrase: String) {
    reveal_main_window(app);
    let _ = app.emit(WAKE_EVENT, VoiceWakePayload { phrase });
}

#[cfg(target_os = "macos")]
mod platform {
    use super::emit_wake_detected;
    use objc2::rc::Retained;
    use objc2::runtime::{NSObject, NSObjectProtocol, ProtocolObject};
    use objc2::{define_class, msg_send, DefinedClass, MainThreadMarker, MainThreadOnly};
    use objc2_app_kit::{NSSpeechRecognizer, NSSpeechRecognizerDelegate};
    use objc2_foundation::{NSArray, NSString};
    use serde::Deserialize;
    use std::cell::RefCell;
    use std::fs;
    use std::path::PathBuf;
    use std::process::Command;
    use std::sync::mpsc;
    use tauri::{AppHandle, Manager};

    thread_local! {
        static MAC_WAKE_RUNTIME: RefCell<Option<MacWakeRuntime>> = const { RefCell::new(None) };
    }

    struct MacWakeRuntime {
        recognizer: Retained<NSSpeechRecognizer>,
        delegate: Retained<WakeRecognizerDelegate>,
    }

    #[derive(Deserialize)]
    #[serde(rename_all = "camelCase")]
    struct NativeCaptureResult {
        audio_path: Option<String>,
        error: Option<String>,
    }

    #[derive(Debug)]
    struct WakeRecognizerDelegateIvars {
        app: AppHandle,
    }

    define_class!(
        #[unsafe(super = NSObject)]
        #[thread_kind = MainThreadOnly]
        #[ivars = WakeRecognizerDelegateIvars]
        struct WakeRecognizerDelegate;

        unsafe impl NSObjectProtocol for WakeRecognizerDelegate {}

        unsafe impl NSSpeechRecognizerDelegate for WakeRecognizerDelegate {
            #[unsafe(method(speechRecognizer:didRecognizeCommand:))]
            fn speech_recognizer_did_recognize_command(
                &self,
                _sender: &NSSpeechRecognizer,
                command: &NSString,
            ) {
                emit_wake_detected(&self.ivars().app, command.to_string());
            }
        }
    );

    impl WakeRecognizerDelegate {
        fn new(mtm: MainThreadMarker, app: AppHandle) -> Retained<Self> {
            let this = Self::alloc(mtm).set_ivars(WakeRecognizerDelegateIvars { app });
            unsafe { msg_send![super(this), init] }
        }
    }

    pub fn is_supported() -> bool {
        true
    }

    pub fn set_enabled(app: AppHandle, enabled: bool, wake_phrase: String) -> Result<(), String> {
        let (sender, receiver) = mpsc::channel();
        let app_handle = app.clone();

        app.run_on_main_thread(move || {
            let result = set_enabled_on_main_thread(app_handle, enabled, wake_phrase);
            let _ = sender.send(result);
        })
        .map_err(|error| error.to_string())?;

        receiver
            .recv()
            .map_err(|_| "Failed to receive macOS voice listener result.".to_string())?
    }

    fn set_enabled_on_main_thread(
        app: AppHandle,
        enabled: bool,
        wake_phrase: String,
    ) -> Result<(), String> {
        if enabled {
            start_listener(app, wake_phrase)
        } else {
            stop_listener();
            Ok(())
        }
    }

    fn start_listener(app: AppHandle, wake_phrase: String) -> Result<(), String> {
        let mtm = MainThreadMarker::new()
            .ok_or_else(|| "Wake listening must be initialized on the main thread.".to_string())?;

        MAC_WAKE_RUNTIME.with(|runtime| {
            if let Some(existing) = runtime.borrow_mut().take() {
                existing.recognizer.stopListening();
                existing.recognizer.setDelegate(None);
            }

            let delegate = WakeRecognizerDelegate::new(mtm, app);
            let recognizer = NSSpeechRecognizer::new();
            let phrase = NSString::from_str(&wake_phrase);
            let commands = NSArray::from_slice(&[&*phrase]);
            let title = NSString::from_str("ShellMind Voice Commands");

            recognizer.setCommands(Some(&commands));
            recognizer.setDisplayedCommandsTitle(Some(&title));
            recognizer.setListensInForegroundOnly(false);
            recognizer.setBlocksOtherRecognizers(false);
            recognizer.setDelegate(Some(ProtocolObject::from_ref(&*delegate)));
            recognizer.startListening();

            *runtime.borrow_mut() = Some(MacWakeRuntime {
                recognizer,
                delegate,
            });

            Ok(())
        })
    }

    pub fn transcribe_once(app: &AppHandle) -> Result<String, String> {
        let helper = native_dictation_helper_path(app)?;
        let capture_output = Command::new(&helper)
            .args([
                "--silence-timeout-ms",
                "1200",
                "--max-duration-ms",
                "10000",
                "--speech-threshold-db",
                "-28",
            ])
            .output()
            .map_err(|error| format!("Failed to start native audio capture helper: {error}"))?;

        let stdout = String::from_utf8(capture_output.stdout)
            .map_err(|_| "Native audio capture helper returned invalid UTF-8.".to_string())?;

        let payload: NativeCaptureResult = serde_json::from_str(stdout.trim()).map_err(|_| {
            format!(
                "Native audio capture helper returned invalid JSON: {}",
                stdout.trim()
            )
        })?;

        if !capture_output.status.success() {
            return Err(payload
                .error
                .unwrap_or_else(|| "Native audio capture failed.".to_string()));
        }

        let audio_path = payload
            .audio_path
            .map(PathBuf::from)
            .ok_or_else(|| "Native audio capture returned no audio file.".to_string())?;

        let whisper_cli = whisper_cli_path()?;
        let whisper_model = whisper_model_path()?;
        let output_prefix = std::env::temp_dir()
            .join(format!("llmos-whisper-{}", std::process::id()))
            .join(format!("{}", uuid_like_timestamp()));
        let thread_count = std::thread::available_parallelism()
            .map(|value| value.get().clamp(4, 8))
            .unwrap_or(4)
            .to_string();

        if let Some(parent) = output_prefix.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("Failed to prepare Whisper output directory: {error}"))?;
        }

        let whisper_output = Command::new(&whisper_cli)
            .args([
                "-m",
                whisper_model
                    .to_str()
                    .ok_or_else(|| "Whisper model path is not valid UTF-8.".to_string())?,
                "-f",
                audio_path
                    .to_str()
                    .ok_or_else(|| "Captured audio path is not valid UTF-8.".to_string())?,
                "-l",
                "en",
                "-t",
                &thread_count,
                "-otxt",
                "-of",
                output_prefix
                    .to_str()
                    .ok_or_else(|| "Whisper output path is not valid UTF-8.".to_string())?,
                "-np",
                "-nt",
                "-ng",
            ])
            .output()
            .map_err(|error| format!("Failed to start whisper-cli: {error}"))?;

        let transcript_path = output_prefix.with_extension("txt");
        let transcript = fs::read_to_string(&transcript_path).map_err(|_| {
            let stderr = String::from_utf8_lossy(&whisper_output.stderr);
            let stdout = String::from_utf8_lossy(&whisper_output.stdout);
            format!(
                "Whisper transcription failed. stdout: {} stderr: {}",
                stdout.trim(),
                stderr.trim()
            )
        })?;

        let _ = fs::remove_file(&audio_path);
        let _ = fs::remove_file(&transcript_path);

        let cleaned = transcript.trim().to_string();
        if cleaned.is_empty() {
            Err("Whisper returned an empty transcript.".to_string())
        } else {
            Ok(cleaned)
        }
    }

    fn native_dictation_helper_path(app: &AppHandle) -> Result<PathBuf, String> {
        let source_candidate = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/macos/voice-dictation-helper");
        if source_candidate.exists() {
            return Ok(source_candidate);
        }

        if let Ok(current_exe) = std::env::current_exe() {
            if let Some(parent) = current_exe.parent() {
                let bundled_candidate = parent.join("voice-dictation-helper");
                if bundled_candidate.exists() {
                    return Ok(bundled_candidate);
                }
            }
        }

        if let Ok(resource_dir) = app.path().resource_dir() {
            let resource_candidate = resource_dir.join("macos/voice-dictation-helper");
            if resource_candidate.exists() {
                return Ok(resource_candidate);
            }
        }

        Err("Unable to locate the native dictation helper.".to_string())
    }

    fn whisper_cli_path() -> Result<PathBuf, String> {
        if let Ok(path) = std::env::var("LLMOS_WHISPER_CLI") {
            let candidate = PathBuf::from(path);
            if candidate.exists() {
                return Ok(candidate);
            }
        }

        for candidate in [
            PathBuf::from("/opt/homebrew/bin/whisper-cli"),
            PathBuf::from("/usr/local/bin/whisper-cli"),
        ] {
            if candidate.exists() {
                return Ok(candidate);
            }
        }

        Err("Unable to locate whisper-cli. Install whisper-cpp or set LLMOS_WHISPER_CLI.".to_string())
    }

    fn whisper_model_path() -> Result<PathBuf, String> {
        if let Ok(path) = std::env::var("LLMOS_WHISPER_MODEL") {
            let candidate = PathBuf::from(path);
            if candidate.exists() {
                return Ok(candidate);
            }
        }

        let candidates = [
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("resources/models/ggml-base.en-q5_1.bin"),
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("resources/models/ggml-base.en.bin"),
            PathBuf::from("/opt/homebrew/opt/whisper-cpp/share/whisper-cpp/ggml-base.en-q5_1.bin"),
            PathBuf::from("/opt/homebrew/opt/whisper-cpp/share/whisper-cpp/ggml-base.en.bin"),
            PathBuf::from("/opt/homebrew/opt/whisper-cpp/share/whisper-cpp/for-tests-ggml-tiny.bin"),
        ];

        candidates
            .into_iter()
            .find(|candidate| candidate.exists())
            .ok_or_else(|| {
                "Unable to locate a Whisper model. Set LLMOS_WHISPER_MODEL or place a ggml model in gui/src-tauri/resources/models.".to_string()
            })
    }

    fn uuid_like_timestamp() -> String {
        use std::time::{SystemTime, UNIX_EPOCH};

        match SystemTime::now().duration_since(UNIX_EPOCH) {
            Ok(duration) => format!("{}", duration.as_millis()),
            Err(_) => "0".to_string(),
        }
    }

    fn stop_listener() {
        MAC_WAKE_RUNTIME.with(|runtime| {
            if let Some(existing) = runtime.borrow_mut().take() {
                existing.recognizer.stopListening();
                existing.recognizer.setDelegate(None);
                drop(existing.delegate);
            }
        });
    }
}

#[cfg(not(target_os = "macos"))]
mod platform {
    use tauri::AppHandle;

    pub fn is_supported() -> bool {
        false
    }

    pub fn set_enabled(_app: AppHandle, enabled: bool, _wake_phrase: String) -> Result<(), String> {
        if enabled {
            Err("Hey Shell wake listening is currently only available on macOS.".to_string())
        } else {
            Ok(())
        }
    }

    pub fn transcribe_once(_app: &AppHandle) -> Result<String, String> {
        Err("Native dictation is currently only available on macOS.".to_string())
    }
}
