/// Shares this RIFT instance's existing internet connection out to every
/// device that joins NORA's isolated WiFi AP. F# counterpart of
/// Fleet/internet_share.py: join NORA's AP as a secondary connection over a
/// spare WiFi radio, then let NetworkManager's "shared" method (its own DHCP
/// server + NAT) hand internet access to NORA and anything else on her AP,
/// while RIFT's own default route is left alone. Linux + NetworkManager only;
/// anywhere else it quietly does nothing.
module Rift.Share

open System
open System.Diagnostics
open System.Threading
open System.Threading.Tasks

let private noraSsid = "NORA"
let private noraPassword = "12345678"
let private interval = TimeSpan.FromSeconds 30.0

/// Runs nmcli, killing it if it hasn't finished within `timeoutMs`.
let private nmcli (timeoutMs: int) (args: string list) : string option =
    try
        let psi = ProcessStartInfo("nmcli", args)
        psi.RedirectStandardOutput <- true
        psi.RedirectStandardError <- true
        psi.UseShellExecute <- false
        use p = Process.Start psi

        if p.WaitForExit timeoutMs then
            Some(p.StandardOutput.ReadToEnd())
        else
            p.Kill()
            None
    with _ ->
        None

let private lines (s: string) =
    s.Split('\n') |> Array.map (fun l -> l.Trim()) |> Array.filter (fun l -> l <> "") |> List.ofArray

let private wifiIface () =
    nmcli 20000 [ "-t"; "-f"; "DEVICE,TYPE"; "device"; "status" ]
    |> Option.bind (fun out ->
        lines out
        |> List.tryPick (fun l ->
            match l.Split(':') with
            | [| device; "wifi" |] -> Some device
            | parts when parts.Length >= 2 && parts.[1] = "wifi" -> Some parts.[0]
            | _ -> None))

let private activeConnections () =
    nmcli 20000 [ "-t"; "-f"; "NAME"; "connection"; "show"; "--active" ]
    |> Option.map lines
    |> Option.defaultValue []

/// Joins NORA's AP (if not already) and marks it shared. Safe to call
/// repeatedly; a no-op once already connected and shared.
let private ensureInternetShare () =
    match wifiIface () with
    | None -> false
    | Some iface ->
        if List.contains noraSsid (activeConnections ()) then
            true
        else
            match nmcli 20000 [ "-t"; "-f"; "NAME"; "connection"; "show" ] with
            | None -> false
            | Some known ->
                if not (List.contains noraSsid (lines known)) then
                    nmcli 30000 [ "device"; "wifi"; "connect"; noraSsid; "password"; noraPassword; "ifname"; iface ]
                    |> ignore

                    nmcli 20000 [ "connection"; "modify"; noraSsid; "ipv4.method"; "shared" ] |> ignore
                else
                    nmcli 30000 [ "connection"; "up"; noraSsid ] |> ignore

                List.contains noraSsid (activeConnections ())

/// Keeps NORA's AP joined and shared until the token is cancelled.
let start (ct: CancellationToken) =
    if OperatingSystem.IsLinux() && (nmcli 5000 [ "--version" ]).IsSome then
        Task.Run(fun () ->
            while not ct.IsCancellationRequested do
                ensureInternetShare () |> ignore

                try
                    Task.Delay(interval, ct).Wait()
                with _ ->
                    ())
        |> ignore
