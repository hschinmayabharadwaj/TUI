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
./target/release/esp-top workload list
./target/release/esp-top package build examples/hello/manifest.json \
  -o /tmp/hello.espkg examples/hello/main.txt
./target/release/esp-top package verify /tmp/hello.espkg
./target/release/esp-top workload install /tmp/hello.espkg --start
./target/release/esp-top workload inspect hello-workload
./target/release/esp-top workload stop hello-workload
./target/release/esp-top workload restart hello-workload
./target/release/esp-top workload remove hello-workload
./target/release/esp-top doctor
./target/release/esp-top support-bundle -o /tmp/esp-top-support
./target/release/esp-top simulate --name hello-workload
```

The registry is stored at `~/.config/esp-top/workloads.json`; use
`--registry FILE` for an isolated registry.

## Live monitor

```bash
./target/release/esp-top --list-ports
./target/release/esp-top tui --port /dev/cu.usbserial-0001 --baud 115200
```

Press `q` to quit. The monitor accepts the existing newline-delimited ESP32
telemetry JSON while the versioned protocol is introduced in parallel.

## ESP32 firmware

1. Open `runtime/esp_runtime/esp_runtime.ino` in Arduino IDE or PlatformIO.
2. Flash the runtime once.
3. Build workloads using `sdk/arduino/ESPWorkload.h`.
4. Deploy packages through the native CLI transport as that adapter is added.

The older `esp/esp.ino` remains available as a telemetry/reference sketch. Wi-Fi
credentials belong in the ignored `esp/secrets.h`, copied from
`esp/secrets.example.h`; no credentials are stored in source control.

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

Next: serial command transport, real ESP32 workload registry integration,
resource attribution, atomic device-side updates, crash capture, signing, and
rollback.
