# ESP-Top native Phase 1

The project uses Rust for the host and C++/C for the device runtime.

```text
ESP32 runtime -> versioned protocol envelope -> serial transport -> esp-top
                                                   |                 |
                                             workload CLI       native TUI
```

The Rust host registry is local in Phase 1, allowing lifecycle behavior and package
verification to be tested without hardware. `WorkloadRegistry` persists an
atomic JSON registry and audit log, enforces explicit state transitions, and
supports restart policies and quarantine.

`.espkg` is a directory package in this native baseline. It contains
`manifest.json` and `payload/`; every payload member is checked using SHA-256.
This avoids a third-party archive dependency while the device transport is
being implemented. Signed archives can be added without changing the manifest
or lifecycle interfaces.

The next device-facing boundary is a Rust serial transport adapter mapping
`host/src/protocol.rs` to `runtime/esp_runtime/esp_runtime.ino`.

The optional OCaml verifier in `tools/ocaml/` checks lifecycle transition traces
against the same state machine without becoming part of the embedded runtime.
