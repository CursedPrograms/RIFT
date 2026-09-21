// RiftRegistry.cs - the fleet registry (robots/managers that have called
// POST /register, expiring after the TTL unless they keep heartbeating) and the
// mDNS peer list. C# counterparts of app.py's _fleet and _peers dicts.

using System;
using System.Collections.Generic;

namespace Rift
{
    public sealed class Robot
    {
        public string Name = "";
        public string Ip = "";
        public string Type = "";
        public List<string> Capabilities = new List<string>();
    }

    public sealed class RiftRegistry
    {
        readonly object gate = new object();
        readonly double ttlSecs;
        readonly Dictionary<string, KeyValuePair<Robot, DateTime>> members = new Dictionary<string, KeyValuePair<Robot, DateTime>>();
        readonly List<string> order = new List<string>(); // insertion order, like a Python dict

        public RiftRegistry(double ttlSecs) { this.ttlSecs = ttlSecs; }

        public void Add(string name, string ip, string type, List<string> caps, DateTime? now = null)
        {
            lock (gate)
            {
                if (!members.ContainsKey(name)) order.Add(name); // re-registering keeps its position
                members[name] = new KeyValuePair<Robot, DateTime>(
                    new Robot { Name = name, Ip = ip, Type = type, Capabilities = caps }, now ?? DateTime.UtcNow);
            }
        }

        // The live roster, dropping anything not heard from within the TTL.
        public List<Robot> Robots(DateTime? now = null)
        {
            lock (gate)
            {
                var t = now ?? DateTime.UtcNow;
                var roster = new List<Robot>();
                var live = new List<string>();
                foreach (var name in order)
                {
                    var m = members[name];
                    if ((t - m.Value).TotalSeconds > ttlSecs) { members.Remove(name); continue; }
                    live.Add(name);
                    roster.Add(m.Key);
                }
                order.Clear();
                order.AddRange(live);
                return roster;
            }
        }
    }

    // name -> "http://ip:port" for every peer seen over mDNS.
    public sealed class RiftPeers
    {
        readonly object gate = new object();
        readonly SortedDictionary<string, string> items = new SortedDictionary<string, string>(StringComparer.Ordinal);

        public void Set(string name, string url) { lock (gate) items[name] = url; }
        public void Remove(string name) { lock (gate) items.Remove(name); }

        public List<KeyValuePair<string, string>> Snapshot()
        {
            lock (gate) return new List<KeyValuePair<string, string>>(items);
        }
    }
}
