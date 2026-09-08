# ESP-Top Rust/C++ setup

## Requirements

- Rust toolchain with Cargo
- A C++ compiler for ESP32 firmware
- ESP32 Arduino core or ESP-IDF for firmware builds
- A data-capable USB cable for serial operation

## Host build

```bash
cd /Volumes/Untitled/TUI
cargo build --release
cargo test --workspace
```

## Connect to a board

```bash
./target/release/es32-top --list-ports
./target/release/es32-top tui --port /dev/cu.usbserial-0001 --baud 115200
```

On Linux, the device is commonly `/dev/ttyUSB0` or `/dev/ttyACM0`.

## Configure Wi-Fi safely

```bash
cp esp/secrets.example.h esp/secrets.h
```

Edit `esp/secrets.h` locally. It is ignored by git and must not be committed.

## Build a workload package

```bash
./target/release/es32-top package build examples/hello/manifest.json \
  -o /tmp/hello.espkg examples/hello/main.txt
./target/release/es32-top package verify /tmp/hello.espkg
./target/release/es32-top --registry /tmp/registry.json workload install /tmp/hello.espkg --start
```

## Troubleshooting

- Close Arduino Serial Monitor before starting `es32-top`; serial devices are
  normally exclusive.
- If the port is busy, check `lsof /dev/cu.usbserial-0001` on macOS or
  `lsof /dev/ttyUSB0` on Linux.
- If the registry is damaged, preserve it for diagnosis and use a new path with
  `--registry`; do not silently overwrite it.

## Optional OCaml verifier

The lifecycle verifier in `tools/ocaml/` is not required by the host or device.
With OCaml and Dune installed, run `make ocaml-verify` or execute it against a
transition trace.
