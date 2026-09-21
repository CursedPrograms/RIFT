#!/usr/bin/env julia
# RIFT fleet hub, Julia edition: the same fleet registry, dashboard, mDNS
# discovery, NORA fleet-authority heartbeat (WiFi or Bluetooth) and internet
# share as app.py. Speaks the same protocol on the same port as app.py and the
# C++ server, so run one or the other on a given machine, not both.
#
#   julia --project=. rift.jl           start the hub on :5000
#   julia --project=. rift.jl --scan    scan this /24 for hubs/robots serving /robots

include(joinpath(@__DIR__, "config.jl"))
include(joinpath(@__DIR__, "registry.jl"))
include(joinpath(@__DIR__, "authority.jl"))
include(joinpath(@__DIR__, "mdns.jl"))
include(joinpath(@__DIR__, "share.jl"))
include(joinpath(@__DIR__, "scan.jl"))
include(joinpath(@__DIR__, "server.jl"))

function main()
    cfg = try
        parse_config(ARGS)
    catch e
        println(stderr, e isa ErrorException ? e.msg : sprint(showerror, e))
        return 1
    end

    if cfg.scan
        run_scan(cfg.ip, cfg.port)
        return 0
    end

    println("[RIFT] IP   : $(cfg.ip)\n[RIFT] Port : $(cfg.port)\n[RIFT] Root : $(cfg.root)")

    peers = Peers()
    mdns = nothing
    if !cfg.no_mdns
        try
            mdns = start_mdns(cfg, peers)
            println("[RIFT] Zeroconf registered as $(cfg.name); watching $BROWSE_TYPES")
        catch e
            println("[RIFT] Continuing without mDNS: ", sprint(showerror, e))
        end
    end

    authority = Authority(cfg)
    restart!(authority, "wifi", "")
    if cfg.no_heartbeat
        println("[RIFT] Not announcing to NORA (--no-heartbeat)")
    else
        println("[RIFT] Announcing to NORA at $(cfg.nora_host):$(cfg.nora_port) as fleet authority (mode: wifi)")
    end

    stop_share = Ref(false)
    cfg.no_internet_share || start_internet_share(stop_share)

    state = State(cfg, Registry(cfg.ttl), peers, authority)
    server = try
        start_server(state)
    catch e
        println(stderr, "[RIFT] server error: ", sprint(showerror, e))
        return 1
    end

    try
        while true
            sleep(0.5)   # keep yielding so the HTTP server and heartbeat tasks run
        end
    catch e
        e isa InterruptException || rethrow()
    finally
        stop_share[] = true
        stop!(authority)
        mdns === nothing || stop_mdns!(mdns)
        close(server)
        println("[RIFT] Shut down.")
    end
    return 0
end

exit(main())
