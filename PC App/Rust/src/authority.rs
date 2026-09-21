//! Announces this RIFT instance to a NORA hub as the fleet authority, over
//! HTTP/WiFi (default) or a Bluetooth serial link. Rust counterpart of
//! Fleet/register.py + Fleet/bt_link.py: while RIFT keeps heartbeating, NORA
//! defers her /robots response to point at RIFT; if it stops, the
//! registration simply expires on her side.

use crate::config::Config;
use std::io::{Read, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

const CAPABILITIES: &str = "fleet_management,monitoring";
const BT_BAUD: u32 = 115_200;

struct Running {
    stop: Arc<AtomicBool>,
    handle: JoinHandle<()>,
}

#[derive(Default)]
struct Inner {
    mode: String,
    bt_port: String,
    running: Option<Running>,
}

pub struct Authority {
    cfg: Config,
    inner: Mutex<Inner>,
}

impl Authority {
    pub fn new(cfg: Config) -> Self {
        Self { cfg, inner: Mutex::new(Inner { mode: "wifi".into(), ..Default::default() }) }
    }

    pub fn state(&self) -> (String, String) {
        let inner = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        (inner.mode.clone(), inner.bt_port.clone())
    }

    /// Retires the current heartbeat (if any) and starts one on the given transport.
    pub fn restart(&self, mode: &str, bt_port: &str) {
        let mut inner = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(r) = inner.running.take() {
            r.stop.store(true, Ordering::Relaxed);
            let _ = r.handle.join();
        }
        inner.mode = mode.to_string();
        inner.bt_port = bt_port.to_string();
        if self.cfg.no_heartbeat {
            return;
        }
        let stop = Arc::new(AtomicBool::new(false));
        let (cfg, stop2, mode, bt_port) = (self.cfg.clone(), stop.clone(), mode.to_string(), bt_port.to_string());
        let handle = std::thread::spawn(move || heartbeat_loop(cfg, stop2, mode, bt_port));
        inner.running = Some(Running { stop, handle });
    }

    pub fn stop(&self) {
        let mut inner = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(r) = inner.running.take() {
            r.stop.store(true, Ordering::Relaxed);
            let _ = r.handle.join();
        }
    }
}

fn heartbeat_loop(cfg: Config, stop: Arc<AtomicBool>, mode: String, bt_port: String) {
    let mut bt: Option<BtLink> = None;
    while !stop.load(Ordering::Relaxed) {
        if mode == "bluetooth" {
            let result = match bt.take() {
                Some(link) => Ok(link),
                None => BtLink::open(&bt_port),
            }
            .and_then(|mut link| link.register(&cfg.name, CAPABILITIES).map(|_| link));
            bt = result.ok(); // on any failure drop the link and reopen next round
        } else {
            announce_wifi(&cfg);
        }

        let mut waited = Duration::ZERO;
        while waited < cfg.heartbeat_every && !stop.load(Ordering::Relaxed) {
            std::thread::sleep(Duration::from_millis(100));
            waited += Duration::from_millis(100);
        }
    }
}

fn announce_wifi(cfg: &Config) {
    // NORA may not be reachable yet (booting, or not on her AP) - keep retrying.
    let _ = ureq::post(&format!("http://{}:{}/register", cfg.nora_host, cfg.nora_port))
        .timeout(Duration::from_secs(2))
        .send_form(&[("name", &cfg.name), ("type", "fleet_manager"), ("capabilities", CAPABILITIES)]);
}

/// The fleet-registration half of NORA's Bluetooth protocol: send
/// "H<name>:<cap1,cap2>\n", she replies "OK\n" or "ERR\n".
struct BtLink {
    port: Box<dyn serialport::SerialPort>,
}

impl BtLink {
    fn open(name: &str) -> Result<Self, String> {
        let port = serialport::new(name, BT_BAUD).timeout(Duration::from_secs(2)).open().map_err(|e| e.to_string())?;
        Ok(Self { port })
    }

    fn register(&mut self, name: &str, capabilities: &str) -> Result<bool, String> {
        let _ = self.port.clear(serialport::ClearBuffer::Input);
        self.port.write_all(format!("H{name}:{capabilities}\n").as_bytes()).map_err(|e| e.to_string())?;
        let mut line = Vec::new();
        let mut byte = [0u8; 1];
        loop {
            match self.port.read(&mut byte) {
                Ok(1) if byte[0] == b'\n' => break,
                Ok(1) => line.push(byte[0]),
                Ok(_) => return Err("connection closed".into()),
                Err(e) => return Err(e.to_string()), // includes the 2s read timeout
            }
        }
        Ok(String::from_utf8_lossy(&line).trim() == "OK")
    }
}
