fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(&["driftguard_request"])),
    )
    .expect("Unable to prepare the desktop permission manifest");
}
