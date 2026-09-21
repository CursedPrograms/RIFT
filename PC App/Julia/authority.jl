# authority.jl - announces this RIFT instance to a NORA hub as the fleet
# authority, over HTTP/WiFi (default) or a Bluetooth serial link. Julia
# counterpart of Fleet/register.py + Fleet/bt_link.py: while RIFT keeps
# heartbeating, NORA defers her /robots response to point at RIFT; if it
# stops, the registration simply expires on her side.
#
# Julia tasks are cooperative: everything here yields on I/O or sleep, and the
# main task must keep sleeping (it does) so these tasks - and the HTTP server -
# get to run.

import HTTP
import LibSerialPort

const AUTHORITY_CAPS = "fleet_management,monitoring"

mutable struct Authority
    cfg::Config
    lock::ReentrantLock
    mode::String
    bt_port::String
    stop::Ref{Bool}
    task::Union{Task,Nothing}
end

Authority(cfg::Config) = Authority(cfg, ReentrantLock(), "wifi", "", Ref(false), nothing)

authority_state(a::Authority) = lock(() -> (a.mode, a.bt_port), a.lock)

function announce_wifi(cfg::Config)
    try
        HTTP.post("http://$(cfg.nora_host):$(cfg.nora_port)/register",
                  ["Content-Type" => "application/x-www-form-urlencoded"],
                  "name=$(HTTP.escapeuri(cfg.name))&type=fleet_manager&capabilities=$(HTTP.escapeuri(AUTHORITY_CAPS))";
                  readtimeout=2, connect_timeout=2, retry=false, status_exception=false)
    catch
        # NORA may not be reachable yet (booting, or not on her AP) - keep retrying.
    end
end

# The fleet-registration half of NORA's Bluetooth protocol: send
# "H<name>:<cap1,cap2>\n", she replies "OK\n" or "ERR\n".
function bt_register(sp, name)::Bool
    LibSerialPort.sp_flush(sp, LibSerialPort.SP_BUF_INPUT)
    write(sp, "H$name:$AUTHORITY_CAPS\n")
    deadline = time() + 2.0
    reply = ""
    while time() < deadline
        reply *= String(LibSerialPort.nonblocking_read(sp))
        occursin('\n', reply) && return strip(first(split(reply, '\n'))) == "OK"
        sleep(0.02)
    end
    return false
end

function heartbeat_loop(cfg::Config, mode::String, bt_port::String, stop::Ref{Bool})
    sp = nothing
    try
        while !stop[]
            if mode == "bluetooth"
                try
                    sp === nothing && (sp = LibSerialPort.open(bt_port, 115200))
                    bt_register(sp, cfg.name)
                catch
                    if sp !== nothing
                        try close(sp) catch end
                        sp = nothing  # drop the link and reopen next round
                    end
                end
            else
                announce_wifi(cfg)
            end
            waited = 0.0
            while waited < cfg.heartbeat && !stop[]
                sleep(0.1)
                waited += 0.1
            end
        end
    finally
        if sp !== nothing
            try close(sp) catch end
        end
    end
end

function stop_heartbeat!(a::Authority)
    if a.task !== nothing
        a.stop[] = true
        t0 = time()
        while !istaskdone(a.task) && time() - t0 < 2.0
            sleep(0.05)
        end
        a.task = nothing
    end
end

# Retires the current heartbeat (if any) and starts one on the given transport.
function restart!(a::Authority, mode::String, bt_port::String)
    lock(a.lock) do
        stop_heartbeat!(a)
        a.mode, a.bt_port = mode, bt_port
        a.stop = Ref(false)
        a.cfg.no_heartbeat && return
        stop = a.stop
        a.task = @async heartbeat_loop(a.cfg, mode, bt_port, stop)
    end
    return nothing
end

stop!(a::Authority) = lock(() -> stop_heartbeat!(a), a.lock)
