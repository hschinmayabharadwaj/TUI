# ESP-Top

ESP-Top is a Rust host CLI/TUI and runtime manager for ESP32-family devices.
The ESP32 runtime and Arduino compatibility layer remain C++/C.

The product boundary is a permanent supervisor runtime plus independently
managed workloads: install, start, inspect, stop, restart, update, quarantine,
rollback, and remove workloads without reflashing the base runtime.

## Native project layout

```text
host/src/              Rust CLI, registry, package, protocol, simulator, TUI
runtime/esp_runtime/   ESP32 runtime scaffold
sdk/arduino/           Arduino workload API
protocol/schema/       versioned protocol schema
tools/ocaml/           optional lifecycle verifier/schema boundary
```

The host requirements are Rust/Cargo and a POSIX terminal/serial environment.
The same Rust host code supports Linux and macOS; the device requirements are
the ESP32 Arduino core or ESP-IDF.
The device requirements are the ESP32 Arduino core or ESP-IDF.

## Build

```bash
cargo build --release
cargo test --workspace
```

Or use Make:

```bash
make build
make test
```

## CLI

```bash
./target/release/es32-top workload list
./target/release/es32-top package build examples/hello/manifest.json \
  -o /tmp/hello.espkg examples/hello/main.txt
./target/release/es32-top package verify /tmp/hello.espkg
./target/release/es32-top workload install /tmp/hello.espkg --start
./target/release/es32-top workload inspect hello-workload
./target/release/es32-top workload stop hello-workload
./target/release/es32-top workload restart hello-workload
./target/release/es32-top workload remove hello-workload
./target/release/es32-top doctor
./target/release/es32-top support-bundle -o /tmp/es32-top-support
./target/release/es32-top simulate --name hello-workload
```

The registry is resolved with the `dirs` crate in the platform's canonical
user config directory (typically `$XDG_CONFIG_HOME/es32-top` on Linux and
`~/Library/Application Support/es32-top` on macOS); use `--registry FILE` for
an isolated registry.

## Live monitor (Linux and macOS)

```bash
./target/release/es32-top --list-ports
./target/release/es32-top tui --baud 115200 --theme nord
```

Without `--port`, the host auto-selects the only detected ESP32 USB-serial
adapter (CP210x, CH340, FTDI, or Espressif USB/JTAG). If more than one is
present, pass the path shown by `--list-ports`:

| Linux | macOS |
|---|---|
| `/dev/ttyUSB0` or `/dev/ttyACM0` | `/dev/cu.usbserial-*` or `/dev/cu.usbmodem-*` |
| If denied, add the user to `dialout` and log in again | No `dialout` group is required; close any other serial monitor |

The monitor is a btop-style ESP32 dashboard: CPU/core history, heap/PSRAM/flash,
Wi-Fi/device status, and a selectable FreeRTOS task table. Arrow keys select a
task; `k` then `y` confirms a kill (`n`/Escape cancels); `Space` pauses; and
`q` quits. Ratatui/crossterm provides equivalent rendering and keyboard input
on Linux terminals and macOS Terminal/iTerm2. A reconnecting state is shown if
telemetry stops arriving.

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

Use a `/dev/cu.*` path for an explicit `--port`; macOS has no `dialout` group.
Close Arduino Serial Monitor or another application using the device first.

Optional configuration is `~/.config/es32-top/config.toml` (or `--config`):

```toml
[ui]
theme = "nord"
refresh_rate = 4

[monitor]
history_seconds = 60
```

Built-in themes: `default`, `nord`, `dracula`, `solarized`, `monokai`,
`high-contrast`, and `minimal`.

## ESP32 firmware

1. Open `runtime/esp_runtime/esp_runtime.ino` in Arduino IDE or PlatformIO.
2. Flash the runtime once.
3. Build workloads using `sdk/arduino/ESPWorkload.h`.
4. Deploy packages through the native CLI transport as that adapter is added.

The older `esp/esp.ino` remains available as a telemetry/reference sketch. Wi-Fi
credentials belong in the ignored `esp/secrets.h`, copied from
`esp/secrets.example.h`; no credentials are stored in source control.

## Cross-platform test plan

Run `cargo test --workspace` on both Linux and macOS. Manual checks should
cover: `--list-ports` and automatic single-port selection; multiple-port
selection and `--port` override; Linux `dialout` permission diagnostics;
canonical config paths; terminal resize and redraw; kill confirmation and
cancel; disconnected/reconnecting status; and registry invalid transitions,
crash-budget quarantine, atomic persistence, and package traversal rejection.

## Package format

Native Phase 1 packages are dependency-free directories ending in `.espkg`:

```text
hello.espkg/
├── manifest.json
└── payload/
    └── compiled-workload
```

The manifest records workload identity, resource limits, permissions,
dependencies, restart policy, and SHA-256 payload hashes. A signed archive and
binary/CBOR transport are later compatibility layers, not foundations of the
runtime model.

## Status

Implemented now: native workload model, persistent lifecycle registry, atomic
registry writes, audit history, package verification, protocol envelope,
storage-pressure analyzer, CLI, serial TUI foundation, Arduino SDK scaffold,
and native tests.

The optional OCaml tool in `tools/ocaml/` verifies lifecycle traces against the
same state machine. Install OCaml/Dune and run
`make ocaml-verify TRACE=transitions.txt`.

Next: real ESP32 workload registry integration, resource attribution, atomic
device-side updates, crash capture, signing, and rollback.
