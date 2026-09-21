//! HTTP fleet registry + dashboard. Same wire protocol as app.py's Flask routes
//! (and NORA's fleet server), so PC App/PyGame/registration.py,
//! PC App/App/registration.cpp and every robot's heartbeat work unchanged.

use crate::authority::Authority;
use crate::config::Config;
use crate::mdns::Peers;
use crate::registry::Registry;
use serde_json::{json, Map, Value};
use std::path::{Component, Path};
use std::sync::Arc;
use tiny_http::{Header, Method, Request, Response, Server};

pub struct State {
    pub cfg: Config,
    pub registry: Registry,
    pub peers: Arc<Peers>,
    pub authority: Authority,
}

fn header(name: &str, value: &str) -> Header {
    Header::from_bytes(name.as_bytes(), value.as_bytes()).expect("valid header")
}

fn respond(request: Request, status: u16, content_type: &str, body: impl Into<Vec<u8>>) {
    let response = Response::from_data(body.into())
        .with_status_code(status)
        .with_header(header("Content-Type", content_type));
    let _ = request.respond(response);
}

fn respond_json(request: Request, status: u16, body: Value) {
    respond(request, status, "application/json", body.to_string());
}

fn percent_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'+' => out.push(b' '),
            b'%' if i + 2 < bytes.len() => {
                let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).ok().and_then(|h| u8::from_str_radix(h, 16).ok());
                match hex {
                    Some(b) => {
                        out.push(b);
                        i += 2;
                    }
                    None => out.push(b'%'),
                }
            }
            b => out.push(b),
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn parse_form(body: &str) -> std::collections::HashMap<String, String> {
    body.split('&')
        .filter(|p| !p.is_empty())
        .map(|p| match p.split_once('=') {
            Some((k, v)) => (percent_decode(k), percent_decode(v)),
            None => (percent_decode(p), String::new()),
        })
        .collect()
}

/// Fills in the handful of Jinja expressions templates/index.html uses:
/// {{ this_name }}, {{ my_ip }}, {{ this_port }} and url_for('static', filename=...).
pub fn render_template(tpl: &str, vars: &[(&str, String)]) -> String {
    let mut out = String::with_capacity(tpl.len());
    let mut rest = tpl;
    while let Some(start) = rest.find("{{") {
        out.push_str(&rest[..start]);
        let after = &rest[start + 2..];
        let Some(end) = after.find("}}") else {
            out.push_str(&rest[start..]);
            rest = "";
            break;
        };
        let expr = after[..end].trim();
        if let Some((_, v)) = vars.iter().find(|(k, _)| *k == expr) {
            out.push_str(v);
        } else if let Some(file) = url_for_static(expr) {
            out.push_str("/static/");
            out.push_str(&file);
        } else {
            out.push_str(&rest[start..start + 2 + end + 2]);
        }
        rest = &after[end + 2..];
    }
    out.push_str(rest);
    out
}

fn url_for_static(expr: &str) -> Option<String> {
    let inner = expr.strip_prefix("url_for(")?.strip_suffix(')')?;
    let (first, second) = inner.split_once(',')?;
    if first.trim() != "'static'" {
        return None;
    }
    let value = second.trim().strip_prefix("filename")?.trim().strip_prefix('=')?.trim();
    Some(value.strip_prefix('\'')?.strip_suffix('\'')?.to_string())
}

fn content_type_for(path: &Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()).unwrap_or("") {
        "css" => "text/css; charset=utf-8",
        "js" => "application/javascript; charset=utf-8",
        "html" => "text/html; charset=utf-8",
        "json" => "application/json",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "ico" => "image/x-icon",
        _ => "application/octet-stream",
    }
}

fn split_caps(csv: &str) -> Vec<String> {
    csv.split(',').filter(|c| !c.is_empty()).map(str::to_string).collect()
}

fn read_body(request: &mut Request) -> String {
    let mut body = String::new();
    let _ = request.as_reader().read_to_string(&mut body);
    body
}

fn is_json(request: &Request) -> bool {
    request
        .headers()
        .iter()
        .any(|h| h.field.equiv("Content-Type") && h.value.as_str().starts_with("application/json"))
}

fn handle_register(mut request: Request, state: &State) {
    let is_json = is_json(&request);
    let body = read_body(&mut request);
    let (name, ip, kind, caps): (String, String, String, Vec<String>) = if is_json {
        let v: Value = serde_json::from_str(&body).unwrap_or(Value::Null);
        let text = |k: &str| v.get(k).and_then(Value::as_str).unwrap_or("").to_string();
        let caps = match v.get("capabilities") {
            Some(Value::Array(a)) => a.iter().filter_map(Value::as_str).map(str::to_string).collect(),
            Some(Value::String(s)) => split_caps(s),
            _ => vec![],
        };
        (text("name"), text("ip"), text("type"), caps)
    } else {
        let form = parse_form(&body);
        let get = |k: &str| form.get(k).cloned().unwrap_or_default();
        (get("name"), String::new(), get("type"), split_caps(&get("capabilities")))
    };

    if name.is_empty() {
        return respond(request, 400, "text/plain", "missing name");
    }
    let kind = if kind.is_empty() { "unknown".to_string() } else { kind };
    let ip = if ip.is_empty() {
        request.remote_addr().map(|a| a.ip().to_string()).unwrap_or_default()
    } else {
        ip
    };
    state.registry.register(&name, &ip, &kind, caps);
    respond(request, 200, "text/plain", "OK");
}

fn handle_set_mode(mut request: Request, state: &State) {
    let is_json = is_json(&request);
    let body = read_body(&mut request);
    let (mode, bt_port) = if is_json {
        let v: Value = serde_json::from_str(&body).unwrap_or(Value::Null);
        let text = |k: &str| v.get(k).and_then(Value::as_str).unwrap_or("").to_string();
        (text("mode"), text("bt_port"))
    } else {
        let form = parse_form(&body);
        (form.get("mode").cloned().unwrap_or_default(), form.get("bt_port").cloned().unwrap_or_default())
    };
    let mode = mode.trim().to_lowercase();
    let bt_port = bt_port.trim().to_string();

    if mode != "wifi" && mode != "bluetooth" {
        return respond_json(request, 400, json!({ "error": "mode must be 'wifi' or 'bluetooth'" }));
    }
    if mode == "bluetooth" && bt_port.is_empty() {
        return respond_json(request, 400, json!({ "error": "bt_port is required for Bluetooth mode" }));
    }
    state.authority.restart(&mode, &bt_port);
    respond_json(request, 200, json!({ "mode": mode, "bt_port": if bt_port.is_empty() { Value::Null } else { json!(bt_port) } }));
}

fn serve_static(request: Request, state: &State, rel: &str) {
    let rel = percent_decode(rel);
    let safe = Path::new(&rel).components().all(|c| matches!(c, Component::Normal(_)));
    if !safe || rel.is_empty() {
        return respond(request, 404, "text/plain", "Not found");
    }
    let path = state.cfg.root.join("static").join(&rel);
    match std::fs::read(&path) {
        Ok(bytes) => respond(request, 200, content_type_for(&path), bytes),
        Err(_) => respond(request, 404, "text/plain", "Not found"),
    }
}

fn handle(request: Request, state: &State) {
    let url = request.url().to_string();
    let path = url.split_once('?').map(|(p, _)| p).unwrap_or(&url).to_string();
    let method = request.method().clone();

    match (&method, path.as_str()) {
        (Method::Get, "/ping") => respond(request, 200, "text/plain", format!("{} alive", state.cfg.name)),
        (Method::Post, "/register") => handle_register(request, state),
        (Method::Get, "/robots") => {
            let robots: Vec<Value> = state
                .registry
                .robots()
                .into_iter()
                .map(|r| json!({ "name": r.name, "ip": r.ip, "type": r.kind, "capabilities": r.capabilities }))
                .collect();
            respond_json(request, 200, json!({ "authority": state.cfg.name, "robots": robots }));
        }
        (Method::Get, "/peers") => {
            let peers: Map<String, Value> = state.peers.snapshot().into_iter().map(|(k, v)| (k, json!(v))).collect();
            respond_json(request, 200, Value::Object(peers));
        }
        (Method::Get, "/mode") => {
            let (mode, bt_port) = state.authority.state();
            respond_json(request, 200, json!({ "mode": mode, "bt_port": if bt_port.is_empty() { Value::Null } else { json!(bt_port) } }));
        }
        (Method::Post, "/mode") => handle_set_mode(request, state),
        (Method::Get, "/") => match std::fs::read_to_string(state.cfg.root.join("templates").join("index.html")) {
            Ok(tpl) => {
                let html = render_template(
                    &tpl,
                    &[
                        ("this_name", state.cfg.name.clone()),
                        ("my_ip", state.cfg.ip.clone()),
                        ("this_port", state.cfg.port.to_string()),
                    ],
                );
                respond(request, 200, "text/html; charset=utf-8", html);
            }
            Err(e) => respond(request, 500, "text/plain", format!("dashboard template not found: {e}")),
        },
        (Method::Get, p) if p.starts_with("/static/") => serve_static(request, state, &p["/static/".len()..]),
        (_, "/ping" | "/register" | "/robots" | "/peers" | "/mode" | "/") => {
            let _ = request.respond(Response::from_string("Method Not Allowed").with_status_code(405));
        }
        _ => respond(request, 404, "text/plain", "Not found"),
    }
}

/// Binds the HTTP server; the returned handle's `unblock()` stops it.
pub fn start(state: Arc<State>) -> Result<Arc<Server>, String> {
    let server = Server::http(("0.0.0.0", state.cfg.port))
        .map_err(|e| format!("could not bind port {} (already in use?): {e}", state.cfg.port))?;
    let server = Arc::new(server);
    let accept = server.clone();
    std::thread::spawn(move || {
        for request in accept.incoming_requests() {
            let state = state.clone();
            std::thread::spawn(move || handle(request, &state));
        }
    });
    Ok(server)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renders_dashboard_expressions() {
        let tpl = "<p>{{ this_name }} &middot; {{ my_ip }}:{{ this_port }}</p><link href=\"{{ url_for('static', filename='css/styles.css') }}\">{{ unknown }}";
        let out = render_template(
            tpl,
            &[("this_name", "RIFT".into()), ("my_ip", "1.2.3.4".into()), ("this_port", "5000".into())],
        );
        assert_eq!(out, "<p>RIFT &middot; 1.2.3.4:5000</p><link href=\"/static/css/styles.css\">{{ unknown }}");
    }

    #[test]
    fn decodes_form_bodies() {
        let f = parse_form("name=ARM&type=robot&capabilities=servo_control%2C6dof%2Carm&x=a+b");
        assert_eq!(f["capabilities"], "servo_control,6dof,arm");
        assert_eq!(f["x"], "a b");
    }
}
