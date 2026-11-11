#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::sync::{Mutex, atomic::{AtomicBool, Ordering}};
use tauri::Manager;
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_shell::{process::{CommandChild, CommandEvent}, ShellExt};

struct Backend { child: Mutex<Option<CommandChild>>, exiting: AtomicBool, terminated: AtomicBool }

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") { let _ = window.show(); let _ = window.set_focus(); }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .manage(Backend { child: Mutex::new(None), exiting: AtomicBool::new(false), terminated: AtomicBool::new(false) })
        .setup(|app| {
            let (mut receiver, child) = app.shell().sidecar("apply-backend")?
                .args(["--desktop", "--port", "0", "--no-open"])
                .env("APPLY_DESKTOP", "1").set_process_group(true).spawn()?;
            *app.state::<Backend>().child.lock().unwrap() = Some(child);
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                while let Some(event) = receiver.recv().await {
                    if matches!(event, CommandEvent::Terminated(_)) {
                        handle.state::<Backend>().terminated.store(true, Ordering::SeqCst);
                    }
                    if let CommandEvent::Stdout(bytes) = event {
                        let line = String::from_utf8_lossy(&bytes);
                        for line in line.lines() {
                            if let Some(raw) = line.strip_prefix("APPLY_READY ") {
                                if let Ok(value) = serde_json::from_str::<serde_json::Value>(raw) {
                                    if let Some(port) = value["port"].as_u64().filter(|p| *p > 0 && *p <= 65535) {
                                        if let Some(window) = handle.get_webview_window("main") {
                                            if let Ok(url) = format!("http://127.0.0.1:{port}").parse() {
                                                let _ = window.navigate(url);
                                            }
                                        }
                                    }
                                }
                            } else if let Some(raw) = line.strip_prefix("APPLY_NOTICE ") {
                                if let Ok(value) = serde_json::from_str::<serde_json::Value>(raw) {
                                    let title = value["title"].as_str().unwrap_or("Apply");
                                    let body = value["body"].as_str().unwrap_or("Нужно ваше участие в приложении.");
                                    let _ = handle.notification().request_permission();
                                    let _ = handle.notification().builder().title(title).body(body).show();
                                }
                            }
                        }
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Не удалось запустить Apply");
    app.run(|handle, event| {
        if let tauri::RunEvent::ExitRequested { api, .. } = event {
            if !handle.state::<Backend>().exiting.swap(true, Ordering::SeqCst) {
                api.prevent_exit();
                if let Some(window) = handle.get_webview_window("main") { let _ = window.hide(); }
                if let Some(child) = handle.state::<Backend>().child.lock().unwrap().as_mut() {
                    let _ = child.write(b"SHUTDOWN\n");
                }
                let handle = handle.clone();
                std::thread::spawn(move || {
                    for _ in 0..450 {
                        if handle.state::<Backend>().terminated.load(Ordering::SeqCst) { break; }
                        std::thread::sleep(std::time::Duration::from_millis(100));
                    }
                    if let Some(child) = handle.state::<Backend>().child.lock().unwrap().take() {
                        if !handle.state::<Backend>().terminated.load(Ordering::SeqCst) { let _ = child.kill(); }
                    }
                    handle.exit(0);
                });
            }
        }
    });
}
