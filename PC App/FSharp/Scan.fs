/// --scan: the subnet-scanning client (F# counterpart of PC App/App/registration.cpp
/// and PC App/PyGame/registration.py). Queries every host on this machine's /24
/// for :<port>/robots and prints whatever answers.
module Rift.Scan

open System
open System.Net.Http
open System.Text.Json
open System.Threading
open System.Threading.Tasks

let private queryHost (http: HttpClient) (ip: string) (port: int) =
    task {
        try
            let! body = http.GetStringAsync(sprintf "http://%s:%d/robots" ip port)
            use doc = JsonDocument.Parse body
            // RIFT and NORA both serve {"authority": "...", "robots": [...]}, not a bare array.
            match doc.RootElement.TryGetProperty "robots" with
            | true, robots ->
                let text (r: JsonElement) (key: string) =
                    match r.TryGetProperty key with
                    | true, v when v.ValueKind = JsonValueKind.String -> v.GetString()
                    | _ -> ""

                return
                    [ for r in robots.EnumerateArray() ->
                          let caps =
                              match r.TryGetProperty "capabilities" with
                              | true, c when c.ValueKind = JsonValueKind.Array ->
                                  [ for x in c.EnumerateArray() -> x.GetString() ]
                              | _ -> []

                          sprintf "%s (%s) @ %s\n  Capabilities: %s\n" (text r "name") (text r "type") ip (String.Join(" ", caps)) ]
            | _ -> return []
        with _ ->
            return []
    }

let run (localIp: string) (port: int) =
    let dot = localIp.LastIndexOf '.'
    let baseIp = if dot > 0 then localIp.Substring(0, dot) else "192.168.1" // assumes a /24
    printfn "Scanning %s.1-254 on port %d..." baseIp port
    use http = new HttpClient(Timeout = TimeSpan.FromMilliseconds 500.0)
    use gate = new SemaphoreSlim 50

    let tasks =
        [| for i in 1..254 ->
               task {
                   do! gate.WaitAsync()

                   try
                       return! queryHost http (sprintf "%s.%d" baseIp i) port
                   finally
                       gate.Release() |> ignore
               } |]

    let results = Task.WhenAll(tasks).GetAwaiter().GetResult()
    printfn "\n=== Robots Found ==="

    for entries in results do
        for e in entries do
            printfn "%s" e
