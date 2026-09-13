//! A lightweight, btop-inspired monitor for the ESP32 serial telemetry stream.
use anyhow::{Context, Result};
use crossterm::{
    cursor,
    event::{self, Event, KeyCode},
    execute,
    style::{Color, Print, ResetColor, SetBackgroundColor, SetForegroundColor},
    terminal::{self, Clear, ClearType, EnterAlternateScreen, LeaveAlternateScreen},
};
use serde::Deserialize;
use serde_json::Value;
use std::{
    cmp::Ordering,
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

const CONFIG_EXAMPLE: &str =
    r#"{ "theme": "ocean", "refresh_ms": 250, "show_system_tasks": true }"#;

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
enum ThemeName {
    Ocean,
    Forest,
    Amber,
}
impl ThemeName {
    fn next(self) -> Self {
        match self {
            Self::Ocean => Self::Forest,
            Self::Forest => Self::Amber,
            Self::Amber => Self::Ocean,
        }
    }
    fn label(self) -> &'static str {
        match self {
            Self::Ocean => "OCEAN",
            Self::Forest => "FOREST",
            Self::Amber => "AMBER",
        }
    }
    fn palette(self) -> Palette {
        match self {
            Self::Ocean => Palette::new(Color::Cyan, Color::Green, Color::Yellow),
            Self::Forest => Palette::new(Color::Green, Color::Cyan, Color::Yellow),
            Self::Amber => Palette::new(Color::Yellow, Color::Green, Color::Red),
        }
    }
}
impl Default for ThemeName {
    fn default() -> Self {
        Self::Ocean
    }
}
#[derive(Clone, Copy)]
struct Palette {
    accent: Color,
    good: Color,
    text: Color,
    dim: Color,
    background: Color,
}
impl Palette {
    fn new(accent: Color, good: Color, _warn: Color) -> Self {
        Self {
            accent,
            good,
            text: Color::White,
            dim: Color::DarkGrey,
            background: Color::Black,
        }
    }
}

#[derive(Deserialize)]
struct FileConfig {
    theme: Option<ThemeName>,
    refresh_ms: Option<u64>,
    show_system_tasks: Option<bool>,
}
struct Settings {
    theme: ThemeName,
    refresh: Duration,
    show_system_tasks: bool,
}
impl Settings {
    fn load(path: Option<&Path>, theme: Option<&str>, refresh_ms: Option<u64>) -> Result<Self> {
        let mut file = FileConfig {
            theme: None,
            refresh_ms: None,
            show_system_tasks: None,
        };
        let config_path = path.map(PathBuf::from).or_else(default_config_path);
        if let Some(path) = config_path.as_deref() {
            if path.exists() {
                file = serde_json::from_slice(
                    &fs::read(path)
                        .with_context(|| format!("cannot read config {}", path.display()))?,
                )
                .with_context(|| {
                    format!(
                        "invalid config {}; expected JSON like {CONFIG_EXAMPLE}",
                        path.display()
                    )
                })?;
            }
        }
        let theme = theme
            .map(parse_theme)
            .transpose()?
            .or(file.theme)
            .unwrap_or_default();
        Ok(Self {
            theme,
            refresh: Duration::from_millis(
                refresh_ms
                    .or(file.refresh_ms)
                    .unwrap_or(250)
                    .clamp(50, 5_000),
            ),
            show_system_tasks: file.show_system_tasks.unwrap_or(true),
        })
    }
}
fn default_config_path() -> Option<PathBuf> {
    std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|v| PathBuf::from(v).join(".config")))
        .map(|p| p.join("es32-top/config.json"))
}
fn parse_theme(name: &str) -> Result<ThemeName> {
    match name.to_ascii_lowercase().as_str() {
        "ocean" => Ok(ThemeName::Ocean),
        "forest" => Ok(ThemeName::Forest),
        "amber" => Ok(ThemeName::Amber),
        _ => anyhow::bail!("unknown theme {name}; choose ocean, forest, or amber"),
    }
}

fn n(v: &Value, key: &str) -> f64 {
    v.get(key).and_then(Value::as_f64).unwrap_or(0.0)
}
fn u(v: &Value, key: &str) -> u64 {
    v.get(key).and_then(Value::as_u64).unwrap_or(0)
}
fn s(v: &Value, key: &str) -> String {
    v.get(key).and_then(Value::as_str).unwrap_or("—").to_owned()
}
fn bytes(v: u64) -> String {
    if v < 1024 {
        format!("{v} B")
    } else if v < 1_048_576 {
        format!("{:.1} KiB", v as f64 / 1024.0)
    } else {
        format!("{:.1} MiB", v as f64 / 1_048_576.0)
    }
}
fn uptime(ms: u64) -> String {
    format!(
        "{:02}:{:02}:{:02}",
        ms / 3_600_000,
        (ms / 60_000) % 60,
        (ms / 1_000) % 60
    )
}
fn bar(v: f64, width: usize) -> String {
    let on = ((v.clamp(0.0, 100.0) / 100.0) * width as f64).round() as usize;
    format!("{}{}", "█".repeat(on), "░".repeat(width.saturating_sub(on)))
}
fn trim(v: &str, width: usize) -> String {
    v.chars().take(width).collect()
}
fn at(out: &mut impl Write, x: u16, y: u16, c: Color, v: impl AsRef<str>) -> Result<()> {
    execute!(
        out,
        cursor::MoveTo(x, y),
        SetForegroundColor(c),
        Print(v.as_ref())
    )?;
    Ok(())
}
fn rule(out: &mut impl Write, y: u16, width: u16, p: Palette) -> Result<()> {
    at(out, 0, y, p.dim, "─".repeat(width as usize))
}
fn panel(out: &mut impl Write, x: u16, y: u16, width: u16, title: &str, p: Palette) -> Result<()> {
    if width >= 8 {
        at(out, x, y, p.accent, format!("┌─ {title} "))?;
        at(
            out,
            x + 3 + title.len() as u16,
            y,
            p.dim,
            "─".repeat((width as usize).saturating_sub(title.len() + 3)),
        )?;
    }
    Ok(())
}

fn render(data: &Value, st: &Settings, sort_cpu: bool, help: bool) -> Result<()> {
    let mut out = std::io::stdout();
    let (w, h) = terminal::size()?;
    let p = st.theme.palette();
    execute!(
        out,
        cursor::Hide,
        SetBackgroundColor(p.background),
        Clear(ClearType::All)
    )?;
    at(
        &mut out,
        0,
        0,
        p.accent,
        format!(
            " ESP-TOP  •  {}  •  {} MHz ",
            s(data, "chip"),
            u(data, "cpu_mhz")
        ),
    )?;
    at(
        &mut out,
        w.saturating_sub(31),
        0,
        p.dim,
        format!("{}  [?] help  [q] quit", st.theme.label()),
    )?;
    rule(&mut out, 1, w, p)?;
    if help {
        render_help(&mut out, w, h, p)?;
        out.flush()?;
        return Ok(());
    }
    let compact = w < 82;
    let left = if compact { w } else { w / 2 };
    panel(&mut out, 0, 2, left, "PROCESSOR", p)?;
    for (i, value) in [n(data, "cpu_core0"), n(data, "cpu_core1")]
        .iter()
        .enumerate()
    {
        at(
            &mut out,
            2,
            3 + i as u16,
            p.text,
            format!(
                "CORE {i}  {} {:>5.1}%",
                bar(*value, if compact { 18 } else { 12 }),
                value
            ),
        )?;
    }
    if !compact {
        panel(&mut out, left + 1, 2, w - left - 1, "MEMORY", p)?;
        let total = u(data, "total_heap");
        let used = total.saturating_sub(u(data, "heap"));
        let pct = if total == 0 {
            0.0
        } else {
            used as f64 * 100.0 / total as f64
        };
        at(
            &mut out,
            left + 3,
            3,
            p.text,
            format!("HEAP  {} {:>5.1}%", bar(pct, 11), pct),
        )?;
        at(
            &mut out,
            left + 3,
            4,
            p.dim,
            format!(
                "free {}  low {}",
                bytes(u(data, "heap")),
                bytes(u(data, "min_heap"))
            ),
        )?;
    }
    let row = 6;
    let wifi = if n(data, "rssi") == 0.0 {
        "offline".to_owned()
    } else {
        format!("{} dBm", n(data, "rssi") as i64)
    };
    at(
        &mut out,
        1,
        row,
        p.dim,
        format!(
            "UP {}   WIFI {}   FLASH {}   PSRAM {}",
            uptime(u(data, "uptime_ms")),
            wifi,
            bytes(u(data, "flash")),
            bytes(u(data, "psram"))
        ),
    )?;
    rule(&mut out, row + 1, w, p)?;
    at(
        &mut out,
        0,
        row + 2,
        p.accent,
        format!(
            " TASKS  {:>3}  {}",
            u(data, "task_count"),
            if sort_cpu { "CPU ↓" } else { "NAME" }
        ),
    )?;
    at(
        &mut out,
        0,
        row + 3,
        p.dim,
        if compact {
            " PID    NAME                 STATE       STACK"
        } else {
            " PID    NAME                 STATE       CPU    STACK       PRIORITY"
        },
    )?;
    let mut tasks = data
        .get("tasks")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if !st.show_system_tasks {
        tasks.retain(|t| !t.get("protected").and_then(Value::as_bool).unwrap_or(false));
    }
    if sort_cpu {
        tasks.sort_by(|a, b| {
            n(b, "cpu")
                .partial_cmp(&n(a, "cpu"))
                .unwrap_or(Ordering::Equal)
        });
    }
    for (i, task) in tasks
        .iter()
        .take(h.saturating_sub(row + 6) as usize)
        .enumerate()
    {
        let protected = task
            .get("protected")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let color = if protected {
            p.dim
        } else if s(task, "state").eq_ignore_ascii_case("running") {
            p.good
        } else {
            p.text
        };
        let line = if compact {
            format!(
                " {:<6} {:<20} {:<11} {}",
                u(task, "pid"),
                trim(&s(task, "name"), 20),
                trim(&s(task, "state"), 11),
                bytes(u(task, "stack_hwm"))
            )
        } else {
            format!(
                " {:<6} {:<20} {:<11} {:>5.1}%  {:<11} {:>3}",
                u(task, "pid"),
                trim(&s(task, "name"), 20),
                trim(&s(task, "state"), 11),
                n(task, "cpu"),
                bytes(u(task, "stack_hwm")),
                u(task, "priority")
            )
        };
        at(&mut out, 0, row + 4 + i as u16, color, line)?;
    }
    at(
        &mut out,
        0,
        h.saturating_sub(1),
        p.dim,
        " [h/?] help  [t] theme  [s] sort  [i] system tasks  [+/-] refresh ",
    )?;
    execute!(out, ResetColor)?;
    out.flush()?;
    Ok(())
}
fn render_help(out: &mut impl Write, w: u16, h: u16, p: Palette) -> Result<()> {
    let x = w.saturating_sub(54) / 2;
    let y = h.saturating_sub(13) / 2;
    panel(out, x, y, 54, "ESP-TOP KEYBOARD SHORTCUTS", p)?;
    for (i, line) in [
        "q / Esc     Quit monitor",
        "h / ?       Toggle this help",
        "t           Cycle Ocean, Forest, Amber themes",
        "s           Sort tasks by CPU usage",
        "i           Show/hide protected system tasks",
        "+ / -       Increase/decrease refresh interval",
        "",
        "Config: ~/.config/es32-top/config.json",
        "Use --config FILE, --theme NAME, --refresh-ms N",
    ]
    .iter()
    .enumerate()
    {
        at(
            out,
            x + 2,
            y + 2 + i as u16,
            if i < 6 { p.text } else { p.dim },
            line,
        )?;
    }
    Ok(())
}

pub fn list_ports() -> Result<()> {
    for port in serialport::available_ports()? {
        println!("{}\t{:?}", port.port_name, port.port_type);
    }
    Ok(())
}
pub fn run(
    port: &str,
    baud: u32,
    config: Option<&Path>,
    theme: Option<&str>,
    refresh_ms: Option<u64>,
) -> Result<()> {
    let mut st = Settings::load(config, theme, refresh_ms)?;
    let mut serial = serialport::new(port, baud)
        .timeout(Duration::from_millis(50))
        .open()
        .with_context(|| format!("cannot open serial port {port}"))?;
    terminal::enable_raw_mode()?;
    let mut out = std::io::stdout();
    execute!(out, EnterAlternateScreen, cursor::Hide)?;
    let mut buffer = String::new();
    let mut data = Value::Object(Default::default());
    let mut help = false;
    let mut sort_cpu = false;
    let mut drawn = Instant::now() - st.refresh;
    let result = loop {
        let mut chunk = [0; 2048];
        match serial.read(&mut chunk) {
            Ok(count) => buffer.push_str(&String::from_utf8_lossy(&chunk[..count])),
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::Interrupted
                ) => {}
            Err(e) => break Err(e.into()),
        };
        while let Some(end) = buffer.find('\n') {
            let line = buffer[..end].trim().to_owned();
            buffer.drain(..=end);
            if let Ok(next) = serde_json::from_str(&line) {
                data = next;
            }
        }
        if buffer.len() > 65_536 {
            buffer.clear();
        }
        if drawn.elapsed() >= st.refresh {
            render(&data, &st, sort_cpu, help)?;
            drawn = Instant::now();
        }
        if event::poll(Duration::from_millis(10))? {
            if let Event::Key(key) = event::read()? {
                match key.code {
                    KeyCode::Char('q') | KeyCode::Char('Q') | KeyCode::Esc => break Ok(()),
                    KeyCode::Char('h') | KeyCode::Char('?') => help = !help,
                    KeyCode::Char('t') => st.theme = st.theme.next(),
                    KeyCode::Char('s') => sort_cpu = !sort_cpu,
                    KeyCode::Char('i') => st.show_system_tasks = !st.show_system_tasks,
                    KeyCode::Char('+') => {
                        st.refresh =
                            (st.refresh + Duration::from_millis(50)).min(Duration::from_secs(5))
                    }
                    KeyCode::Char('-') => {
                        st.refresh = st
                            .refresh
                            .saturating_sub(Duration::from_millis(50))
                            .max(Duration::from_millis(50))
                    }
                    _ => {}
                }
            }
        }
    };
    let cleanup = execute!(out, ResetColor, cursor::Show, LeaveAlternateScreen);
    terminal::disable_raw_mode()?;
    cleanup?;
    result
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn formatters() {
        assert_eq!(bytes(1536), "1.5 KiB");
        assert_eq!(uptime(3_661_000), "01:01:01");
        assert_eq!(bar(50.0, 4), "██░░");
    }
    #[test]
    fn themes() {
        assert!(parse_theme("forest").is_ok());
        assert!(parse_theme("purple").is_err());
    }
}
