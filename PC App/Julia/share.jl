# share.jl - shares this RIFT instance's existing internet connection out to
# every device that joins NORA's isolated WiFi AP. Julia counterpart of
# Fleet/internet_share.py: join NORA's AP as a secondary connection over a
# spare WiFi radio, then let NetworkManager's "shared" method (its own DHCP
# server + NAT) hand internet access to NORA and anything else on her AP, while
# RIFT's own default route is left alone. Linux + NetworkManager only;
# anywhere else it quietly does nothing.

const NORA_SSID = "NORA"
const NORA_PASSWORD = "12345678"
const SHARE_INTERVAL = 30.0

# Runs nmcli, killing it if it hasn't finished within `timeout` seconds.
function nmcli(timeout::Real, args::String...)::Union{String,Nothing}
    try
        out = IOBuffer()
        proc = run(pipeline(`nmcli $(collect(args))`; stdout=out, stderr=devnull); wait=false)
        t0 = time()
        while process_running(proc)
            if time() - t0 > timeout
                kill(proc)
                return nothing
            end
            sleep(0.05)
        end
        return String(take!(out))
    catch
        return nothing
    end
end

nonempty_lines(s) = [strip(l) for l in split(s, '\n') if !isempty(strip(l))]

function wifi_iface()
    out = nmcli(20, "-t", "-f", "DEVICE,TYPE", "device", "status")
    out === nothing && return nothing
    for l in nonempty_lines(out)
        parts = split(l, ':')
        length(parts) >= 2 && parts[2] == "wifi" && return String(parts[1])
    end
    return nothing
end

function active_connections()
    out = nmcli(20, "-t", "-f", "NAME", "connection", "show", "--active")
    return out === nothing ? String[] : String.(nonempty_lines(out))
end

# Joins NORA's AP (if not already) and marks it shared. Safe to call
# repeatedly; a no-op once already connected and shared.
function ensure_internet_share()
    iface = wifi_iface()
    iface === nothing && return false
    NORA_SSID in active_connections() && return true
    known = nmcli(20, "-t", "-f", "NAME", "connection", "show")
    known === nothing && return false
    if !(NORA_SSID in nonempty_lines(known))
        nmcli(30, "device", "wifi", "connect", NORA_SSID, "password", NORA_PASSWORD, "ifname", iface)
        nmcli(20, "connection", "modify", NORA_SSID, "ipv4.method", "shared")
    else
        nmcli(30, "connection", "up", NORA_SSID)
    end
    return NORA_SSID in active_connections()
end

# Keeps NORA's AP joined and shared until `stop[]` is set.
function start_internet_share(stop::Ref{Bool})
    (Sys.islinux() && nmcli(5, "--version") !== nothing) || return nothing
    return @async begin
        while !stop[]
            ensure_internet_share()
            waited = 0.0
            while waited < SHARE_INTERVAL && !stop[]
                sleep(0.2)
                waited += 0.2
            end
        end
    end
end
