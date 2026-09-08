use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
pub struct Entry { pub name: String, pub size: u64, pub kind: String, pub removable: bool }
#[derive(Debug, Serialize)]
pub struct Analysis { pub total: u64, pub used: u64, pub free: u64, pub used_percent: f64, pub pressure: bool, pub recoverable: u64, pub entries: Vec<Entry> }
pub fn analyze(total: u64, mut entries: Vec<Entry>) -> Analysis { entries.sort_by(|a,b| b.size.cmp(&a.size)); let used = entries.iter().map(|e| e.size).sum(); Analysis { total, used, free: total.saturating_sub(used), used_percent: if total == 0 { 0.0 } else { used as f64 * 100.0 / total as f64 }, pressure: total > 0 && used as f64 / total as f64 >= 0.85, recoverable: entries.iter().filter(|e| e.removable).map(|e| e.size).sum(), entries } }
