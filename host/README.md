# ESP-Top

ESP-Top is a Rust host CLI/TUI and workload manager for ESP32-family devices. It
manages workloads (applications) on an ESP32 supervisor runtime: install, start,
inspect, stop, restart, update, quarantine, rollback, and remove workloads
without reflashing the base runtime. The same host code runs on Linux and macOS.

## Features

- **Lifecycle registry** — persistent workload state machine with atomic writes,
  a capped audit log, crash-budget quarantine, and full workload history
- **Package tooling** — build and verify `.espkg` packages with SHA-256 payload
  hashes and strict manifest validation (no path traversal, bounded names)
- **Serial TUI** — btop-style live monitor (`es32-top tui --port ...`) and port
  discovery (`es32-top --list-ports`); auto-selects a single ESP32 USB-serial
  adapter (CP210x, CH340, FTDI, Espressif USB/JTAG)
- **Protocol client** — versioned JSON envelope (`protocol/v1`) for host-device
  communication
- **Storage analyzer** — flash-pressure analysis and recoverable-space reporting
- **Simulator & doctor** — offline `simulate`, `doctor`, and `support-bundle`
  tooling

## Install

The crate is published on [crates.io](https://crates.io/crates/es32-top):

```bash
cargo install es32-top
```

Or build from source:

```bash
cargo build --release
cargo test --workspace
```

## Requirements

- Rust/Cargo (stable) and a POSIX terminal
- Linux: `pkg-config` and `libudev-dev`; a user in the `dialout` group to open
  serial devices
- macOS: Xcode command line tools (`xcode-select --install`); no `dialout` group
  is required

## Usage

```bash
es32-top --list-ports
es32-top workload list
es32-top workload inspect hello-workload
es32-top workload logs hello-workload
es32-top package build examples/hello/manifest.json -o /tmp/hello.espkg examples/hello/main.txt
es32-top package verify /tmp/hello.espkg
es32-top workload install /tmp/hello.espkg --start
es32-top workload start hello-workload
es32-top workload stop hello-workload
es32-top workload restart hello-workload
es32-top workload remove hello-workload
es32-top workload quarantine hello-workload "root cause"
es32-top workload unquarantine hello-workload
es32-top workload crash hello-workload "out of memory"
es32-top storage analyze --total 4194304 --entry hello-workload=524288
es32-top device status
es32-top doctor
es32-top support-bundle -o /tmp/es32-top-support
es32-top simulate --name hello-workload
```

Global flags: `--registry FILE` points the workload registry at an explicit
file (defaults to the platform config directory), and `--list-ports` prints all
serial ports.

## Storage and registry location

The registry and audit history are stored with the `dirs` crate in the
platform's canonical per-user config directory:

| Linux | macOS |
|---|---|
| `$XDG_CONFIG_HOME/es32-top/workloads.json` (usually `~/.config/es32-top/workloads.json`) | `~/Library/Application Support/es32-top/workloads.json` |

Use `--registry FILE` for an isolated registry (for example in tests or
CI).

## Live serial TUI (Linux and macOS)

```bash
es32-top --list-ports
es32-top tui --baud 115200 --theme nord
es32-top tui --port /dev/cu.usbserial-0001
```

Without `--port`, the host auto-selects the only detected ESP32 USB-serial
adapter (CP210x, CH340, FTDI, or Espressif USB/JTAG). If there is more than one,
pass the path shown by `--list-ports`:

| Linux | macOS |
|---|---|
| `/dev/ttyUSB0` or `/dev/ttyACM0` | `/dev/cu.usbserial-*` or `/dev/cu.usbmodem-*` |
| If opening the device is denied, add the user to `dialout` and log in again | No group is required; close other serial monitors first |

The monitor is a btop-style ESP32 dashboard: CPU/core history with a sparkline,
heap/PSRAM pressure gauges, Wi-Fi signal, temperature, and a selectable FreeRTOS
task table. Controls:

| Key | Action |
|---|---|
| `↑` / `↓` | Select a task |
| `k` then `y` | Confirm kill of the selected non-system task |
| `n` / `Esc` | Cancel a pending kill |
| `Space` | Pause / resume incoming samples |
| `q` | Quit |

A status bar shows `CONNECTED` / `RECONNECTING` based on how recently telemetry
arrived.

### Linux

```bash
sudo apt install build-essential pkg-config libudev-dev
cargo build --release
cargo test --workspace
./target/release/es32-top --list-ports
./target/release/es32-top tui
```

If opening a serial device is denied, run `sudo usermod -aG dialout "$USER"`
and start a new login session.

### macOS

```bash
xcode-select --install
cargo build --release
cargo test --workspace
./target/release/es32-top --list-ports
./target/release/es32-top tui
```

Use a `/dev/cu.*` path for an explicit `--port`. Close the Arduino Serial
Monitor or another application using the device first.

## TUI configuration

Optional configuration is `--config FILE`, or the default config file
`$XDG_CONFIG_HOME/es32-top/config.toml` (falling back to
`~/.config/es32-top/config.toml` on both Linux and macOS):

```toml
[ui]
theme = "nord"
refresh_rate = 4

[monitor]
history_seconds = 60
```

The CLI flags `--theme`, `--refresh-rate` (1-30 samples/s), and
`--history-seconds` (10-600 s) override the file. Built-in themes: `default`,
`nord`, `dracula`, `solarized`, `monokai`, `high-contrast`, and `minimal`.

## Package format and security

Native Phase 1 packages are dependency-free directories ending in `.espkg`:

```text
hello.espkg/
├── manifest.json
└── payload/
    └── compiled-workload
```

The manifest records workload identity, resource limits, permissions,
dependencies, restart policy, and SHA-256 payload hashes. `es32-top package
verify` enforces strict manifest validation, rejects path traversal, and verifies
payload hashes before installation. A signed archive and binary/CBOR transport
are later compatibility layers.

## Security

See `SECURITY.md` at the repository root for the security policy and current
Phase 1 boundaries. Highlights:

- Payload SHA-256 verification and strict manifest validation before install
- Path-traversal-resistant package verification
- Atomic local registry writes and bounded audit/log history
- Crash-budget quarantine and lifecycle state-machine enforcement
- No secrets in source control; Wi-Fi credentials live in ignored
  `esp/secrets.h`

Unsigned packages detect corruption but not authenticity, and the serial
transport is unauthenticated. Do not use for hostile networks or production
fleet provisioning.

## License

MIT