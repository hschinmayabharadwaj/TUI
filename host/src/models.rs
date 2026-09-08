use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use std::time::{SystemTime, UNIX_EPOCH};

pub fn now() -> String {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs().to_string()
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "UPPERCASE")]
pub enum WorkloadState { Installed, Starting, Running, Stopping, Stopped, Failed, Restarting, Updating, Deleting, Quarantined }

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "UPPERCASE")]
pub enum HealthState { Healthy, Warning, Degraded, Failed, Crashed, Quarantined, Stopped }

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum RestartPolicy { Never, Always, OnFailure, OnCrash }

impl Default for RestartPolicy { fn default() -> Self { Self::OnFailure } }

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ResourceLimits {
    #[serde(default)] pub max_heap: u64,
    #[serde(default)] pub max_stack: u64,
    #[serde(default = "default_cpu")] pub max_cpu: f64,
    #[serde(default)] pub max_storage: u64,
}
fn default_cpu() -> f64 { 100.0 }
impl Default for ResourceLimits { fn default() -> Self { Self { max_heap: 0, max_stack: 0, max_cpu: 100.0, max_storage: 0 } } }

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RestartConfig {
    #[serde(default)] pub policy: RestartPolicy,
    #[serde(default = "default_restarts")] pub max_restarts: u32,
    #[serde(default = "default_backoff")] pub backoff: String,
}
fn default_restarts() -> u32 { 3 }
fn default_backoff() -> String { "exponential".to_string() }
impl Default for RestartConfig { fn default() -> Self { Self { policy: RestartPolicy::default(), max_restarts: 3, backoff: default_backoff() } } }

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorkloadManifest {
    pub name: String,
    pub version: String,
    #[serde(default = "default_target")] pub target: String,
    #[serde(default = "default_architecture")] pub architecture: String,
    #[serde(default = "default_runtime")] pub runtime_version: String,
    #[serde(default = "default_entrypoint")] pub entrypoint: String,
    #[serde(default)] pub resources: ResourceLimits,
    #[serde(default)] pub permissions: BTreeMap<String, bool>,
    #[serde(default)] pub dependencies: BTreeMap<String, String>,
    #[serde(default)] pub restart: RestartConfig,
    #[serde(default)] pub requires: BTreeMap<String, Value>,
}
fn default_target() -> String { "esp32".into() }
fn default_architecture() -> String { "xtensa".into() }
fn default_runtime() -> String { ">=0.1".into() }
fn default_entrypoint() -> String { "main".into() }

impl WorkloadManifest {
    pub fn validate(&self) -> anyhow::Result<()> {
        if self.name.is_empty() { anyhow::bail!("workload name must be non-empty") }
        if self.name.len() > 64 { anyhow::bail!("workload name must be 64 characters or fewer") }
        if self.name.chars().any(char::is_whitespace) { anyhow::bail!("workload name must contain no whitespace") }
        if self.name.contains('/') || self.name.contains('\\') { anyhow::bail!("workload name must not contain path separators") }
        if self.name == "." || self.name == ".." { anyhow::bail!("workload name must not be '.' or '..'") }
        if !self.name.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') { anyhow::bail!("workload name must contain only ASCII alphanumeric characters, hyphens, or underscores") }
        if self.version.is_empty() { anyhow::bail!("workload version must be non-empty") }
        if self.version.len() > 32 { anyhow::bail!("workload version must be 32 characters or fewer") }
        if self.version.contains('/') || self.version.contains('\\') { anyhow::bail!("workload version must not contain path separators") }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn manifest(name: &str, version: &str) -> WorkloadManifest {
        WorkloadManifest {
            name: name.into(),
            version: version.into(),
            target: "esp32".into(),
            architecture: "xtensa".into(),
            runtime_version: ">=0.1".into(),
            entrypoint: "main".into(),
            resources: ResourceLimits::default(),
            permissions: Default::default(),
            dependencies: Default::default(),
            restart: RestartConfig::default(),
            requires: Default::default(),
        }
    }

    #[test]
    fn rejects_path_traversal_names() {
        for name in ["../etc/passwd", "a/b", "a\\b", "..", ".", "a b", ""] {
            assert!(manifest(name, "1.0.0").validate().is_err(), "should reject name {name:?}");
        }
    }

    #[test]
    fn rejects_path_traversal_versions() {
        for version in ["1.0.0/../x", "..\\x", ""] {
            assert!(manifest("ok", version).validate().is_err(), "should reject version {version:?}");
        }
    }

    #[test]
    fn accepts_safe_names_and_versions() {
        let valid = manifest("hello-workload", "1.2.3");
        assert!(valid.validate().is_ok());
        let long = manifest("a".repeat(64).as_str(), "1.0.0");
        assert!(long.validate().is_ok());
        assert!(manifest(&"a".repeat(65), "1.0.0").validate().is_err());
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LogEntry { pub timestamp: String, pub severity: String, pub task: String, pub message: String }

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorkloadRecord {
    pub numeric_id: u32,
    pub workload_id: String,
    pub manifest: WorkloadManifest,
    pub state: WorkloadState,
    pub health: HealthState,
    pub installed_at: String,
    pub updated_at: String,
    #[serde(default)] pub flash_bytes: u64,
    #[serde(default)] pub current_heap: u64,
    #[serde(default)] pub peak_heap: u64,
    #[serde(default)] pub stack_hwm: u64,
    #[serde(default)] pub cpu: f64,
    #[serde(default)] pub restarts: u32,
    #[serde(default)] pub crashes: u32,
    #[serde(default)] pub last_error: String,
    #[serde(default)] pub logs: Vec<LogEntry>,
}

impl WorkloadRecord {
    pub fn new(id: u32, manifest: WorkloadManifest, flash_bytes: u64) -> Self {
        let timestamp = now();
        Self { numeric_id: id, workload_id: uuid::Uuid::new_v4().to_string(), manifest, state: WorkloadState::Installed, health: HealthState::Stopped, installed_at: timestamp.clone(), updated_at: timestamp, flash_bytes, current_heap: 0, peak_heap: 0, stack_hwm: 0, cpu: 0.0, restarts: 0, crashes: 0, last_error: String::new(), logs: Vec::new() }
    }
}
