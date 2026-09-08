# Security Policy

## Scope

ESP-Top includes a Rust host CLI/TUI, ESP32 runtime firmware, an Arduino workload SDK, a serial protocol, and workload packages. This policy applies to vulnerabilities in those components and in the repository's build or release process.

## Reporting a Vulnerability

Do not report security vulnerabilities in public issues or pull requests.

Report privately through the repository owner's GitHub Security Advisories page. Include:

- affected component and version or commit
- device, operating system, and toolchain details
- reproduction steps or a minimal proof of concept
- security impact and any required physical or network access
- suggested mitigation, if known

Please do not include passwords, Wi-Fi credentials, private keys, production package contents, or personal data in a report. If GitHub private reporting is unavailable, contact the repository maintainer privately through the GitHub account associated with this repository and request an encrypted reporting channel.

We will acknowledge reports when practical, investigate reproducible reports, and coordinate disclosure with the reporter. Do not publicly disclose a vulnerability until a fix or mitigation and a disclosure date have been agreed.

## Supported Versions

This project is under active development. Security fixes should target the latest commit on `main` and the latest release, when releases are published. Older development snapshots may not receive backports.

## Security Requirements

Production deployments should provide all of the following:

- authenticated devices and authorized host clients
- encrypted network transport when network transport is introduced
- signed workload packages, with signature verification before installation
- checksum verification for package integrity
- manifest, runtime, dependency, version, and resource-limit validation
- authorization and confirmation for destructive operations
- command identifiers, freshness checks, and replay protection
- append-only or protected audit records
- secure provisioning and credential rotation
- secure-boot and flash-encryption compatibility where supported by the ESP32 target

## Current Phase 1 Boundaries

The current implementation provides local lifecycle management, SHA-256 payload verification, manifest validation, path-traversal-resistant package handling, atomic local registry writes, audit history, and a serial telemetry TUI. These controls do **not** establish package authenticity or device identity.

In particular:

- package checksums detect corruption but do not prove who produced a package
- workload names and versions are strictly bounded (≤64/≤32 chars, ASCII alphanumeric, `-`, `_`; no path separators), and package payload names reject path traversal, dot-prefixed names, and control characters
- serial input is bounded (device command buffer and host TUI line buffer are size-limited) but not authenticated or encrypted
- workload installation and lifecycle commands are local host operations without a role or authorization model
- the native package format does not yet provide production signature verification
- firmware credentials belong in the ignored `esp/secrets.h`; never commit that file or any key, token, password, or private certificate
- support bundles and logs may contain operational data; review them before sharing

Do not use the current serial transport or unsigned package flow for hostile networks, untrusted physical environments, or production fleet provisioning.

## Development Rules

- Keep secrets in local ignored configuration or a dedicated secret manager.
- Use `esp/secrets.example.h` as the template, not as a place for real credentials.
- Review package manifests, permissions, dependencies, and payload hashes before installation.
- Validate all host and device input at protocol boundaries.
- Avoid logging credentials, tokens, private keys, or sensitive payload contents.
- Run `cargo test --workspace` and `cargo build --release` before publishing host changes.
- Treat generated files, macOS `._*` metadata, `target/`, and support bundles as non-source artifacts.

## Planned Security Work

Before production deployment, implement and test signed packages, authenticated and encrypted transport, device identity and provisioning, replay-resistant command handling, authorization for destructive actions, protected audit storage, and a documented key-rotation and revocation process.
