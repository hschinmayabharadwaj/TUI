use std::path::PathBuf;

/// Canonical per-user location shared by registry and future host settings.
pub fn config_dir() -> PathBuf {
    dirs::config_dir().unwrap_or_else(|| PathBuf::from(".")).join("es32-top")
}

pub fn registry_path() -> PathBuf { config_dir().join("workloads.json") }
