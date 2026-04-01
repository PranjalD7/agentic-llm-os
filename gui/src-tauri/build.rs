fn main() {
    #[cfg(target_os = "macos")]
    build_voice_dictation_helper();

    tauri_build::build()
}

#[cfg(target_os = "macos")]
fn build_voice_dictation_helper() {
    use std::{
        fs,
        os::unix::fs::PermissionsExt,
        path::PathBuf,
        process::Command,
    };

    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap());
    let source = manifest_dir.join("native/voice_dictation.swift");
    let output_dir = manifest_dir.join("resources/macos");
    let output = output_dir.join("voice-dictation-helper");
    let module_cache = output_dir.join("swift-module-cache");

    println!("cargo:rerun-if-changed={}", source.display());

    fs::create_dir_all(&output_dir).expect("failed to create native helper output dir");
    fs::create_dir_all(&module_cache).expect("failed to create swift module cache dir");

    let status = Command::new("xcrun")
        .arg("--sdk")
        .arg("macosx")
        .arg("swiftc")
        .arg(&source)
        .arg("-framework")
        .arg("AVFoundation")
        .arg("-module-cache-path")
        .arg(&module_cache)
        .arg("-o")
        .arg(&output)
        .status()
        .expect("failed to compile voice dictation helper");

    if !status.success() {
        panic!("failed to compile voice dictation helper");
    }

    let mut permissions = fs::metadata(&output)
        .expect("failed to stat voice dictation helper")
        .permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(&output, permissions).expect("failed to chmod voice dictation helper");
}
