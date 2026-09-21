/// Command-line configuration and repo-root discovery.
module Rift.Config

open System
open System.IO
open System.Net
open System.Net.Sockets

type Config =
    { Name: string
      Port: int
      Ip: string
      Root: string
      Ttl: TimeSpan
      NoraHost: string
      NoraPort: int
      HeartbeatEvery: TimeSpan
      NoHeartbeat: bool
      NoMdns: bool
      NoInternetShare: bool
      Scan: bool }

/// Same trick as app.py's _get_ip(): "connect" a UDP socket (no traffic is sent)
/// and read back which local address the OS would use.
let localIp () =
    let probe (target: string) =
        try
            use s = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp)
            s.Connect(target, 1)
            Some((s.LocalEndPoint :?> IPEndPoint).Address.ToString())
        with _ ->
            None

    match probe "10.255.255.255" with
    | Some ip -> ip
    | None -> probe "8.8.8.8" |> Option.defaultValue "127.0.0.1"

/// Walks up from the executable / working directory until it finds the RIFT
/// repo root (app.py next to templates/), so it works from PC App/FSharp, from
/// the repo root, or from a built binary anywhere below it.
let findRoot () =
    let isRoot (d: string) =
        File.Exists(Path.Combine(d, "app.py")) && File.Exists(Path.Combine(d, "templates", "index.html"))

    let rec up (d: DirectoryInfo) =
        if isNull d then None
        elif isRoot d.FullName then Some d.FullName
        else up d.Parent

    [ AppContext.BaseDirectory; Directory.GetCurrentDirectory() ]
    |> List.tryPick (fun start -> up (DirectoryInfo start))
    |> Option.defaultValue (Directory.GetCurrentDirectory())

let usage =
    "usage: rift-fsharp [--name RIFT] [--port 5000] [--nora-host 192.168.4.1] [--nora-port 5000]\n\
     \                    [--heartbeat-secs 10] [--ttl-secs 20] [--no-heartbeat] [--no-mdns]\n\
     \                    [--no-internet-share] [--root <repo>] [--scan]"

let parse (argv: string[]) : Result<Config, string> =
    let seconds (flag: string) (text: string) =
        match Double.TryParse(text, Globalization.NumberStyles.Float, Globalization.CultureInfo.InvariantCulture) with
        | true, v -> Ok(TimeSpan.FromSeconds v)
        | _ -> Error(sprintf "--%s requires a number" flag)

    let integer (flag: string) (text: string) =
        match Int32.TryParse text with
        | true, v -> Ok v
        | _ -> Error(sprintf "--%s requires a number" flag)

    let rec go (cfg: Config) (root: string option) (args: string list) =
        match args with
        | [] -> Ok { cfg with Root = defaultArg root (findRoot ()) }
        | arg :: rest ->
            let flag = arg.TrimStart('-')

            let withValue (apply: string -> Result<Config, string>) =
                match rest with
                | v :: tail -> apply v |> Result.bind (fun c -> go c root tail)
                | [] -> Error(sprintf "--%s requires a value" flag)

            match flag with
            | "scan" -> go { cfg with Scan = true } root rest
            | "no-mdns" -> go { cfg with NoMdns = true } root rest
            | "no-heartbeat" -> go { cfg with NoHeartbeat = true } root rest
            | "no-internet-share" -> go { cfg with NoInternetShare = true } root rest
            | "name" -> withValue (fun v -> Ok { cfg with Name = v })
            | "nora-host" -> withValue (fun v -> Ok { cfg with NoraHost = v })
            | "port" -> withValue (fun v -> integer flag v |> Result.map (fun n -> { cfg with Port = n }))
            | "nora-port" -> withValue (fun v -> integer flag v |> Result.map (fun n -> { cfg with NoraPort = n }))
            | "heartbeat-secs" -> withValue (fun v -> seconds flag v |> Result.map (fun t -> { cfg with HeartbeatEvery = t }))
            | "ttl-secs" -> withValue (fun v -> seconds flag v |> Result.map (fun t -> { cfg with Ttl = t }))
            | "root" ->
                match rest with
                | v :: tail -> go cfg (Some v) tail
                | [] -> Error "--root requires a value"
            | "help"
            | "h" -> Error usage
            | _ -> Error(sprintf "unknown argument: %s\n%s" arg usage)

    go
        { Name = "RIFT"
          Port = 5000
          Ip = localIp ()
          Root = ""
          Ttl = TimeSpan.FromSeconds 20.0
          NoraHost = "192.168.4.1"
          NoraPort = 5000
          HeartbeatEvery = TimeSpan.FromSeconds 10.0
          NoHeartbeat = false
          NoMdns = false
          NoInternetShare = false
          Scan = false }
        None
        (List.ofArray argv)
