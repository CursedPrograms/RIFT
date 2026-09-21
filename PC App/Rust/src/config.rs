//! Command-line configuration and repo-root discovery.

use std::path::{Path, PathBuf};
use std::time::Duration;

#[derive(Clone, Debug)]
pub struct Config {
    pub name: String,
    pub port: u16,
    pub ip: String,
    pub root: PathBuf,
    pub ttl: Duration,
    pub nora_host: String,
    pub nora_port: u16,
    pub heartbeat_every: Duration,
    pub no_heartbeat: bool,
    pub no_mdns: bool,
    pub no_internet_share: bool,
    pub scan: bool,
}

/// Same trick as app.py's `_get_ip()`: "connect" a UDP socket (no traffic is
/// sent) and read back which local address the OS would use.
pub fn local_ip() -> String {
    std::net::UdpSocket::bind("0.0.0.0:0")
        .and_then(|s| {
            s.connect("10.255.255.255:1")?;
            s.local_addr()
        })
        .map(|a| a.ip().to_string())
        .unwrap_or_else(|_| "127.0.0.1".into())
}

/// Walks up from the executable / working directory until it finds the RIFT
/// repo root (app.py next to templates/), so it works from PC App/Rust, from
/// the repo root, or from a built binary anywhere below it.
fn find_root() -> PathBuf {
    let mut starts = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            starts.push(dir.to_path_buf());
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        starts.push(cwd);
    }
    for start in &starts {
        let mut dir: Option<&Path> = Some(start);
        while let Some(d) = dir {
            if d.join("app.py").is_file() && d.join("templates").join("index.html").is_file() {
                return d.to_path_buf();
            }
            dir = d.parent();
        }
    }
    std::env::current_dir().unwrap_or_default()
}

impl Config {
    pub fn parse(args: impl IntoIterator<Item = String>) -> Result<Self, String> {
        let mut c = Config {
            name: "RIFT".into(),
            port: 5000,
            ip: local_ip(),
            root: PathBuf::new(),
            ttl: Duration::from_secs(20),
            nora_host: "192.168.4.1".into(),
            nora_port: 5000,
            heartbeat_every: Duration::from_secs(10),
            no_heartbeat: false,
            no_mdns: false,
            no_internet_share: false,
            scan: false,
        };
        let mut root: Option<PathBuf> = None;
        let mut it = args.into_iter();
        while let Some(a) = it.next() {
            let flag = a.trim_start_matches('-').to_string();
            let mut value = || it.next().ok_or_else(|| format!("--{flag} requires a value"));
            match flag.as_str() {
                "scan" => c.scan = true,
                "no-mdns" => c.no_mdns = true,
                "no-heartbeat" => c.no_heartbeat = true,
                "no-internet-share" => c.no_internet_share = true,
                "name" => c.name = value()?,
                "nora-host" => c.nora_host = value()?,
                "root" => root = Some(PathBuf::from(value()?)),
                "port" => c.port = num(&flag, &value()?)?,
                "nora-port" => c.nora_port = num(&flag, &value()?)?,
                "heartbeat-secs" => c.heartbeat_every = Duration::from_secs_f64(num(&flag, &value()?)?),
                "ttl-secs" => c.ttl = Duration::from_secs_f64(num(&flag, &value()?)?),
                "help" | "h" => return Err(USAGE.into()),
                _ => return Err(format!("unknown argument: {a}\n{USAGE}")),
            }
        }
        c.root = root.unwrap_or_else(find_root);
        Ok(c)
    }
}

fn num<T: std::str::FromStr>(flag: &str, text: &str) -> Result<T, String> {
    text.parse().map_err(|_| format!("--{flag} requires a number"))
}

const USAGE: &str = "usage: rift-rust [--name RIFT] [--port 5000] [--nora-host 192.168.4.1] [--nora-port 5000]
                 [--heartbeat-secs 10] [--ttl-secs 20] [--no-heartbeat] [--no-mdns]
                 [--no-internet-share] [--root <repo>] [--scan]";
