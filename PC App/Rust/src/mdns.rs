//! Zeroconf: publish this instance as _rift._tcp and watch for other RIFT
//! instances and ComCentre (_flask-link._tcp). Rust counterpart of app.py's
//! `_start_zeroconf()` / `_PeerListener` - browsing both is what lets DREAM
//! show up in this dashboard without ComCentre knowing anything about RIFT.

use crate::config::Config;
use mdns_sd::{ServiceDaemon, ServiceEvent, ServiceInfo};
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};

pub const BROWSE_TYPES: [&str; 2] = ["_rift._tcp.local.", "_flask-link._tcp.local."];

/// name -> "http://ip:port" for every peer seen over mDNS.
#[derive(Default)]
pub struct Peers {
    items: Mutex<BTreeMap<String, String>>,
}

impl Peers {
    pub fn snapshot(&self) -> BTreeMap<String, String> {
        self.items.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    fn set(&self, name: &str, url: String) {
        self.items.lock().unwrap_or_else(|e| e.into_inner()).insert(name.to_string(), url);
    }

    fn remove(&self, name: &str) {
        self.items.lock().unwrap_or_else(|e| e.into_inner()).remove(name);
    }
}

/// Publishes the service and starts browsing. Dropping/shutting down the
/// returned daemon unregisters everything.
pub fn start(cfg: &Config, peers: Arc<Peers>) -> Result<ServiceDaemon, String> {
    let daemon = ServiceDaemon::new().map_err(|e| e.to_string())?;

    let info = ServiceInfo::new(
        "_rift._tcp.local.",
        &cfg.name,
        &format!("{}.local.", cfg.name),
        cfg.ip.as_str(),
        cfg.port,
        &[("role", "fleet_manager")][..],
    )
    .map_err(|e| e.to_string())?;
    daemon.register(info).map_err(|e| e.to_string())?;

    for service in BROWSE_TYPES {
        let receiver = daemon.browse(service).map_err(|e| e.to_string())?;
        let (peers, own) = (peers.clone(), cfg.name.clone());
        std::thread::spawn(move || {
            while let Ok(event) = receiver.recv() {
                match event {
                    ServiceEvent::ServiceResolved(info) => {
                        let short = info.get_fullname().split('.').next().unwrap_or("").to_string();
                        if short == own || short.is_empty() {
                            continue;
                        }
                        let addr = info.get_addresses_v4().into_iter().next();
                        if let Some(addr) = addr {
                            peers.set(&short, format!("http://{addr}:{}", info.get_port()));
                        }
                    }
                    ServiceEvent::ServiceRemoved(_, fullname) => {
                        peers.remove(fullname.split('.').next().unwrap_or(""));
                    }
                    _ => {}
                }
            }
        });
    }
    Ok(daemon)
}
