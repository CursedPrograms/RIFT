//! Fleet registry: robots/managers that have called POST /register, expiring
//! after the TTL unless they keep heartbeating. Rust counterpart of app.py's
//! `_fleet` dict + `_prune_fleet()`.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

#[derive(Clone, Debug, PartialEq)]
pub struct Robot {
    pub name: String,
    pub ip: String,
    pub kind: String,
    pub capabilities: Vec<String>,
}

struct Member {
    robot: Robot,
    last_seen: Instant,
}

#[derive(Default)]
struct Inner {
    members: HashMap<String, Member>,
    order: Vec<String>, // insertion order, like a Python dict
}

pub struct Registry {
    ttl: Duration,
    inner: Mutex<Inner>,
}

impl Registry {
    pub fn new(ttl: Duration) -> Self {
        Self { ttl, inner: Mutex::new(Inner::default()) }
    }

    pub fn register(&self, name: &str, ip: &str, kind: &str, capabilities: Vec<String>) {
        self.register_at(name, ip, kind, capabilities, Instant::now());
    }

    fn register_at(&self, name: &str, ip: &str, kind: &str, capabilities: Vec<String>, now: Instant) {
        let mut inner = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        if !inner.members.contains_key(name) {
            inner.order.push(name.to_string());
        }
        let robot = Robot { name: name.into(), ip: ip.into(), kind: kind.into(), capabilities };
        inner.members.insert(name.to_string(), Member { robot, last_seen: now });
    }

    /// The live roster, dropping anything not heard from within the TTL.
    pub fn robots(&self) -> Vec<Robot> {
        self.robots_at(Instant::now())
    }

    fn robots_at(&self, now: Instant) -> Vec<Robot> {
        let mut inner = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        let ttl = self.ttl;
        let stale: Vec<String> = inner
            .members
            .iter()
            .filter(|(_, m)| now.saturating_duration_since(m.last_seen) > ttl)
            .map(|(n, _)| n.clone())
            .collect();
        for name in &stale {
            inner.members.remove(name);
        }
        inner.order.retain(|n| !stale.contains(n));
        inner.order.iter().map(|n| inner.members[n].robot.clone()).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn register_and_expire() {
        let start = Instant::now();
        let r = Registry::new(Duration::from_secs(20));
        r.register_at("ARM", "10.0.0.5", "robot", vec!["arm".into()], start);
        r.register_at("KIDA", "10.0.0.6", "robot", vec![], start);
        let names = |v: Vec<Robot>| v.into_iter().map(|r| r.name).collect::<Vec<_>>();
        assert_eq!(names(r.robots_at(start)), ["ARM", "KIDA"]);

        r.register_at("ARM", "10.0.0.5", "robot", vec!["arm".into()], start + Duration::from_secs(15));
        // KIDA is now 25s stale, ARM 10s.
        assert_eq!(names(r.robots_at(start + Duration::from_secs(25))), ["ARM"]);
    }

    #[test]
    fn re_register_keeps_position() {
        let now = Instant::now();
        let r = Registry::new(Duration::from_secs(60));
        r.register_at("A", "1", "t", vec![], now);
        r.register_at("B", "2", "t", vec![], now);
        r.register_at("A", "3", "t", vec![], now);
        let got = r.robots_at(now);
        assert_eq!((got[0].name.as_str(), got[0].ip.as_str(), got[1].name.as_str()), ("A", "3", "B"));
    }
}
