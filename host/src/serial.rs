use anyhow::{bail, Context, Result};
use serialport::{SerialPort, SerialPortInfo, SerialPortType};

fn is_esp_usb(port: &SerialPortInfo) -> bool {
    match &port.port_type {
        SerialPortType::UsbPort(info) => matches!(info.vid, 0x10c4 | 0x1a86 | 0x0403 | 0x303a),
        _ => false,
    }
}

pub fn available() -> Result<Vec<SerialPortInfo>> { Ok(serialport::available_ports()?) }

pub fn choose(override_path: Option<&str>) -> Result<String> {
    if let Some(path) = override_path.filter(|path| !path.is_empty()) { return Ok(path.to_string()); }
    let ports = available()?;
    let matches: Vec<_> = ports.iter().filter(|p| is_esp_usb(p)).collect();
    if matches.len() == 1 { return Ok(matches[0].port_name.clone()); }
    if matches.is_empty() { bail!("no ESP32 USB serial port found; pass --port explicitly or check USB permissions") }
    let choices = matches.iter().map(|p| p.port_name.as_str()).collect::<Vec<_>>().join(", ");
    bail!("multiple ESP32 serial ports found ({choices}); pass --port explicitly")
}

pub fn open(path: Option<&str>, baud: u32) -> Result<Box<dyn SerialPort>> {
    let selected = choose(path)?;
    serialport::new(&selected, baud).timeout(std::time::Duration::from_millis(25)).open().map_err(|e| {
        if e.kind() == serialport::ErrorKind::Io(std::io::ErrorKind::PermissionDenied) {
            anyhow::anyhow!("permission denied opening {selected}; on Linux add your user to the dialout group and log in again, then retry")
        } else { anyhow::anyhow!("cannot open serial port {selected}: {e}") }
    })
}

pub fn describe() -> Result<()> { for port in available()? { println!("{}\t{:?}", port.port_name, port.port_type); } Ok(()) }
