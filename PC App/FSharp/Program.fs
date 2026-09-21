/// RIFT fleet hub, F# edition: the same fleet registry, dashboard, mDNS
/// discovery, NORA fleet-authority heartbeat (WiFi or Bluetooth) and internet
/// share as app.py, on .NET. Speaks the same protocol on the same port as
/// app.py and the C++ server, so run one or the other on a given machine, not
/// both.
///
///   rift-fsharp           start the hub on :5000
///   rift-fsharp --scan    scan this /24 for hubs/robots serving /robots
module Rift.Program

open System
open System.Threading
open Rift.Config

let private run (cfg: Config) =
    printfn "[RIFT] IP   : %s\n[RIFT] Port : %d\n[RIFT] Root : %s" cfg.Ip cfg.Port cfg.Root

    let peers = Mdns.Peers()

    let mdns =
        if cfg.NoMdns then
            None
        else
            try
                let h = Mdns.start cfg peers
                printfn "[RIFT] Zeroconf registered as %s; watching %A" cfg.Name Mdns.browseTypes
                Some h
            with e ->
                printfn "[RIFT] Continuing without mDNS: %s" e.Message
                None

    let authority = Authority.Authority cfg
    authority.Restart("wifi", "")

    if cfg.NoHeartbeat then
        printfn "[RIFT] Not announcing to NORA (--no-heartbeat)"
    else
        printfn "[RIFT] Announcing to NORA at %s:%d as fleet authority (mode: wifi)" cfg.NoraHost cfg.NoraPort

    use cts = new CancellationTokenSource()

    if not cfg.NoInternetShare then
        Share.start cts.Token

    let state: Server.State =
        { Cfg = cfg
          Registry = Registry.Registry cfg.Ttl
          Peers = peers
          Authority = authority }

    try
        let app = Server.start state
        use quit = new ManualResetEventSlim(false)

        Console.CancelKeyPress.Add(fun e ->
            e.Cancel <- true
            quit.Set())

        AppDomain.CurrentDomain.ProcessExit.Add(fun _ -> quit.Set())
        quit.Wait()

        cts.Cancel()
        authority.Stop()
        mdns |> Option.iter (fun h -> h.Stop())
        app.StopAsync().GetAwaiter().GetResult()
        printfn "[RIFT] Shut down."
        0
    with e ->
        eprintfn "[RIFT] server error: %s" e.Message
        1

[<EntryPoint>]
let main argv =
    match Config.parse argv with
    | Error msg ->
        eprintfn "%s" msg
        1
    | Ok cfg when cfg.Scan ->
        Scan.run cfg.Ip cfg.Port
        0
    | Ok cfg -> run cfg
