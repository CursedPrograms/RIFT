/// HTTP fleet registry + dashboard. Same wire protocol as app.py's Flask routes
/// (and NORA's fleet server), so PC App/PyGame/registration.py,
/// PC App/App/registration.cpp and every robot's heartbeat work unchanged.
module Rift.Server

open System
open System.IO
open System.Text
open System.Text.Json
open System.Text.Json.Nodes
open System.Text.Encodings.Web
open System.Text.RegularExpressions
open System.Threading.Tasks
open Microsoft.AspNetCore.Builder
open Microsoft.AspNetCore.Hosting
open Microsoft.AspNetCore.Http
open Microsoft.Extensions.Logging
open Rift.Config
open Rift.Registry
open Rift.Authority
open Rift.Mdns

type State =
    { Cfg: Config
      Registry: Registry
      Peers: Peers
      Authority: Authority }

let private jstr (s: string) = JsonValue.Create s :> JsonNode
let private jnull () : JsonNode = null

let private templateTag = Regex(@"\{\{\s*(.*?)\s*\}\}")

let private urlForStatic =
    Regex(@"^url_for\(\s*'static'\s*,\s*filename\s*=\s*'([^']*)'\s*\)$")

/// Fills in the handful of Jinja expressions templates/index.html uses:
/// {{ this_name }}, {{ my_ip }}, {{ this_port }} and url_for('static', filename=...).
let renderTemplate (tpl: string) (vars: Map<string, string>) =
    templateTag.Replace(
        tpl,
        MatchEvaluator(fun m ->
            let expr = m.Groups.[1].Value

            match Map.tryFind expr vars with
            | Some v -> v
            | None ->
                let u = urlForStatic.Match expr
                if u.Success then "/static/" + u.Groups.[1].Value else m.Value)
    )

let private contentTypeFor (path: string) =
    match Path.GetExtension(path).ToLowerInvariant() with
    | ".css" -> "text/css; charset=utf-8"
    | ".js" -> "application/javascript; charset=utf-8"
    | ".html" -> "text/html; charset=utf-8"
    | ".json" -> "application/json"
    | ".svg" -> "image/svg+xml"
    | ".png" -> "image/png"
    | ".ico" -> "image/x-icon"
    | _ -> "application/octet-stream"

let private respond (ctx: HttpContext) (status: int) (contentType: string) (body: string) : Task =
    ctx.Response.StatusCode <- status
    ctx.Response.ContentType <- contentType
    ctx.Response.WriteAsync body

// Relaxed escaping keeps quotes like ' literal, so every RIFT implementation emits the same text.
let private jsonOptions = JsonSerializerOptions(Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping)

let private respondJson (ctx: HttpContext) (status: int) (node: JsonNode) =
    respond ctx status "application/json" (node.ToJsonString jsonOptions)

let private splitCaps (csv: string) =
    csv.Split(',') |> Array.filter (fun c -> c <> "") |> List.ofArray

let private optionalString (s: string) = if String.IsNullOrEmpty s then jnull () else jstr s

let private robotJson (r: Robot) =
    let o = JsonObject()
    o.["name"] <- jstr r.Name
    o.["ip"] <- jstr r.Ip
    o.["type"] <- jstr r.Type
    let caps = JsonArray()
    r.Capabilities |> List.iter (fun c -> caps.Add(jstr c))
    o.["capabilities"] <- caps
    o :> JsonNode

/// A registration or mode change: app.py reads a form body; the Android app's
/// Registration.kt sends JSON, so both are accepted. Returns a lookup over the fields.
let private readFields (ctx: HttpContext) =
    task {
        if not (isNull ctx.Request.ContentType) && ctx.Request.ContentType.StartsWith "application/json" then
            use reader = new StreamReader(ctx.Request.Body)
            let! body = reader.ReadToEndAsync()

            try
                let doc = JsonDocument.Parse body
                return Some(doc.RootElement.Clone())
            with _ ->
                return None
        else
            let! form = ctx.Request.ReadFormAsync()
            let o = JsonObject()

            for kv in form do
                o.[kv.Key] <- jstr (kv.Value.ToString())

            return Some(JsonDocument.Parse(o.ToJsonString()).RootElement.Clone())
    }

let private field (root: JsonElement option) (key: string) =
    match root with
    | Some r when r.ValueKind = JsonValueKind.Object ->
        match r.TryGetProperty key with
        | true, v when v.ValueKind = JsonValueKind.String -> v.GetString()
        | _ -> ""
    | _ -> ""

let private handleRegister (st: State) (ctx: HttpContext) : Task =
    task {
        let! fields = readFields ctx
        let name = field fields "name"

        if name = "" then
            do! respond ctx 400 "text/plain" "missing name"
        else
            let kind =
                match field fields "type" with
                | "" -> "unknown"
                | t -> t

            let caps =
                match fields with
                | Some r when r.ValueKind = JsonValueKind.Object ->
                    match r.TryGetProperty "capabilities" with
                    | true, c when c.ValueKind = JsonValueKind.Array -> [ for x in c.EnumerateArray() -> x.GetString() ]
                    | true, c when c.ValueKind = JsonValueKind.String -> splitCaps (c.GetString())
                    | _ -> []
                | _ -> []

            let ip =
                match field fields "ip" with
                | "" -> string ctx.Connection.RemoteIpAddress
                | given -> given

            st.Registry.Register(name, ip, kind, caps)
            do! respond ctx 200 "text/plain" "OK"
    }
    :> Task

let private handleSetMode (st: State) (ctx: HttpContext) : Task =
    task {
        let! fields = readFields ctx
        let mode = (field fields "mode").Trim().ToLowerInvariant()
        let btPort = (field fields "bt_port").Trim()

        if mode <> "wifi" && mode <> "bluetooth" then
            let o = JsonObject()
            o.["error"] <- jstr "mode must be 'wifi' or 'bluetooth'"
            do! respondJson ctx 400 o
        elif mode = "bluetooth" && btPort = "" then
            let o = JsonObject()
            o.["error"] <- jstr "bt_port is required for Bluetooth mode"
            do! respondJson ctx 400 o
        else
            st.Authority.Restart(mode, btPort)
            let o = JsonObject()
            o.["mode"] <- jstr mode
            o.["bt_port"] <- optionalString btPort
            do! respondJson ctx 200 o
    }
    :> Task

let private serveStatic (st: State) (ctx: HttpContext) (rel: string) : Task =
    let staticDir = Path.GetFullPath(Path.Combine(st.Cfg.Root, "static"))
    let full = Path.GetFullPath(Path.Combine(staticDir, rel))

    if rel <> "" && full.StartsWith(staticDir + string Path.DirectorySeparatorChar) && File.Exists full then
        task {
            ctx.Response.StatusCode <- 200
            ctx.Response.ContentType <- contentTypeFor full
            do! ctx.Response.SendFileAsync full
        }
        :> Task
    else
        respond ctx 404 "text/plain" "Not found"

let handle (st: State) (ctx: HttpContext) : Task =
    let path = ctx.Request.Path.Value
    let meth = ctx.Request.Method

    match meth, path with
    | "GET", "/ping" -> respond ctx 200 "text/plain" (st.Cfg.Name + " alive")
    | "POST", "/register" -> handleRegister st ctx
    | "GET", "/robots" ->
        let o = JsonObject()
        o.["authority"] <- jstr st.Cfg.Name
        let robots = JsonArray()
        st.Registry.Robots() |> List.iter (fun r -> robots.Add(robotJson r))
        o.["robots"] <- robots
        respondJson ctx 200 o
    | "GET", "/peers" ->
        let o = JsonObject()
        st.Peers.Snapshot() |> List.iter (fun (k, v) -> o.[k] <- jstr v)
        respondJson ctx 200 o
    | "GET", "/mode" ->
        let mode, btPort = st.Authority.State
        let o = JsonObject()
        o.["mode"] <- jstr mode
        o.["bt_port"] <- optionalString btPort
        respondJson ctx 200 o
    | "POST", "/mode" -> handleSetMode st ctx
    | "GET", "/" ->
        let file = Path.Combine(st.Cfg.Root, "templates", "index.html")

        if File.Exists file then
            let html =
                renderTemplate
                    (File.ReadAllText file)
                    (Map [ "this_name", st.Cfg.Name; "my_ip", st.Cfg.Ip; "this_port", string st.Cfg.Port ])

            respond ctx 200 "text/html; charset=utf-8" html
        else
            respond ctx 500 "text/plain" "dashboard template not found"
    | "GET", p when p.StartsWith "/static/" -> serveStatic st ctx (p.Substring "/static/".Length)
    | _, ("/ping" | "/register" | "/robots" | "/peers" | "/mode" | "/") -> respond ctx 405 "text/plain" "Method Not Allowed"
    | _ -> respond ctx 404 "text/plain" "Not found"

/// Starts Kestrel on 0.0.0.0:<port> (no admin rights needed); dispose/StopAsync to shut down.
let start (st: State) : WebApplication =
    let builder = WebApplication.CreateBuilder()
    builder.Logging.ClearProviders() |> ignore
    builder.WebHost.UseUrls(sprintf "http://0.0.0.0:%d" st.Cfg.Port) |> ignore
    let app = builder.Build()
    RunExtensions.Run(app, RequestDelegate(fun ctx -> handle st ctx))
    app.StartAsync().GetAwaiter().GetResult()
    app
