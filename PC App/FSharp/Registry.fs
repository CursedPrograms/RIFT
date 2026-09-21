/// Fleet registry: robots/managers that have called POST /register, expiring
/// after the TTL unless they keep heartbeating. F# counterpart of app.py's
/// _fleet dict + _prune_fleet().
module Rift.Registry

open System
open System.Collections.Generic

type Robot =
    { Name: string
      Ip: string
      Type: string
      Capabilities: string list }

type Registry(ttl: TimeSpan) =
    let gate = obj ()
    let members = Dictionary<string, Robot * DateTime>()
    let order = List<string>() // insertion order, like a Python dict

    member _.Register(name: string, ip: string, kind: string, caps: string list, ?now: DateTime) =
        let now = defaultArg now DateTime.UtcNow

        lock gate (fun () ->
            if not (members.ContainsKey name) then order.Add name

            members.[name] <-
                ({ Name = name
                   Ip = ip
                   Type = kind
                   Capabilities = caps },
                 now))

    /// The live roster, dropping anything not heard from within the TTL.
    member _.Robots(?now: DateTime) : Robot list =
        let now = defaultArg now DateTime.UtcNow

        lock gate (fun () ->
            let stale = order |> Seq.filter (fun n -> now - snd members.[n] > ttl) |> List.ofSeq

            for n in stale do
                members.Remove n |> ignore
                order.Remove n |> ignore

            order |> Seq.map (fun n -> fst members.[n]) |> List.ofSeq)
