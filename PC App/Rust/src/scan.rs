//! `--scan`: the subnet-scanning client (Rust counterpart of
//! PC App/App/registration.cpp and PC App/PyGame/registration.py). Queries every
//! host on this machine's /24 for :<port>/robots and prints whatever answers.

use serde_json::Value;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

pub fn run(local_ip: &str, port: u16) {
    let base = local_ip.rsplit_once('.').map(|(b, _)| b.to_string()).unwrap_or_else(|| "192.168.1".into()); // assumes a /24
    println!("Scanning {base}.1-254 on port {port}...");

    let next = Arc::new(AtomicUsize::new(1));
    let found: Arc<Mutex<Vec<(String, Vec<Value>)>>> = Arc::default();
    let workers: Vec<_> = (0..50)
        .map(|_| {
            let (next, found, base) = (next.clone(), found.clone(), base.clone());
            std::thread::spawn(move || loop {
                let i = next.fetch_add(1, Ordering::Relaxed);
                if i > 254 {
                    return;
                }
                let ip = format!("{base}.{i}");
                let Ok(resp) = ureq::get(&format!("http://{ip}:{port}/robots")).timeout(Duration::from_millis(500)).call() else {
                    continue;
                };
                // RIFT and NORA both serve {"authority": "...", "robots": [...]}, not a bare array.
                if let Some(body) = resp.into_string().ok().and_then(|t| serde_json::from_str::<Value>(&t).ok()) {
                    if let Some(robots) = body.get("robots").and_then(Value::as_array) {
                        found.lock().unwrap().push((ip, robots.clone()));
                    }
                }
            })
        })
        .collect();
    for w in workers {
        let _ = w.join();
    }

    println!("\n=== Robots Found ===");
    let mut found = found.lock().unwrap().clone();
    found.sort_by(|a, b| a.0.cmp(&b.0));
    for (ip, robots) in found {
        for r in robots {
            let text = |k: &str| r.get(k).and_then(Value::as_str).unwrap_or("").to_string();
            let caps: Vec<String> =
                r.get("capabilities").and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_str).map(str::to_string).collect();
            println!("{} ({}) @ {ip}\n  Capabilities: {}\n", text("name"), text("type"), caps.join(" "));
        }
    }
}
