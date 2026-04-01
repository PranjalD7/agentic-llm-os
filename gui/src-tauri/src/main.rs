// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod voice;

use std::process::{Child, Command};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Instant;
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, WebviewWindow,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

struct DaemonState(Mutex<Option<Child>>);
struct TrayInteractionState(Mutex<Option<Instant>>);

fn note_tray_interaction(state: &TrayInteractionState) {
    if let Ok(mut guard) = state.0.lock() {
        *guard = Some(Instant::now());
    }
}

#[cfg(not(target_os = "macos"))]
fn should_ignore_blur(state: &TrayInteractionState) -> bool {
    state
        .0
        .lock()
        .ok()
        .and_then(|guard| *guard)
        .is_some_and(|instant| instant.elapsed() <= std::time::Duration::from_millis(1200))
}

fn toggle_window(app: &AppHandle, window: &WebviewWindow) {
    if window.is_visible().unwrap_or(false) {
        let _ = window.hide();
    } else {
        show_window(app, window);
    }
}

fn show_window(app: &AppHandle, window: &WebviewWindow) {
    note_tray_interaction(&app.state::<TrayInteractionState>());

    #[cfg(target_os = "macos")]
    let _ = app.show();

    let _ = window.center();
    let _ = window.show();
    let _ = window.set_focus();
}

fn start_daemon() -> Option<Child> {
    match spawn_installed_daemon().or_else(|_| spawn_repo_daemon()) {
        Ok(child) => {
            println!("[daemon] started with pid {}", child.id());
            Some(child)
        }
        Err(e) => {
            eprintln!("[daemon] failed to start: {}", e);
            None
        }
    }
}

fn spawn_installed_daemon() -> std::io::Result<Child> {
    Command::new("llmos-daemon")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
}

fn spawn_repo_daemon() -> std::io::Result<Child> {
    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."));

    let python = repo_root.join(".venv/bin/python");
    if !python.exists() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "Neither llmos-daemon nor .venv/bin/python was found",
        ));
    }

    Command::new(python)
        .arg("-c")
        .arg("from llmos.api.app import start_daemon; start_daemon()")
        .current_dir(&repo_root)
        .env("PYTHONPATH", repo_root.join("src"))
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
}

fn stop_daemon(state: &DaemonState) {
    if let Ok(mut guard) = state.0.lock() {
        if let Some(ref mut child) = *guard {
            println!("[daemon] stopping pid {}", child.id());
            let _ = child.kill();
            let _ = child.wait();
        }
        *guard = None;
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            voice::voice_get_status,
            voice::voice_set_enabled,
            voice::voice_transcribe_once
        ])
        .manage(DaemonState(Mutex::new(None)))
        .manage(TrayInteractionState(Mutex::new(None)))
        .manage(voice::VoiceState::default())
        .setup(|app| {
            // Start the Python daemon
            let daemon_child = start_daemon();
            let state = app.state::<DaemonState>();
            *state.0.lock().unwrap() = daemon_child;

            // Get the main window
            let window = app.get_webview_window("main").unwrap();
            // On macOS, keeping the window alive is more reliable than hiding on blur,
            // especially while native voice capture and permission prompts are active.
            #[cfg(not(target_os = "macos"))]
            {
                let app_handle = app.handle().clone();
                let win_blur = window.clone();
                window.on_window_event(move |event| {
                    if let tauri::WindowEvent::Focused(false) = event {
                        if should_ignore_blur(&app_handle.state::<TrayInteractionState>()) {
                            return;
                        }
                        let _ = win_blur.hide();
                    }
                });
            }

            // System tray — click to toggle window
            let icon = app.default_window_icon().unwrap().clone();
            let open_item = MenuItem::with_id(app, "tray-open", "Open ShellMind", true, None::<&str>)?;
            let hide_item = MenuItem::with_id(app, "tray-hide", "Hide ShellMind", true, None::<&str>)?;
            let quit_item = PredefinedMenuItem::quit(app, Some("Quit"))?;
            let tray_menu = Menu::with_items(app, &[&open_item, &hide_item, &quit_item])?;

            let mut tray = TrayIconBuilder::with_id("main-tray")
                .icon(icon)
                .title("ShellMind")
                .icon_as_template(true)
                .tooltip("ShellMind")
                .menu(&tray_menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "tray-open" => {
                        if let Some(window) = app.get_webview_window("main") {
                            show_window(app, &window);
                        }
                    }
                    "tray-hide" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.hide();
                        }
                    }
                    _ => {}
                });

            #[cfg(target_os = "macos")]
            {
                tray = tray.show_menu_on_left_click(true);
            }

            let _tray = tray.build(app)?;
            eprintln!("[tray] built main-tray");

            #[cfg(debug_assertions)]
            show_window(&app.handle(), &window);

            // Global shortcut: Cmd+Shift+Space
            let shortcut: Shortcut = "CommandOrControl+Shift+Space".parse().unwrap();
            let handle = app.handle().clone();
            app.global_shortcut()
                .on_shortcut(shortcut, move |_app, _shortcut, event| {
                    if event.state == ShortcutState::Pressed {
                        if let Some(window) = handle.get_webview_window("main") {
                            toggle_window(&handle, &window);
                        }
                    }
                })?;

            Ok(())
        })
        .on_tray_icon_event(|app, event| {
            eprintln!("[tray] event: {:?}", event);

            match event {
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Down,
                    ..
                } => {
                    note_tray_interaction(&app.state::<TrayInteractionState>());
                }
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                } => {
                    note_tray_interaction(&app.state::<TrayInteractionState>());

                    if let Some(window) = app.get_webview_window("main") {
                        toggle_window(app, &window);
                    }
                }
                _ => {}
            }
        })
        .on_window_event(|app, event| {
            // Intercept close to hide instead
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                voice::shutdown(app);
                let state = app.state::<DaemonState>();
                stop_daemon(&state);
            }
        });
}
