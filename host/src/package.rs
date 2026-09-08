use crate::models::WorkloadManifest;
use anyhow::{Context, Result, bail};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

pub fn sha256_file(path: &Path) -> Result<String> { let bytes = fs::read(path).with_context(|| format!("cannot read {}", path.display()))?; let mut hash = Sha256::new(); hash.update(bytes); Ok(format!("{:x}", hash.finalize())) }
pub fn package_bytes(path: &Path) -> Result<u64> { let mut total = 0; for entry in walk(path)? { if entry.is_file() { total += entry.metadata()?.len(); } } Ok(total) }
fn walk(path: &Path) -> Result<Vec<PathBuf>> { let mut result = Vec::new(); if path.is_dir() { for item in fs::read_dir(path)? { let item = item?; result.push(item.path()); if item.path().is_dir() { result.extend(walk(&item.path())?); } } } Ok(result) }

fn validate_payload_name(name: &str) -> Result<()> {
    if name.is_empty() { bail!("payload name must not be empty") }
    if name.contains('/') || name.contains('\\') || name == "." || name == ".." { bail!("payload name contains path separator or is a reserved path: {name}") }
    if name.starts_with('.') { bail!("payload name must not start with a dot: {name}") }
    if name.bytes().any(|b| b < 0x20 || b == 0x7f) { bail!("payload name contains control character: {name}") }
    Ok(())
}

fn safe_payload_path(base: &Path, name: &str) -> Result<PathBuf> {
    validate_payload_name(name)?;
    let resolved = base.join("payload").join(name);
    let canonical_base = base.join("payload").canonicalize().unwrap_or_else(|_| base.join("payload"));
    if let Ok(canonical_file) = resolved.canonicalize() {
        if !canonical_file.starts_with(&canonical_base) { bail!("payload path escapes package directory: {name}") }
    }
    Ok(resolved)
}

pub fn build(manifest_path: &Path, output: &Path, payloads: &[PathBuf]) -> Result<()> { if output.exists() { bail!("package output already exists: {}", output.display()) } let manifest: WorkloadManifest = serde_json::from_str(&fs::read_to_string(manifest_path)?)?; manifest.validate()?; let mut names = Vec::new(); for source in payloads { if !source.is_file() { bail!("payload is not a file: {}", source.display()) } let name = source.file_name().context("payload has no filename")?.to_string_lossy().to_string(); validate_payload_name(&name)?; names.push((source, name)); } fs::create_dir_all(output.join("payload"))?; let mut hashes = Map::new(); for (source, name) in names { let target = output.join("payload").join(&name); fs::copy(source, &target)?; hashes.insert(name, Value::String(sha256_file(&target)?)); } let mut value = serde_json::to_value(manifest)?; value["package_version"] = Value::from(1); value["payload"] = Value::Object(hashes); fs::write(output.join("manifest.json"), serde_json::to_vec_pretty(&value)?)?; Ok(()) }
pub fn verify(path: &Path) -> Result<WorkloadManifest> { if !path.is_dir() { bail!("native .espkg packages are directories: {}", path.display()) } let value: Value = serde_json::from_str(&fs::read_to_string(path.join("manifest.json"))?)?; if value["package_version"].as_u64() != Some(1) { bail!("unsupported package version") } if let Some(payloads) = value["payload"].as_object() { for (name, expected) in payloads { let file = safe_payload_path(path, name)?; if !file.is_file() { bail!("missing payload: {name}") } if sha256_file(&file)? != expected.as_str().unwrap_or_default() { bail!("checksum mismatch: {name}") } } } let manifest: WorkloadManifest = serde_json::from_value(value)?; manifest.validate()?; Ok(manifest) }

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn rejects_payload_names_with_path_separators() {
        assert!(validate_payload_name("ok.bin").is_ok());
        for name in ["../etc/passwd", "a/b", "a\\b", "..", ".", ".hidden", ""] {
            assert!(validate_payload_name(name).is_err(), "should reject {name:?}");
        }
    }

    #[test]
    fn verify_rejects_manifest_with_traversal_payload_name() {
        let dir = std::env::temp_dir().join(format!("es32-top-pkg-verify-{}", std::process::id()));
        let source = dir.join("payload");
        fs::create_dir_all(&source).unwrap();
        fs::write(source.join("file.txt"), b"data").unwrap();
        // A manifest mapping a traversal name to a real checksum of a file
        // outside the package payload directory.
        let outside = std::env::temp_dir().join("es32-top-outside.txt");
        fs::write(&outside, b"secret").unwrap();
        let hash = sha256_file(&outside).unwrap();
        let manifest = json!({
            "name": "w",
            "version": "1.0.0",
            "package_version": 1,
            "payload": { "../es32-top-outside.txt": hash }
        });
        fs::write(dir.join("manifest.json"), serde_json::to_vec(&manifest).unwrap()).unwrap();
        assert!(verify(&dir).is_err());
        let _ = fs::remove_dir_all(&dir);
        let _ = fs::remove_file(&outside);
    }

    #[test]
    fn build_rejects_dotfile_payload_sources() {
        let m = std::env::temp_dir().join(format!("es32-top-pkg-build-m-{}", std::process::id()));
        fs::create_dir_all(&m).unwrap();
        fs::write(m.join("manifest.json"), r#"{"name":"w","version":"1.0.0"}"#).unwrap();
        let parent = m.join("payload_test");
        fs::create_dir_all(&parent).unwrap();
        fs::write(parent.join(".hidden"), b"y").unwrap();
        let out = m.join("out.espkg");
        let result = build(&m.join("manifest.json"), &out, &[parent.join(".hidden")]);
        assert!(result.is_err(), "dotfile payload source must be rejected");
        assert!(!out.exists());
        let _ = fs::remove_dir_all(&m);
    }
}
