# server.jl - HTTP fleet registry + dashboard. Same wire protocol as app.py's
# Flask routes (and NORA's fleet server), so PC App/PyGame/registration.py,
# PC App/App/registration.cpp and every robot's heartbeat work unchanged.
#
# Uses HTTP.jl's stream-style handler because that's the only form that exposes
# the caller's address (a robot's /register records the IP it came from).

import HTTP
import JSON3
import Sockets

struct State
    cfg::Config
    registry::Registry
    peers::Peers
    authority::Authority
end

# ---- JSON output (built by hand so key order matches every other RIFT implementation) ----

function jstr(s::AbstractString)
    io = IOBuffer()
    write(io, '"')
    for c in s
        if c == '"'
            write(io, "\\\"")
        elseif c == '\\'
            write(io, "\\\\")
        elseif c == '\n'
            write(io, "\\n")
        elseif c == '\r'
            write(io, "\\r")
        elseif c == '\t'
            write(io, "\\t")
        elseif c < ' '
            write(io, "\\u", lpad(string(Int(c); base=16), 4, '0'))
        else
            write(io, c)
        end
    end
    write(io, '"')
    return String(take!(io))
end

jobj(pairs...) = "{" * join([jstr(k) * ":" * v for (k, v) in pairs], ",") * "}"
jarr(items) = "[" * join(items, ",") * "]"
jnull_or_str(s) = isempty(s) ? "null" : jstr(s)

robot_json(r::Robot) = jobj("name" => jstr(r.name), "ip" => jstr(r.ip), "type" => jstr(r.type),
                            "capabilities" => jarr(jstr.(r.capabilities)))

# ---- dashboard template: the handful of Jinja expressions templates/index.html uses ----

function render_template(tpl::String, vars::Dict{String,String})
    return replace(tpl, r"\{\{\s*(.*?)\s*\}\}" => function (tag)
        expr = match(r"\{\{\s*(.*?)\s*\}\}", tag).captures[1]
        haskey(vars, expr) && return vars[expr]
        m = match(r"^url_for\(\s*'static'\s*,\s*filename\s*=\s*'([^']*)'\s*\)$", expr)
        m !== nothing && return "/static/" * m.captures[1]
        return tag
    end)
end

function content_type_for(path)
    ext = lowercase(splitext(path)[2])
    ext == ".css" && return "text/css; charset=utf-8"
    ext == ".js" && return "application/javascript; charset=utf-8"
    ext == ".html" && return "text/html; charset=utf-8"
    ext == ".json" && return "application/json"
    ext == ".svg" && return "image/svg+xml"
    ext == ".png" && return "image/png"
    ext == ".ico" && return "image/x-icon"
    return "application/octet-stream"
end

# ---- request plumbing ----

function respond(http::HTTP.Stream, status::Int, content_type::String, body::Union{String,Vector{UInt8}})
    data = body isa String ? Vector{UInt8}(codeunits(body)) : body
    HTTP.setstatus(http, status)
    HTTP.setheader(http, "Content-Type" => content_type)
    HTTP.setheader(http, "Content-Length" => string(length(data)))
    HTTP.startwrite(http)
    write(http, data)
    return nothing
end

respond_json(http, status, body::String) = respond(http, status, "application/json", body)

# app.py reads a form body; the Android app's Registration.kt sends JSON, so both are accepted.
function read_fields(http::HTTP.Stream, body::String)
    ctype = HTTP.header(http.message, "Content-Type", "")
    if startswith(ctype, "application/json")
        try
            parsed = JSON3.read(body)
            return Dict{String,Any}(String(k) => v for (k, v) in pairs(parsed))
        catch
            return Dict{String,Any}()
        end
    end
    return Dict{String,Any}(k => v for (k, v) in HTTP.queryparams(body))
end

field(fields, key) = (v = get(fields, key, ""); v isa AbstractString ? String(v) : "")

split_caps(csv) = String[c for c in split(csv, ',') if !isempty(c)]

function handle_register(st::State, http::HTTP.Stream, body::String)
    fields = read_fields(http, body)
    name = field(fields, "name")
    if isempty(name)
        return respond(http, 400, "text/plain", "missing name")
    end
    kind = field(fields, "type")
    isempty(kind) && (kind = "unknown")
    caps = get(fields, "capabilities", "")
    caps = caps isa AbstractString ? split_caps(caps) : String[string(c) for c in caps]
    ip = field(fields, "ip")
    if isempty(ip)
        ip = try
            string(Sockets.getpeername(http)[1])
        catch
            ""
        end
    end
    register!(st.registry, name, ip, kind, caps)
    return respond(http, 200, "text/plain", "OK")
end

function handle_set_mode(st::State, http::HTTP.Stream, body::String)
    fields = read_fields(http, body)
    mode = lowercase(strip(field(fields, "mode")))
    bt_port = strip(field(fields, "bt_port"))
    if mode != "wifi" && mode != "bluetooth"
        return respond_json(http, 400, jobj("error" => jstr("mode must be 'wifi' or 'bluetooth'")))
    elseif mode == "bluetooth" && isempty(bt_port)
        return respond_json(http, 400, jobj("error" => jstr("bt_port is required for Bluetooth mode")))
    end
    restart!(st.authority, String(mode), String(bt_port))
    return respond_json(http, 200, jobj("mode" => jstr(mode), "bt_port" => jnull_or_str(bt_port)))
end

function serve_static(st::State, http::HTTP.Stream, rel::String)
    static_dir = normpath(joinpath(st.cfg.root, "static"))
    full = normpath(joinpath(static_dir, rel))
    if !isempty(rel) && startswith(full, static_dir * Base.Filesystem.path_separator) && isfile(full)
        return respond(http, 200, content_type_for(full), read(full))
    end
    return respond(http, 404, "text/plain", "Not found")
end

function handle(st::State, http::HTTP.Stream)
    req = http.message
    method = String(req.method)
    path = HTTP.URI(req.target).path
    body = String(read(http))

    if method == "GET" && path == "/ping"
        respond(http, 200, "text/plain", st.cfg.name * " alive")
    elseif method == "POST" && path == "/register"
        handle_register(st, http, body)
    elseif method == "GET" && path == "/robots"
        respond_json(http, 200, jobj("authority" => jstr(st.cfg.name),
                                     "robots" => jarr(robot_json.(robots!(st.registry)))))
    elseif method == "GET" && path == "/peers"
        respond_json(http, 200, jobj([k => jstr(v) for (k, v) in peers_snapshot(st.peers)]...))
    elseif method == "GET" && path == "/mode"
        mode, bt_port = authority_state(st.authority)
        respond_json(http, 200, jobj("mode" => jstr(mode), "bt_port" => jnull_or_str(bt_port)))
    elseif method == "POST" && path == "/mode"
        handle_set_mode(st, http, body)
    elseif method == "GET" && path == "/"
        file = joinpath(st.cfg.root, "templates", "index.html")
        if isfile(file)
            html = render_template(read(file, String),
                Dict("this_name" => st.cfg.name, "my_ip" => st.cfg.ip, "this_port" => string(st.cfg.port)))
            respond(http, 200, "text/html; charset=utf-8", html)
        else
            respond(http, 500, "text/plain", "dashboard template not found")
        end
    elseif method == "GET" && startswith(path, "/static/")
        serve_static(st, http, String(path[length("/static/") + 1:end]))
    elseif path in ("/ping", "/register", "/robots", "/peers", "/mode", "/")
        respond(http, 405, "text/plain", "Method Not Allowed")
    else
        respond(http, 404, "text/plain", "Not found")
    end
end

# Starts the HTTP server (non-blocking); close() the result to stop it.
function start_server(st::State)
    return HTTP.serve!(http -> handle(st, http), "0.0.0.0", st.cfg.port; stream=true, verbose=-1)
end
