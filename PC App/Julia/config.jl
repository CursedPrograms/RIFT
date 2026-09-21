# config.jl - command-line configuration and repo-root discovery.

import Sockets

struct Config
    name::String
    port::Int
    ip::String
    root::String
    ttl::Float64
    nora_host::String
    nora_port::Int
    heartbeat::Float64
    no_heartbeat::Bool
    no_mdns::Bool
    no_internet_share::Bool
    scan::Bool
end

# Same trick as app.py's _get_ip(): "connect" a UDP socket (no traffic is sent)
# and read back which local address the OS would use.
function local_ip()
    try
        sock = Sockets.UDPSocket()
        try
            Sockets.connect(sock, Sockets.ip"10.255.255.255", 1)
            return string(Sockets.getsockname(sock)[1])
        finally
            close(sock)
        end
    catch
        try
            return string(Sockets.getipaddr())
        catch
            return "127.0.0.1"
        end
    end
end

# Walks up from this file / the working directory until it finds the RIFT repo
# root (app.py next to templates/), so it works from PC App/Julia, from the repo
# root, or from anywhere below it.
function find_root()
    is_root(d) = isfile(joinpath(d, "app.py")) && isfile(joinpath(d, "templates", "index.html"))
    for start in (@__DIR__, pwd())
        dir = abspath(start)
        while true
            is_root(dir) && return dir
            parent = dirname(dir)
            parent == dir && break
            dir = parent
        end
    end
    return pwd()
end

const USAGE = """
usage: julia rift.jl [--name RIFT] [--port 5000] [--nora-host 192.168.4.1] [--nora-port 5000]
                     [--heartbeat-secs 10] [--ttl-secs 20] [--no-heartbeat] [--no-mdns]
                     [--no-internet-share] [--root <repo>] [--scan]"""

function parse_config(argv::Vector{String})
    opts = Dict{String,Any}(
        "name" => "RIFT", "port" => 5000, "nora-host" => "192.168.4.1", "nora-port" => 5000,
        "heartbeat-secs" => 10.0, "ttl-secs" => 20.0, "root" => "",
        "no-heartbeat" => false, "no-mdns" => false, "no-internet-share" => false, "scan" => false,
    )
    bool_flags = ("no-heartbeat", "no-mdns", "no-internet-share", "scan")
    int_flags = ("port", "nora-port")
    float_flags = ("heartbeat-secs", "ttl-secs")
    i = 1
    while i <= length(argv)
        flag = lstrip(argv[i], '-')
        if flag in ("help", "h")
            error(USAGE)
        elseif flag in bool_flags
            opts[flag] = true
        elseif haskey(opts, flag)
            i == length(argv) && error("--$flag requires a value")
            i += 1
            val = argv[i]
            if flag in int_flags
                n = tryparse(Int, val)
                n === nothing && error("--$flag requires a number")
                opts[flag] = n
            elseif flag in float_flags
                x = tryparse(Float64, val)
                x === nothing && error("--$flag requires a number")
                opts[flag] = x
            else
                opts[flag] = val
            end
        else
            error("unknown argument: $(argv[i])\n$USAGE")
        end
        i += 1
    end
    root = isempty(opts["root"]) ? find_root() : opts["root"]
    return Config(opts["name"], opts["port"], local_ip(), root, opts["ttl-secs"], opts["nora-host"], opts["nora-port"],
                  opts["heartbeat-secs"], opts["no-heartbeat"], opts["no-mdns"], opts["no-internet-share"], opts["scan"])
end
