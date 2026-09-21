//! Shares this RIFT instance's existing internet connection out to every
//! device that joins NORA's isolated WiFi AP. Rust counterpart of
//! Fleet/internet_share.py: join NORA's AP as a secondary connection over a
//! spare WiFi radio, then let NetworkManager's "shared" method (its own DHCP
//! server + NAT) hand internet access to NORA and anything else on her AP,
//! while RIFT's own default route is left alone. Linux + NetworkManager only;
//! anywhere else it quietly does nothing.

use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

const NORA_SSID: &str = "NORA";
const NORA_PASSWORD: &str = "12345678";
const INTERVAL: Duration = Duration::from_secs(30);

/// Runs nmcli, killing it if it hasn't finished within `timeout`.
fn nmcli(timeout: Duration, args: &[&str]) -> Option<String> {
    let mut child = Command::new("nmcli").args(args).stdout(Stdio::piped()).stderr(Stdio::null()).spawn().ok()?;
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(50)),
            _ => {
                let _ = child.kill();
                return None;
            }
        }
    }
    let out = child.wait_with_output().ok()?;
    Some(String::from_utf8_lossy(&out.stdout).into_owned())
}

fn lines(s: &str) -> Vec<String> {
    s.lines().map(str::trim).filter(|l| !l.is_empty()).map(str::to_string).collect()
}

fn wifi_iface() -> Option<String> {
    let out = nmcli(Duration::from_secs(20), &["-t", "-f", "DEVICE,TYPE", "device", "status"])?;
    lines(&out).into_iter().find_map(|l| {
        let mut parts = l.split(':');
        let (device, kind) = (parts.next()?, parts.next()?);
        (kind == "wifi").then(|| device.to_string())
    })
}

fn active_connections() -> Vec<String> {
    nmcli(Duration::from_secs(20), &["-t", "-f", "NAME", "connection", "show", "--active"]).map(|o| lines(&o)).unwrap_or_default()
}

/// Joins NORA's AP (if not already) and marks it shared. Safe to call
/// repeatedly; a no-op once already connected and shared.
fn ensure_internet_share() -> bool {
    let Some(iface) = wifi_iface() else { return false };
    if active_connections().iter().any(|c| c == NORA_SSID) {
        return true;
    }
    let Some(known) = nmcli(Duration::from_secs(20), &["-t", "-f", "NAME", "connection", "show"]) else { return false };
    if !lines(&known).iter().any(|c| c == NORA_SSID) {
        nmcli(Duration::from_secs(30), &["device", "wifi", "connect", NORA_SSID, "password", NORA_PASSWORD, "ifname", &iface]);
        nmcli(Duration::from_secs(20), &["connection", "modify", NORA_SSID, "ipv4.method", "shared"]);
    } else {
        nmcli(Duration::from_secs(30), &["connection", "up", NORA_SSID]);
    }
    active_connections().iter().any(|c| c == NORA_SSID)
}

/// Keeps NORA's AP joined and shared until `stop` is set.
pub fn start(stop: Arc<AtomicBool>) {
    if !cfg!(target_os = "linux") || Command::new("nmcli").arg("--version").output().is_err() {
        return;
    }
    std::thread::spawn(move || {
        while !stop.load(Ordering::Relaxed) {
            ensure_internet_share();
            let mut waited = Duration::ZERO;
            while waited < INTERVAL && !stop.load(Ordering::Relaxed) {
                std::thread::sleep(Duration::from_millis(200));
                waited += Duration::from_millis(200);
            }
        }
    });
}
