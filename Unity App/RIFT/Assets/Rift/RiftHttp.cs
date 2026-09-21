// RiftHttp.cs - a minimal HTTP/1.1 server on a plain TcpListener.
//
// The original Unity stub used HttpListener, which on Windows can only bind
// non-localhost prefixes with admin rights (or a URL ACL), so a phone or robot
// on the LAN could never reach it. A TcpListener bound to 0.0.0.0 has no such
// restriction, and this small protocol (short GET/POST requests, one response
// per connection) doesn't need more.

using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

namespace Rift
{
    public sealed class HttpRequestInfo
    {
        public string Method = "";
        public string Path = "";                                   // raw, not URL-decoded
        public string Query = "";
        public Dictionary<string, string> Headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        public string Body = "";
        public string RemoteIp = "";

        public string Header(string name) => Headers.TryGetValue(name, out var v) ? v : "";
    }

    public sealed class HttpReply
    {
        public int Status = 200;
        public string ContentType = "text/plain";
        public byte[] Body = new byte[0];

        public static HttpReply Text(int status, string contentType, string body) =>
            new HttpReply { Status = status, ContentType = contentType, Body = Encoding.UTF8.GetBytes(body) };
    }

    public sealed class RiftHttpServer : IDisposable
    {
        readonly int port;
        readonly Func<HttpRequestInfo, HttpReply> handler;
        TcpListener listener;
        volatile bool running;

        public RiftHttpServer(int port, Func<HttpRequestInfo, HttpReply> handler)
        {
            this.port = port;
            this.handler = handler;
        }

        // Returns null on success, else an error message (e.g. port in use).
        public string Start()
        {
            try
            {
                listener = new TcpListener(IPAddress.Any, port);
                listener.Start();
            }
            catch (SocketException e)
            {
                return "could not bind port " + port + " (already in use?): " + e.Message;
            }
            running = true;
            new Thread(AcceptLoop) { IsBackground = true, Name = "rift-http-accept" }.Start();
            return null;
        }

        void AcceptLoop()
        {
            while (running)
            {
                TcpClient client;
                try { client = listener.AcceptTcpClient(); }
                catch (SocketException) { break; }
                catch (ObjectDisposedException) { break; }
                ThreadPool.QueueUserWorkItem(_ => Handle(client));
            }
        }

        static string ReasonPhrase(int status)
        {
            switch (status)
            {
                case 200: return "OK";
                case 400: return "Bad Request";
                case 404: return "Not Found";
                case 405: return "Method Not Allowed";
                case 500: return "Internal Server Error";
                default: return "Status";
            }
        }

        void Handle(TcpClient client)
        {
            using (client)
            {
                try
                {
                    client.ReceiveTimeout = 5000;
                    client.SendTimeout = 5000;
                    var stream = client.GetStream();
                    var request = ReadRequest(stream, ((IPEndPoint)client.Client.RemoteEndPoint).Address.ToString());
                    HttpReply reply;
                    if (request == null) reply = HttpReply.Text(400, "text/plain", "Bad Request");
                    else
                    {
                        try { reply = handler(request); }
                        catch (Exception e) { reply = HttpReply.Text(500, "text/plain", "Internal Server Error: " + e.Message); }
                    }

                    var head = "HTTP/1.1 " + reply.Status + " " + ReasonPhrase(reply.Status) + "\r\n" +
                               "Content-Type: " + reply.ContentType + "\r\n" +
                               "Content-Length: " + reply.Body.Length + "\r\n" +
                               "Connection: close\r\n\r\n";
                    var headBytes = Encoding.ASCII.GetBytes(head);
                    stream.Write(headBytes, 0, headBytes.Length);
                    stream.Write(reply.Body, 0, reply.Body.Length);
                    stream.Flush();
                }
                catch (IOException) { /* client went away */ }
                catch (SocketException) { }
            }
        }

        static HttpRequestInfo ReadRequest(NetworkStream stream, string remoteIp)
        {
            var buffer = new List<byte>();
            var chunk = new byte[4096];
            int headerEnd = -1;
            while (headerEnd < 0)
            {
                int n = stream.Read(chunk, 0, chunk.Length);
                if (n <= 0) return null;
                for (int i = 0; i < n; i++) buffer.Add(chunk[i]);
                if (buffer.Count > 65536) return null;
                headerEnd = IndexOfHeaderEnd(buffer);
            }

            var headText = Encoding.ASCII.GetString(buffer.GetRange(0, headerEnd).ToArray());
            var lines = headText.Split(new[] { "\r\n" }, StringSplitOptions.None);
            var requestLine = lines[0].Split(' ');
            if (requestLine.Length < 2) return null;

            var info = new HttpRequestInfo { Method = requestLine[0], RemoteIp = remoteIp };
            var target = requestLine[1];
            int q = target.IndexOf('?');
            info.Path = q < 0 ? target : target.Substring(0, q);
            info.Query = q < 0 ? "" : target.Substring(q + 1);
            for (int i = 1; i < lines.Length; i++)
            {
                int colon = lines[i].IndexOf(':');
                if (colon > 0) info.Headers[lines[i].Substring(0, colon).Trim()] = lines[i].Substring(colon + 1).Trim();
            }

            int contentLength = 0;
            int.TryParse(info.Header("Content-Length"), out contentLength);
            if (contentLength > 1 << 20) return null;
            int bodyStart = headerEnd + 4;
            while (buffer.Count - bodyStart < contentLength)
            {
                int n = stream.Read(chunk, 0, chunk.Length);
                if (n <= 0) break;
                for (int i = 0; i < n; i++) buffer.Add(chunk[i]);
            }
            int available = Math.Min(contentLength, buffer.Count - bodyStart);
            info.Body = available > 0 ? Encoding.UTF8.GetString(buffer.GetRange(bodyStart, available).ToArray()) : "";
            return info;
        }

        static int IndexOfHeaderEnd(List<byte> b)
        {
            for (int i = 0; i + 3 < b.Count; i++)
                if (b[i] == 13 && b[i + 1] == 10 && b[i + 2] == 13 && b[i + 3] == 10) return i;
            return -1;
        }

        public void Dispose()
        {
            running = false;
            try { listener?.Stop(); } catch (SocketException) { }
        }
    }
}
