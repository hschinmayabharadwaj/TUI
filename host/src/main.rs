mod models;
mod package;
mod protocol;
mod registry;
mod storage;
mod tui;

use anyhow::{Context, Result, bail};
use clap::{Parser, Subcommand};
use models::{WorkloadState};
use package::{build, package_bytes, verify};
use registry::Registry;
use serde_json::json;
use std::fs;
use std::path::PathBuf;

#[derive(Parser)]
#[command(name = "es32-top", version, about = "ESP32 workload manager, Rust host CLI/TUI, and simulator")]
struct Cli {
    #[arg(long, global = true, help = "local workload registry path")]
    registry: Option<PathBuf>,
    #[arg(long = "list-ports", global = true, help = "list available serial ports")]
    list_ports: bool,
    #[command(subcommand)] command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    Tui { #[arg(short, long)] port: String, #[arg(short, long, default_value_t = 115200)] baud: u32 },
    #[command(subcommand)] Workload(WorkloadCommand),
    #[command(subcommand)] Package(PackageCommand),
    #[command(subcommand)] Storage(StorageCommand),
    Device { action: String },
    Doctor,
    SupportBundle { #[arg(short, long, default_value = "support-bundle")] output: PathBuf },
    Simulate { #[arg(long, default_value = "hello-workload")] name: String },
}

#[derive(Subcommand)]
enum WorkloadCommand {
    List { #[arg(long)] json: bool },
    Inspect { name: String, #[arg(long)] json: bool },
    Install { package: PathBuf, #[arg(long)] start: bool },
    Start { name: String }, Stop { name: String }, Restart { name: String }, Remove { name: String },
    Logs { name: String },
    Quarantine { name: String, reason: String },
    Unquarantine { name: String },
    Crash { name: String, reason: String },
}

#[derive(Subcommand)]
enum PackageCommand { Build { manifest: PathBuf, #[arg(short, long)] output: PathBuf, payload: Vec<PathBuf> }, Verify { package: PathBuf } }

#[derive(Subcommand)]
enum StorageCommand { Analyze { #[arg(long)] total: u64, #[arg(long = "entry")] entries: Vec<String>, #[arg(long)] json: bool } }

fn human(bytes: u64) -> String { let mut value = bytes as f64; let mut unit = "B"; for candidate in ["KiB", "MiB", "GiB"] { if value < 1024.0 { break } value /= 1024.0; unit = candidate; } if unit == "B" { format!("{} B", bytes) } else { format!("{value:.1} {unit}") } }
fn open_registry(path: Option<PathBuf>) -> Result<Registry> { Registry::new(path) }
fn print_record(record: &models::WorkloadRecord) { println!("{:<4} {:<20} {:<12} {:<12} {:<12} {}", record.numeric_id, record.manifest.name, record.manifest.version, format!("{:?}", record.state).to_uppercase(), format!("{:?}", record.health).to_uppercase(), human(record.flash_bytes)); }
fn inspect(record: &models::WorkloadRecord, json_output: bool) { if json_output { println!("{}", serde_json::to_string_pretty(record).unwrap()); return } println!("{}\n{}", record.manifest.name, "-".repeat(record.manifest.name.len())); println!("ID       {}\nVersion  {}\nState    {:?}\nHealth   {:?}\nCPU      {:.1}%\nHeap     {} / {} peak\nStack    {}\nFlash    {}\nRestarts {}\nCrashes  {}", record.numeric_id, record.manifest.version, record.state, record.health, record.cpu, human(record.current_heap), human(record.peak_heap), human(record.stack_hwm), human(record.flash_bytes), record.restarts, record.crashes); if !record.last_error.is_empty() { println!("Error    {}", record.last_error); } }

fn run_workload(command: WorkloadCommand, path: Option<PathBuf>) -> Result<()> {
    let mut registry = open_registry(path)?;
    match command {
        WorkloadCommand::List { json } => { let records = registry.list(); if json { println!("{}", serde_json::to_string_pretty(&records)?); } else { println!("ID   NAME                 VERSION      STATE        HEALTH       FLASH"); for record in &records { print_record(record); } } }
        WorkloadCommand::Inspect { name, json } => inspect(registry.get(&name)?, json),
        WorkloadCommand::Install { package, start } => { let manifest = verify(&package)?; let mut record = registry.install(manifest, package_bytes(&package)?)?; if start { record = registry.start(&record.manifest.name)?; } println!("installed {} id {}", record.manifest.name, record.numeric_id); }
        WorkloadCommand::Start { name } => { registry.start(&name)?; println!("started {name}"); }
        WorkloadCommand::Stop { name } => { registry.stop(&name)?; println!("stopped {name}"); }
        WorkloadCommand::Restart { name } => { registry.restart(&name)?; println!("restarted {name}"); }
        WorkloadCommand::Remove { name } => { registry.remove(&name)?; println!("removed {name}"); }
        WorkloadCommand::Logs { name } => for log in &registry.get(&name)?.logs { println!("{} {} {} {}", log.timestamp, log.severity, log.task, log.message); },
        WorkloadCommand::Quarantine { name, reason } => { registry.quarantine(&name, &reason)?; println!("quarantined {name}"); }
        WorkloadCommand::Unquarantine { name } => { registry.unquarantine(&name)?; println!("unquarantined {name}"); }
        WorkloadCommand::Crash { name, reason } => { let record = registry.crash(&name, &reason)?; println!("{} -> {:?}", name, record.state); }
    }
    Ok(())
}

fn run_package(command: PackageCommand) -> Result<()> { match command { PackageCommand::Build { manifest, output, payload } => { build(&manifest, &output, &payload)?; println!("{}", output.display()); }, PackageCommand::Verify { package } => println!("{} verified", verify(&package)?.name) } Ok(()) }

fn run_storage(command: StorageCommand) -> Result<()> { match command { StorageCommand::Analyze { total, entries, json: json_output } => { let entries = entries.into_iter().map(|entry| { let (name, size) = entry.split_once('=').context("storage entries must use NAME=BYTES")?; Ok(crate::storage::Entry { name: name.into(), size: size.parse()?, kind: "workload".into(), removable: true }) }).collect::<Result<Vec<_>>>()?; let analysis = crate::storage::analyze(total, entries); if json_output { println!("{}", serde_json::to_string_pretty(&analysis)?); } else { println!("STORAGE PRESSURE\n\nFlash: {:.1}% used\n{}\nLargest consumers:", analysis.used_percent, if analysis.pressure { "WARNING: storage pressure threshold exceeded" } else { "" }); for (index, entry) in analysis.entries.iter().enumerate() { println!("{}. {}  {}", index + 1, entry.name, human(entry.size)); } println!("\nPotential recovery: {}\nAvailable now: {}", human(analysis.recoverable), human(analysis.free)); } } } Ok(()) }

fn run_support_bundle(output: PathBuf, path: Option<PathBuf>) -> Result<()> { let registry = open_registry(path)?; fs::create_dir_all(&output)?; fs::write(output.join("device.json"), serde_json::to_vec_pretty(&json!({"client":"es32-top","version":env!("CARGO_PKG_VERSION")}))?)?; fs::write(output.join("workloads.json"), serde_json::to_vec_pretty(&registry.list())?)?; fs::write(output.join("audit.json"), serde_json::to_vec_pretty(&registry.audit)?)?; println!("{}", output.display()); Ok(()) }
fn doctor(path: Option<PathBuf>) -> Result<()> { let registry = open_registry(path)?; let failures: Vec<_> = registry.list().into_iter().filter(|record| matches!(record.state, WorkloadState::Failed | WorkloadState::Quarantined)).collect(); if failures.is_empty() { println!("ESP-TOP DOCTOR: OK"); Ok(()) } else { for record in failures { println!("{}: {:?}", record.manifest.name, record.state); } bail!("workload problems detected") } }
fn simulate(name: String) -> Result<()> { println!("ESP-TOP SIMULATOR\nworkload: {name}\nprotocol: {}\n", crate::protocol::VERSION); println!("{}", crate::protocol::encode("WORKLOAD_LIST", json!({"workloads":[{"id":101,"name":name,"state":"RUNNING"}]}), "sim-1")?); Ok(()) }

fn main() -> Result<()> { let Cli { registry, list_ports, command } = Cli::parse(); if list_ports { return tui::list_ports(); } match command.context("a subcommand is required")? { Command::Tui { port, baud } => tui::run(&port, baud), Command::Workload(command) => run_workload(command, registry), Command::Package(command) => run_package(command), Command::Storage(command) => run_storage(command), Command::Device { action } => { println!("local  serial  protocol {}  action {action}", crate::protocol::VERSION); Ok(()) }, Command::Doctor => doctor(registry), Command::SupportBundle { output } => run_support_bundle(output, registry), Command::Simulate { name } => simulate(name) } }
