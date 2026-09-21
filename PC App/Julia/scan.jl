# scan.jl - --scan: the subnet-scanning client (Julia counterpart of
# PC App/App/registration.cpp and PC App/PyGame/registration.py). Queries every
# host on this machine's /24 for :<port>/robots and prints whatever answers.

import HTTP
import JSON3

function scan_host(ip::String, port::Int)
    try
        resp = HTTP.get("http://$ip:$port/robots"; readtimeout=1, connect_timeout=1, retry=false, status_exception=false)
        resp.status == 200 || return nothing
        # RIFT and NORA both serve {"authority": "...", "robots": [...]}, not a bare array.
        return JSON3.read(String(resp.body))
    catch
        return nothing
    end
end

function run_scan(local_ip::String, port::Int)
    base = join(split(local_ip, '.')[1:3], '.')    # assumes a /24
    println("Scanning $base.1-254 on port $port...")
    results = Vector{Any}(nothing, 254)
    sem = Base.Semaphore(50)
    @sync for i in 1:254
        @async begin
            Base.acquire(sem)
            try
                results[i] = scan_host("$base.$i", port)
            finally
                Base.release(sem)
            end
        end
    end
    println("\n=== Robots Found ===")
    for (i, body) in enumerate(results)
        (body === nothing || !haskey(body, :robots)) && continue
        for r in body.robots
            println("$(r.name) ($(r.type)) @ $base.$i\n  Capabilities: $(join(r.capabilities, " "))\n")
        end
    end
end
