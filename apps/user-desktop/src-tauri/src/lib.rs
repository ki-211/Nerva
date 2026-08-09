use std::path::PathBuf;

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_log::{RotationStrategy, Target, TargetKind, WEBVIEW_TARGET};

fn sanitize_print_query(query: &str) -> Result<String, String> {
    if query.len() > 1_024 {
        return Err("print query is too long".into());
    }
    let mut scope = None;
    let mut document_id = None;
    let mut version = None;
    for (key, value) in url::form_urlencoded::parse(query.as_bytes()) {
        match key.as_ref() {
            "scope" if value == "library" || value == "document" => {
                scope = Some(value.into_owned())
            }
            "document_id"
                if value.len() <= 160
                    && value
                        .chars()
                        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-')) =>
            {
                document_id = Some(value.into_owned());
            }
            "version" if value.len() <= 10 && value.chars().all(|c| c.is_ascii_digit()) => {
                version = Some(value.into_owned())
            }
            _ => return Err("invalid print query".into()),
        }
    }
    let scope = scope.ok_or_else(|| "print scope is required".to_string())?;
    if scope == "library" && (document_id.is_some() || version.is_some()) {
        return Err("library export does not accept document parameters".into());
    }
    if scope == "document" && document_id.is_none() {
        return Err("document export requires a document id".into());
    }
    let mut serializer = url::form_urlencoded::Serializer::new(String::new());
    serializer.append_pair("scope", &scope);
    if let Some(value) = document_id {
        serializer.append_pair("document_id", &value);
    }
    if let Some(value) = version {
        serializer.append_pair("version", &value);
    }
    Ok(serializer.finish())
}

#[tauri::command]
fn open_print_window(app: tauri::AppHandle, query: String) -> Result<(), String> {
    let query = sanitize_print_query(&query)?;
    if let Some(existing) = app.get_webview_window("print") {
        existing.close().map_err(|error| error.to_string())?;
    }
    let route = PathBuf::from(format!("user.html#/export/print?{query}"));
    WebviewWindowBuilder::new(&app, "print", WebviewUrl::App(route))
        .title("Nerva · 打印预览")
        .inner_size(1_000.0, 800.0)
        .min_inner_size(700.0, 600.0)
        .build()
        .map_err(|error| error.to_string())?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let log_dir = dirs::data_local_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("Nerva")
        .join("logs");
    let _ = std::fs::create_dir_all(&log_dir);
    let log_plugin = tauri_plugin_log::Builder::new()
        .clear_targets()
        .target(
            Target::new(TargetKind::Folder {
                path: log_dir,
                file_name: Some("nerva".into()),
            })
            .filter(|metadata| metadata.target().starts_with(WEBVIEW_TARGET)),
        )
        .max_file_size(10 * 1024 * 1024)
        .rotation_strategy(RotationStrategy::KeepSome(5))
        .level(log::LevelFilter::Info)
        .format(|out, message, _record| out.finish(format_args!("{message}")))
        .build();

    tauri::Builder::default()
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(log_plugin)
        .invoke_handler(tauri::generate_handler![open_print_window])
        .run(tauri::generate_context!())
        .expect("error while running Nerva");
}

#[cfg(test)]
mod tests {
    use super::sanitize_print_query;

    #[test]
    fn accepts_only_supported_print_routes() {
        assert_eq!(
            sanitize_print_query("scope=library").unwrap(),
            "scope=library"
        );
        assert!(sanitize_print_query("scope=library&document_id=doc_1").is_err());
        assert!(sanitize_print_query("scope=document").is_err());
        assert!(sanitize_print_query("scope=document&document_id=../../secret").is_err());
        assert_eq!(
            sanitize_print_query("scope=document&document_id=doc_1&version=2").unwrap(),
            "scope=document&document_id=doc_1&version=2"
        );
    }
}
