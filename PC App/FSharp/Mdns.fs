/// Zeroconf: publish this instance as _rift._tcp and watch for other RIFT
/// instances and ComCentre (_flask-link._tcp). F# counterpart of app.py's
/// _start_zeroconf() / _PeerListener - browsing both is what lets DREAM show
/// up in this dashboard without ComCentre knowing anything about RIFT.
module Rift.Mdns

open System
open System.Collections.Concurrent
open System.Net
open System.Net.Sockets
open Makaretu.Dns
open Rift.Config

let browseTypes = [ "_rift._tcp"; "_flask-link._tcp" ]

/// name -> "http://ip:port" for every peer seen over mDNS.
type Peers() =
    let items = ConcurrentDictionary<string, string>()
    member _.Set(name: string, url: string) = items.[name] <- url
    member _.Remove(name: string) = items.TryRemove name |> ignore

    member _.Snapshot() =
        items |> Seq.map (fun kv -> kv.Key, kv.Value) |> List.ofSeq |> List.sortBy fst

type Handle(mdns: MulticastService, discovery: ServiceDiscovery) =
    member _.Stop() =
        try
            discovery.Dispose()
            mdns.Stop()
        with _ ->
            ()

/// Publishes the service and starts browsing. Call Stop() on the result to unregister.
let start (cfg: Config) (peers: Peers) : Handle =
    let mdns = new MulticastService()
    let sd = new ServiceDiscovery(mdns)

    let profile = ServiceProfile(cfg.Name, "_rift._tcp", uint16 cfg.Port, [ IPAddress.Parse cfg.Ip ])
    profile.AddProperty("role", "fleet_manager")
    sd.Advertise profile

    // An mDNS browse is a chain: PTR (instance names) -> SRV (host + port) -> A (address).
    let srv = ConcurrentDictionary<string, string * int>() // instance -> (target host, port)
    let addrs = ConcurrentDictionary<string, IPAddress>() // host name -> IPv4

    let publish () =
        for kv in srv do
            let target, port = kv.Value

            match addrs.TryGetValue target with
            | true, ip when kv.Key <> cfg.Name -> peers.Set(kv.Key, sprintf "http://%O:%d" ip port)
            | _ -> ()

    let isBrowsed (name: DomainName) =
        let text = name.ToString()
        browseTypes |> List.exists (fun t -> text.Contains(t))

    sd.ServiceInstanceDiscovered.Add(fun e ->
        if isBrowsed e.ServiceInstanceName then
            mdns.SendQuery(e.ServiceInstanceName, DnsClass.IN, DnsType.SRV))

    sd.ServiceInstanceShutdown.Add(fun e -> peers.Remove(e.ServiceInstanceName.Labels.[0]))

    mdns.AnswerReceived.Add(fun e ->
        for record in Seq.append e.Message.Answers e.Message.AdditionalRecords do
            match record with
            | :? SRVRecord as s when isBrowsed s.Name ->
                let instance = s.Name.Labels.[0]
                srv.[instance] <- (s.Target.ToString(), int s.Port)
                mdns.SendQuery(s.Target, DnsClass.IN, DnsType.A)
            | :? AddressRecord as a when a.Address.AddressFamily = AddressFamily.InterNetwork ->
                addrs.[a.Name.ToString()] <- a.Address
            | _ -> ()

        publish ())

    mdns.NetworkInterfaceDiscovered.Add(fun _ ->
        for t in browseTypes do
            sd.QueryServiceInstances t)

    mdns.Start()
    Handle(mdns, sd)
