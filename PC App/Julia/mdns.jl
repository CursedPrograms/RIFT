# mdns.jl - Zeroconf: publish this instance as _rift._tcp and watch for other
# RIFT instances and ComCentre (_flask-link._tcp). Julia counterpart of app.py's
# _start_zeroconf() / _PeerListener - browsing both is what lets DREAM show up in
# this dashboard without ComCentre knowing anything about RIFT.
#
# Julia has no mDNS package, so this is a small responder + browser over
# multicast UDP (224.0.0.251:5353) using just the DNS wire format: PTR (service ->
# instance), SRV (instance -> host + port), TXT and A (host -> address).

import Sockets

const MDNS_GROUP = Sockets.ip"224.0.0.251"
const MDNS_PORT = 5353
const BROWSE_TYPES = ["_rift._tcp", "_flask-link._tcp"]

const T_A, T_PTR, T_TXT, T_SRV, T_ANY = 0x0001, 0x000c, 0x0010, 0x0021, 0x00ff
const CLASS_IN, CACHE_FLUSH = 0x0001, 0x8000

mutable struct Peers
    lock::ReentrantLock
    items::Dict{String,String}   # name => "http://ip:port"
end
Peers() = Peers(ReentrantLock(), Dict{String,String}())

peers_snapshot(p::Peers) = lock(() -> sort!(collect(p.items); by=first), p.lock)

# ---- DNS wire format -------------------------------------------------------

u16(x) = UInt8[(x >> 8) & 0xff, x & 0xff]
u32(x) = UInt8[(x >> 24) & 0xff, (x >> 16) & 0xff, (x >> 8) & 0xff, x & 0xff]

function encode_name(name::AbstractString)
    out = UInt8[]
    for label in split(rstrip(name, '.'), '.')
        append!(out, UInt8[length(codeunits(label))], codeunits(label))
    end
    push!(out, 0x00)
    return out
end

function record(name, type, class, ttl, rdata)
    return vcat(encode_name(name), u16(type), u16(class), u32(ttl), u16(length(rdata)), rdata)
end

function dns_packet(flags, questions, answers, additionals)
    return vcat(u16(0), u16(flags), u16(length(questions)), u16(length(answers)), u16(0), u16(length(additionals)),
                reduce(vcat, questions; init=UInt8[]), reduce(vcat, answers; init=UInt8[]), reduce(vcat, additionals; init=UInt8[]))
end

question(name, type) = vcat(encode_name(name), u16(type), u16(CLASS_IN))

# Our own records for `ttl` (0 = goodbye).
function own_records(cfg::Config, ttl)
    service = "_rift._tcp.local"
    instance = "$(cfg.name).$service"
    host = "$(cfg.name).local"
    ptr = record(service, T_PTR, CLASS_IN, ttl, encode_name(instance))
    srv = record(instance, T_SRV, CACHE_FLUSH | CLASS_IN, ttl, vcat(u16(0), u16(0), u16(cfg.port), encode_name(host)))
    txt_entry = codeunits("role=fleet_manager")
    txt = record(instance, T_TXT, CACHE_FLUSH | CLASS_IN, ttl, vcat(UInt8[length(txt_entry)], txt_entry))
    octets = UInt8[parse(UInt8, o) for o in split(cfg.ip, '.')]
    a = record(host, T_A, CACHE_FLUSH | CLASS_IN, ttl, octets)
    return [ptr], [srv, txt, a]
end

announce_packet(cfg, ttl) = dns_packet(0x8400, [], own_records(cfg, ttl)...)

# Reads a (possibly compressed) name starting at 1-based index `pos`.
function read_name(buf::Vector{UInt8}, pos::Int)
    labels = String[]
    next_pos = 0
    hops = 0
    while true
        len = buf[pos]
        if len == 0
            pos += 1
            break
        elseif len & 0xc0 == 0xc0
            next_pos == 0 && (next_pos = pos + 2)
            pos = ((Int(len & 0x3f) << 8) | Int(buf[pos + 1])) + 1
            (hops += 1) > 32 && error("compression loop")
        else
            push!(labels, String(buf[pos + 1:pos + len]))
            pos += 1 + len
        end
    end
    return join(labels, "."), (next_pos == 0 ? pos : next_pos)
end

rd16(buf, pos) = (Int(buf[pos]) << 8) | Int(buf[pos + 1])

struct DnsRecord
    name::String
    type::Int
    ttl::Int
    data::Any
end

# Parses a packet into (questions::Vector{Tuple{String,Int}}, records::Vector{DnsRecord}).
function parse_packet(buf::Vector{UInt8})
    qd, an, ns, ar = rd16(buf, 5), rd16(buf, 7), rd16(buf, 9), rd16(buf, 11)
    pos = 13
    questions = Tuple{String,Int}[]
    for _ in 1:qd
        name, pos = read_name(buf, pos)
        push!(questions, (name, rd16(buf, pos)))
        pos += 4
    end
    records = DnsRecord[]
    for _ in 1:(an + ns + ar)
        name, pos = read_name(buf, pos)
        type = rd16(buf, pos)
        ttl = (Int(buf[pos + 4]) << 24) | (Int(buf[pos + 5]) << 16) | (Int(buf[pos + 6]) << 8) | Int(buf[pos + 7])
        rdlen = rd16(buf, pos + 8)
        rdstart = pos + 10
        data = nothing
        if type == T_PTR
            data = first(read_name(buf, rdstart))
        elseif type == T_SRV
            target, _ = read_name(buf, rdstart + 6)
            data = (rd16(buf, rdstart + 4), target)   # (port, target host)
        elseif type == T_A && rdlen == 4
            data = join(Int.(buf[rdstart:rdstart + 3]), ".")
        end
        push!(records, DnsRecord(name, type, ttl, data))
        pos = rdstart + rdlen
    end
    return questions, records
end

# ---- responder + browser -----------------------------------------------------

mutable struct Mdns
    cfg::Config
    peers::Peers
    sock::Sockets.UDPSocket
    running::Bool
    srv::Dict{String,Tuple{Int,String}}   # lowercase instance => (port, target host)
    addrs::Dict{String,String}            # lowercase host => IPv4
    instances::Dict{String,String}        # lowercase instance => original-case instance
end

send_packet(m::Mdns, packet) = Sockets.send(m.sock, MDNS_GROUP, MDNS_PORT, packet)

function publish_peers!(m::Mdns)
    for (key, (port, target)) in m.srv
        instance = m.instances[key]
        short = first(split(instance, '.'))
        short == m.cfg.name && continue
        ip = get(m.addrs, lowercase(target), nothing)
        ip === nothing && continue
        lock(m.peers.lock) do
            m.peers.items[short] = "http://$ip:$port"
        end
    end
end

function browsed_type(name::String)
    lname = lowercase(name)
    return any(t -> endswith(lname, "." * t * ".local") || lname == t * ".local", BROWSE_TYPES)
end

function handle_packet!(m::Mdns, buf::Vector{UInt8})
    questions, records = parse_packet(buf)
    cfg = m.cfg
    service = "_rift._tcp.local"
    instance = lowercase("$(cfg.name).$service")
    host = lowercase("$(cfg.name).local")

    # Someone is asking about us: answer (multicast).
    for (qname, qtype) in questions
        q = lowercase(qname)
        if (q == service && qtype in (T_PTR, T_ANY)) || (q == instance && qtype in (T_SRV, T_TXT, T_ANY)) || (q == host && qtype in (T_A, T_ANY))
            send_packet(m, announce_packet(cfg, 120))
            break
        end
    end

    for r in records
        lname = lowercase(r.name)
        if r.type == T_PTR && any(t -> lname == t * ".local", BROWSE_TYPES)
            inst = r.data::String
            key = lowercase(inst)
            short = first(split(inst, '.'))
            if r.ttl == 0                      # goodbye
                lock(m.peers.lock) do
                    delete!(m.peers.items, short)
                end
            elseif short != cfg.name
                m.instances[key] = inst
                haskey(m.srv, key) || send_packet(m, dns_packet(0x0000, [question(inst, T_SRV)], [], []))
            end
        elseif r.type == T_SRV && browsed_type(r.name)
            port, target = r.data::Tuple{Int,String}
            m.instances[lname] = r.name
            m.srv[lname] = (port, target)
            haskey(m.addrs, lowercase(target)) || send_packet(m, dns_packet(0x0000, [question(target, T_A)], [], []))
        elseif r.type == T_A && r.data !== nothing
            m.addrs[lname] = r.data::String
        end
    end
    publish_peers!(m)
end

function receive_loop(m::Mdns)
    while m.running
        try
            buf = Sockets.recv(m.sock)
            handle_packet!(m, collect(UInt8, buf))
        catch e
            (e isa InterruptException || !m.running) && break
            e isa EOFError && break
            # A malformed packet from someone else must never take the responder down.
        end
    end
end

function query_loop(m::Mdns)
    announced = 0
    while m.running
        for t in BROWSE_TYPES
            send_packet(m, dns_packet(0x0000, [question(t * ".local", T_PTR)], [], []))
        end
        if announced < 3
            send_packet(m, announce_packet(m.cfg, 120))
            announced += 1
        end
        for _ in 1:(announced < 3 ? 10 : 100)   # ~1s while announcing, then every ~10s
            m.running || return
            sleep(0.1)
        end
    end
end

# Publishes the service and starts browsing. Call stop_mdns! on the result to unregister.
function start_mdns(cfg::Config, peers::Peers)
    sock = Sockets.UDPSocket()
    Sockets.bind(sock, Sockets.ip"0.0.0.0", MDNS_PORT; reuseaddr=true)
    Sockets.join_multicast_group(sock, MDNS_GROUP)
    Sockets.setopt(sock; multicast_loop=true)   # so a second instance on this machine hears us
    m = Mdns(cfg, peers, sock, true, Dict(), Dict(), Dict())
    @async receive_loop(m)
    @async query_loop(m)
    return m
end

function stop_mdns!(m::Mdns)
    m.running = false
    try
        send_packet(m, announce_packet(m.cfg, 0))   # goodbye
    catch
    end
    try
        close(m.sock)
    catch
    end
end
