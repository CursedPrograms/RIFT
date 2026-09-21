/// Announces this RIFT instance to a NORA hub as the fleet authority, over
/// HTTP/WiFi (default) or a Bluetooth serial link. F# counterpart of
/// Fleet/register.py + Fleet/bt_link.py: while RIFT keeps heartbeating, NORA
/// defers her /robots response to point at RIFT; if it stops, the
/// registration simply expires on her side.
module Rift.Authority

open System
open System.Collections.Generic
open System.IO.Ports
open System.Net.Http
open System.Threading
open System.Threading.Tasks
open Rift.Config

let private capabilities = "fleet_management,monitoring"

/// The fleet-registration half of NORA's Bluetooth protocol: send
/// "H<name>:<cap1,cap2>\n", she replies "OK\n" or "ERR\n".
type private BtLink(portName: string) =
    let port = new SerialPort(portName, 115200, ReadTimeout = 2000, WriteTimeout = 2000)
    do port.Open()

    member _.Register(name: string) =
        port.DiscardInBuffer()
        port.Write(sprintf "H%s:%s\n" name capabilities)
        port.ReadLine().Trim() = "OK"

    member _.Close() =
        try
            port.Close()
        with _ ->
            ()

type Authority(cfg: Config) =
    let gate = obj ()
    let mutable mode = "wifi"
    let mutable btPort = ""
    let mutable running: (CancellationTokenSource * Task) option = None
    let http = new HttpClient(Timeout = TimeSpan.FromSeconds 2.0)

    let announceWifi () =
        task {
            try
                use form =
                    new FormUrlEncodedContent(
                        [ KeyValuePair("name", cfg.Name)
                          KeyValuePair("type", "fleet_manager")
                          KeyValuePair("capabilities", capabilities) ]
                    )

                use! response = http.PostAsync(sprintf "http://%s:%d/register" cfg.NoraHost cfg.NoraPort, form)
                response |> ignore
            with _ ->
                () // NORA may not be reachable yet (booting, or not on her AP) - keep retrying
        }

    let loop (mode: string) (btPort: string) (ct: CancellationToken) =
        task {
            let mutable bt: BtLink option = None

            while not ct.IsCancellationRequested do
                if mode = "bluetooth" then
                    try
                        let link =
                            match bt with
                            | Some l -> l
                            | None -> BtLink btPort

                        bt <- Some link
                        link.Register cfg.Name |> ignore
                    with _ ->
                        bt |> Option.iter (fun l -> l.Close())
                        bt <- None // drop the link and reopen next round
                else
                    do! announceWifi ()

                try
                    do! Task.Delay(cfg.HeartbeatEvery, ct)
                with :? OperationCanceledException ->
                    ()

            bt |> Option.iter (fun l -> l.Close())
        }
        :> Task

    member _.State = lock gate (fun () -> mode, btPort)

    /// Retires the current heartbeat (if any) and starts one on the given transport.
    member this.Restart(newMode: string, newBtPort: string) =
        lock gate (fun () ->
            running
            |> Option.iter (fun (cts, t) ->
                cts.Cancel()
                t.Wait(TimeSpan.FromSeconds 2.0) |> ignore)

            mode <- newMode
            btPort <- newBtPort

            running <-
                if cfg.NoHeartbeat then
                    None
                else
                    let cts = new CancellationTokenSource()
                    Some(cts, Task.Run(fun () -> loop newMode newBtPort cts.Token)))

    member _.Stop() =
        lock gate (fun () ->
            running
            |> Option.iter (fun (cts, t) ->
                cts.Cancel()
                t.Wait(TimeSpan.FromSeconds 2.0) |> ignore)

            running <- None)
