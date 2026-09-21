//! RIFT fleet hub, Rust edition: the same fleet registry, dashboard, mDNS
//! discovery, NORA fleet-authority heartbeat (WiFi or Bluetooth) and internet
//! share as app.py, as one native binary. Speaks the same protocol on the same
//! port as app.py and the C++ server, so run one or the other on a given
//! machine, not both.
//!
//!   rift-rust           start the hub on :5000
//!   rift-rust --scan    scan this /24 for hubs/robots serving /robots

mod authority;
mod config;
mod mdns;
mod registry;
mod scan;
mod server;
mod share;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc};

fn main() {
    let cfg = match config::Config::parse(std::env::args().skip(1)) {
        Ok(c) => c,
        Err(msg) => {
            eprintln!("{msg}");
            std::process::exit(1);
        }
    };

    if cfg.scan {
        scan::run(&cfg.ip, cfg.port);
        return;
    }

    println!("[RIFT] IP   : {}\n[RIFT] Port : {}\n[RIFT] Root : {}", cfg.ip, cfg.port, cfg.root.display());

    let peers = Arc::new(mdns::Peers::default());
    let mdns_daemon = if cfg.no_mdns {
        None
    } else {
        match mdns::start(&cfg, peers.clone()) {
            Ok(d) => {
                println!("[RIFT] Zeroconf registered as {}; watching {:?}", cfg.name, mdns::BROWSE_TYPES);
                Some(d)
            }
            Err(e) => {
                println!("[RIFT] Continuing without mDNS: {e}");
                None
            }
        }
    };

    let authority = authority::Authority::new(cfg.clone());
    authority.restart("wifi", "");
    if cfg.no_heartbeat {
        println!("[RIFT] Not announcing to NORA (--no-heartbeat)");
    } else {
        println!("[RIFT] Announcing to NORA at {}:{} as fleet authority (mode: wifi)", cfg.nora_host, cfg.nora_port);
    }

    let stop_share = Arc::new(AtomicBool::new(false));
    if !cfg.no_internet_share {
        share::start(stop_share.clone());
    }

    let state = Arc::new(server::State {
        registry: registry::Registry::new(cfg.ttl),
        peers,
        authority,
        cfg,
    });
    let http = match server::start(state.clone()) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("[RIFT] server error: {e}");
            std::process::exit(1);
        }
    };

    let (tx, rx) = mpsc::channel();
    let _ = ctrlc::set_handler(move || {
        let _ = tx.send(());
    });
    let _ = rx.recv(); // wait for Ctrl+C / SIGTERM

    http.unblock();
    stop_share.store(true, Ordering::Relaxed);
    state.authority.stop();
    if let Some(d) = mdns_daemon {
        let _ = d.shutdown();
    }
    println!("[RIFT] Shut down.");
}
