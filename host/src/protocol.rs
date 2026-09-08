use anyhow::{Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::{SystemTime, UNIX_EPOCH};

pub const VERSION: &str = "1.0";
#[derive(Debug, Serialize, Deserialize)]
pub struct Envelope { pub protocol: String, #[serde(rename = "type")] pub message_type: String, pub request_id: String, pub timestamp: f64, pub payload: Value }
pub fn encode(message_type: &str, payload: Value, request_id: impl Into<String>) -> Result<String> { let envelope = Envelope { protocol: VERSION.into(), message_type: message_type.into(), request_id: request_id.into(), timestamp: SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs_f64(), payload }; Ok(format!("{}\n", serde_json::to_string(&envelope)?)) }
pub fn decode(frame: &str) -> Result<Envelope> { let envelope: Envelope = serde_json::from_str(frame)?; if envelope.protocol != VERSION { bail!("unsupported protocol version: {}", envelope.protocol) } if !envelope.payload.is_object() { bail!("protocol payload must be an object") } Ok(envelope) }
