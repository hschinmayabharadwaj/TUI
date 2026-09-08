use crate::models::*;
use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

#[derive(Default, Serialize, Deserialize)]
struct DiskRegistry { schema: u32, workloads: Vec<WorkloadRecord>, audit: Vec<Value> }

pub struct Registry { pub path: PathBuf, pub workloads: BTreeMap<String, WorkloadRecord>, pub audit: Vec<Value> }

fn allowed(from: &WorkloadState, to: &WorkloadState) -> bool {
    use WorkloadState::*;
    matches!((from, to), (Installed, Starting | Deleting | Updating | Quarantined) | (Starting, Running | Failed | Stopping | Quarantined) | (Running, Stopping | Restarting | Failed | Updating | Quarantined) | (Stopping, Stopped | Failed) | (Stopped, Starting | Deleting | Updating | Quarantined) | (Failed, Restarting | Stopping | Quarantined | Deleting) | (Restarting, Starting | Running | Failed | Quarantined) | (Updating, Running | Stopped | Failed) | (Quarantined, Starting | Deleting | Stopped))
}

impl Registry {
    pub fn new(path: Option<PathBuf>) -> Result<Self> {
        let path = path.unwrap_or_else(|| { let home = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from(".")); home.join(".config/esp-top/workloads.json") });
        let mut registry = Self { path, workloads: BTreeMap::new(), audit: Vec::new() };
        registry.load()?;
        Ok(registry)
    }
    fn load(&mut self) -> Result<()> {
        if !self.path.is_file() { return Ok(()) }
        let disk: DiskRegistry = serde_json::from_str(&fs::read_to_string(&self.path).with_context(|| format!("cannot read {}", self.path.display()))?)?;
        self.workloads = disk.workloads.into_iter().map(|item| (item.manifest.name.clone(), item)).collect();
        self.audit = disk.audit;
        Ok(())
    }
    pub fn save(&self) -> Result<()> {
        if let Some(parent) = self.path.parent() { if !parent.as_os_str().is_empty() { fs::create_dir_all(parent)?; } }
        let disk = DiskRegistry { schema: 1, workloads: self.workloads.values().cloned().collect(), audit: self.audit.clone() };
        let temporary = self.path.with_extension("json.tmp");
        fs::write(&temporary, serde_json::to_vec_pretty(&disk)?)?;
        fs::rename(temporary, &self.path)?;
        Ok(())
    }
    pub fn list(&self) -> Vec<WorkloadRecord> { let mut result: Vec<_> = self.workloads.values().cloned().collect(); result.sort_by_key(|item| item.numeric_id); result }
    pub fn get(&self, name: &str) -> Result<&WorkloadRecord> { self.workloads.get(name).with_context(|| format!("workload not found: {name}")) }
    fn get_mut(&mut self, name: &str) -> Result<&mut WorkloadRecord> { self.workloads.get_mut(name).with_context(|| format!("workload not found: {name}")) }
    fn event(&mut self, name: &str, action: &str, reason: &str) { self.audit.push(json!({"at": now(), "workload": name, "action": action, "reason": reason})); if self.audit.len() > 500 { let remove = self.audit.len() - 500; self.audit.drain(0..remove); } }
    fn transition(record: &mut WorkloadRecord, state: WorkloadState, reason: &str) -> Result<()> { if record.state != state && !allowed(&record.state, &state) { bail!("cannot transition {} from {:?} to {:?}", record.manifest.name, record.state, state) } record.state = state.clone(); record.updated_at = now(); if state == WorkloadState::Running { record.health = HealthState::Healthy; } if state == WorkloadState::Stopped { record.health = HealthState::Stopped; } let _ = reason; Ok(()) }

    pub fn install(&mut self, manifest: WorkloadManifest, flash_bytes: u64) -> Result<WorkloadRecord> {
        manifest.validate()?;
        if let Some(record) = self.workloads.get_mut(&manifest.name) {
            if matches!(record.state, WorkloadState::Running | WorkloadState::Starting) { bail!("cannot replace active workload: {}", manifest.name) }
            record.manifest = manifest.clone(); record.flash_bytes = flash_bytes; record.state = WorkloadState::Stopped; record.health = HealthState::Stopped; record.updated_at = now();
        } else {
            let id = self.workloads.values().map(|item| item.numeric_id).max().unwrap_or(100) + 1;
            self.workloads.insert(manifest.name.clone(), WorkloadRecord::new(id, manifest.clone(), flash_bytes));
        }
        self.event(&manifest.name, "install", &manifest.version); self.save()?; Ok(self.workloads[&manifest.name].clone())
    }
    pub fn start(&mut self, name: &str) -> Result<WorkloadRecord> { if self.get(name)?.state == WorkloadState::Quarantined { bail!("workload is quarantined: {name}") } { let record = self.get_mut(name)?; Self::transition(record, WorkloadState::Starting, "start requested")?; Self::transition(record, WorkloadState::Running, "started")?; } self.event(name, "start", "started"); self.save()?; Ok(self.get(name)?.clone()) }
    pub fn stop(&mut self, name: &str) -> Result<WorkloadRecord> { if matches!(self.get(name)?.state, WorkloadState::Stopped | WorkloadState::Installed) { return Ok(self.get(name)?.clone()) } { let record = self.get_mut(name)?; Self::transition(record, WorkloadState::Stopping, "graceful stop requested")?; Self::transition(record, WorkloadState::Stopped, "cleanup complete")?; } self.event(name, "stop", "cleanup complete"); self.save()?; Ok(self.get(name)?.clone()) }
    pub fn restart(&mut self, name: &str) -> Result<WorkloadRecord> { let state = self.get(name)?.state.clone(); if state == WorkloadState::Quarantined { bail!("workload is quarantined: {name}") } { let record = self.get_mut(name)?; if matches!(state, WorkloadState::Running | WorkloadState::Failed) { Self::transition(record, WorkloadState::Restarting, "restart requested")?; } Self::transition(record, WorkloadState::Starting, "restart staged")?; Self::transition(record, WorkloadState::Running, "restart complete")?; record.restarts += 1; } self.event(name, "restart", "restart complete"); self.save()?; Ok(self.get(name)?.clone()) }
    pub fn remove(&mut self, name: &str) -> Result<WorkloadRecord> { if matches!(self.get(name)?.state, WorkloadState::Running | WorkloadState::Starting) { bail!("stop the workload before deleting it") } let mut record = self.workloads.remove(name).context("workload not found")?; record.state = WorkloadState::Deleting; self.event(name, "delete", "delete requested"); self.save()?; Ok(record) }
    pub fn quarantine(&mut self, name: &str, reason: &str) -> Result<WorkloadRecord> { { let record = self.get_mut(name)?; if record.state == WorkloadState::Running { Self::transition(record, WorkloadState::Failed, reason)?; } if record.state != WorkloadState::Quarantined { Self::transition(record, WorkloadState::Quarantined, reason)?; } record.health = HealthState::Quarantined; record.last_error = reason.to_string(); } self.event(name, "quarantine", reason); self.save()?; Ok(self.get(name)?.clone()) }
    pub fn unquarantine(&mut self, name: &str) -> Result<WorkloadRecord> { { let record = self.get_mut(name)?; if record.state == WorkloadState::Quarantined { Self::transition(record, WorkloadState::Stopped, "manual unquarantine")?; } record.health = HealthState::Stopped; } self.event(name, "unquarantine", "manual unquarantine"); self.save()?; Ok(self.get(name)?.clone()) }
    pub fn crash(&mut self, name: &str, reason: &str) -> Result<WorkloadRecord> { let (policy, max_restarts, restarts) = { let record = self.get_mut(name)?; record.crashes += 1; record.last_error = reason.to_string(); record.health = HealthState::Crashed; if record.state == WorkloadState::Running { Self::transition(record, WorkloadState::Failed, reason)?; } (record.manifest.restart.policy.clone(), record.manifest.restart.max_restarts, record.restarts) }; if matches!(policy, RestartPolicy::Always | RestartPolicy::OnCrash) && restarts < max_restarts { self.restart(name) } else { self.quarantine(name, &format!("restart limit reached: {reason}")) } }
    pub fn log(&mut self, name: &str, severity: &str, message: &str, task: &str) -> Result<()> { let record = self.get_mut(name)?; record.logs.push(LogEntry { timestamp: now(), severity: severity.to_uppercase(), task: task.to_string(), message: message.to_string() }); if record.logs.len() > 200 { let remove = record.logs.len() - 200; record.logs.drain(0..remove); } record.updated_at = now(); self.save() }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn crash_policy_quarantines_after_restart_budget() {
        let path = std::env::temp_dir().join(format!("esp-top-rust-test-{}.json", SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
        let mut registry = Registry::new(Some(path.clone())).unwrap();
        let manifest: WorkloadManifest = serde_json::from_str(r#"{"name":"sensor-worker","version":"1.0.0","restart":{"policy":"on-crash","max_restarts":1}}"#).unwrap();
        registry.install(manifest, 100).unwrap();
        registry.start("sensor-worker").unwrap();
        registry.crash("sensor-worker", "fault").unwrap();
        assert_eq!(registry.get("sensor-worker").unwrap().state, WorkloadState::Running);
        registry.crash("sensor-worker", "fault again").unwrap();
        assert_eq!(registry.get("sensor-worker").unwrap().state, WorkloadState::Quarantined);
        let _ = std::fs::remove_file(path);
    }
}
