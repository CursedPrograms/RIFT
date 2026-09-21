# registry.jl - fleet registry: robots/managers that have called POST /register,
# expiring after the TTL unless they keep heartbeating. Julia counterpart of
# app.py's _fleet dict + _prune_fleet().

struct Robot
    name::String
    ip::String
    type::String
    capabilities::Vector{String}
end

mutable struct Registry
    ttl::Float64
    lock::ReentrantLock
    members::Dict{String,Tuple{Robot,Float64}}   # name => (robot, last_seen)
    order::Vector{String}                        # insertion order, like a Python dict
end

Registry(ttl::Real) = Registry(Float64(ttl), ReentrantLock(), Dict{String,Tuple{Robot,Float64}}(), String[])

function register!(r::Registry, name, ip, type, caps; now::Real=time())
    lock(r.lock) do
        name in r.order || push!(r.order, name)
        r.members[name] = (Robot(name, ip, type, collect(String, caps)), Float64(now))
    end
end

# The live roster, dropping anything not heard from within the TTL.
function robots!(r::Registry; now::Real=time())
    lock(r.lock) do
        stale = [n for n in r.order if now - r.members[n][2] > r.ttl]
        for n in stale
            delete!(r.members, n)
        end
        filter!(n -> !(n in stale), r.order)
        return [r.members[n][1] for n in r.order]
    end
end
