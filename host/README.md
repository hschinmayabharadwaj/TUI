# ESP-Top

ESP-Top is a Rust host CLI/TUI and runtime manager for ESP32-family devices. It
manages workloads (applications) on an ESP32 supervisor runtime: install,
start, inspect, stop, restart, update, quarantine, rollback, and remove
workloads without reflashing the base runtime.

## Features

- **Lifecycle registry** — persistent workload state machine with atomic writes
  and a capped audit log (`~/.config/es32-top/workloads.json`)
- **Package tooling** — build and verify `.espkg` packages with SHA-256 payload
  hashes and strict manifest validation (no path traversal, bounded names)
- **Serial TUI** — btop-style live monitor (`es32-top tui --port ...`) and port
  discovery (`es32-top --list-ports`)
- **Protocol client** — versioned JSON envelope (`protocol/v1`) for host-device
  communication
- **Storage analyzer** — flash-pressure analysis and recoverable-space reporting
- **Simulator & doctor** — offline `simulate` and `doctor` tooling

## Install

```bash
cargo install es32-top
```

Or build from source:

```bash
cargo build --release
cargo test --workspace
```

## Usage

```bash
es32-top workload list
es32-top package build examples/hello/manifest.json -o /tmp/hello.espkg examples/hello/main.txt
es32-top package verify /tmp/hello.espkg
es32-top workload install /tmp/hello.espkg --start
es32-top workload inspect hello-workload
es32-top workload stop hello-workload
es32-top workload restart hello-workload
es32-top workload remove hello-workload
es32-top doctor
es32-top support-bundle -o /tmp/es32-top-support
es32-top simulate --name hello-workload
es32-top --list-ports
es32-top tui --port /dev/cu.usbserial-0001 --baud 115200
```

The registry is stored at `~/.config/es32-top/workloads.json`; use
`--registry FILE` for an isolated registry.

## Security

See `SECURITY.md` at the repository root for the security policy and current
Phase 1 boundaries. Highlights:

- Payload SHA-256 verification and strict manifest validation before install
- Path-traversal-resistant package verification
- Atomic local registry writes and bounded audit/log history
- No secrets in source control; Wi-Fi credentials live in ignored
  `esp/secrets.h`

Unsigned packages detect corruption but not authenticity, and the serial
transport is unauthenticated. Do not use for hostile networks or production
fleet provisioning.

## License

MIT