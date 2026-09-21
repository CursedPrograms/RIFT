// MiniJson.cs - just enough JSON for the fleet protocol (a robot's JSON
// registration, a /mode request, and a peer's /robots reply), plus a string
// escaper for building responses by hand so key order matches every other RIFT
// implementation. Unity has no built-in arbitrary-JSON parser (JsonUtility needs
// a fixed class), and System.Text.Json isn't in Unity's .NET Standard 2.1 profile.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Rift
{
    public static class MiniJson
    {
        // Objects -> Dictionary<string, object>, arrays -> List<object>,
        // numbers -> double, plus string / bool / null. Throws FormatException.
        public static object Parse(string text)
        {
            int pos = 0;
            object value = ParseValue(text, ref pos);
            SkipWs(text, ref pos);
            if (pos != text.Length) throw new FormatException("trailing data");
            return value;
        }

        static void SkipWs(string s, ref int p)
        {
            while (p < s.Length && char.IsWhiteSpace(s[p])) p++;
        }

        static object ParseValue(string s, ref int p)
        {
            SkipWs(s, ref p);
            if (p >= s.Length) throw new FormatException("unexpected end");
            char c = s[p];
            if (c == '{') return ParseObject(s, ref p);
            if (c == '[') return ParseArray(s, ref p);
            if (c == '"') return ParseString(s, ref p);
            if (Match(s, ref p, "true")) return true;
            if (Match(s, ref p, "false")) return false;
            if (Match(s, ref p, "null")) return null;
            int start = p;
            while (p < s.Length && "+-0123456789.eE".IndexOf(s[p]) >= 0) p++;
            if (start == p) throw new FormatException("unexpected character");
            return double.Parse(s.Substring(start, p - start), CultureInfo.InvariantCulture);
        }

        static bool Match(string s, ref int p, string word)
        {
            if (string.CompareOrdinal(s, p, word, 0, word.Length) != 0) return false;
            p += word.Length;
            return true;
        }

        static Dictionary<string, object> ParseObject(string s, ref int p)
        {
            var result = new Dictionary<string, object>();
            p++;
            SkipWs(s, ref p);
            if (p < s.Length && s[p] == '}') { p++; return result; }
            while (true)
            {
                SkipWs(s, ref p);
                string key = ParseString(s, ref p);
                SkipWs(s, ref p);
                if (p >= s.Length || s[p++] != ':') throw new FormatException("expected ':'");
                result[key] = ParseValue(s, ref p);
                SkipWs(s, ref p);
                if (p >= s.Length) throw new FormatException("unterminated object");
                if (s[p] == ',') { p++; continue; }
                if (s[p] == '}') { p++; return result; }
                throw new FormatException("expected ',' or '}'");
            }
        }

        static List<object> ParseArray(string s, ref int p)
        {
            var result = new List<object>();
            p++;
            SkipWs(s, ref p);
            if (p < s.Length && s[p] == ']') { p++; return result; }
            while (true)
            {
                result.Add(ParseValue(s, ref p));
                SkipWs(s, ref p);
                if (p >= s.Length) throw new FormatException("unterminated array");
                if (s[p] == ',') { p++; continue; }
                if (s[p] == ']') { p++; return result; }
                throw new FormatException("expected ',' or ']'");
            }
        }

        static string ParseString(string s, ref int p)
        {
            if (p >= s.Length || s[p] != '"') throw new FormatException("expected string");
            p++;
            var sb = new StringBuilder();
            while (p < s.Length)
            {
                char c = s[p++];
                if (c == '"') return sb.ToString();
                if (c != '\\') { sb.Append(c); continue; }
                if (p >= s.Length) break;
                char e = s[p++];
                switch (e)
                {
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'u':
                        if (p + 4 > s.Length) throw new FormatException("bad \\u escape");
                        sb.Append((char)int.Parse(s.Substring(p, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
                        p += 4;
                        break;
                    default: sb.Append(e); break;
                }
            }
            throw new FormatException("unterminated string");
        }

        // ---- building ----

        public static string Str(string s)
        {
            var sb = new StringBuilder("\"");
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < ' ') sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            return sb.Append('"').ToString();
        }

        public static string NullOrStr(string s) => string.IsNullOrEmpty(s) ? "null" : Str(s);

        public static string Obj(params KeyValuePair<string, string>[] fields)
        {
            var parts = new string[fields.Length];
            for (int i = 0; i < fields.Length; i++) parts[i] = Str(fields[i].Key) + ":" + fields[i].Value;
            return "{" + string.Join(",", parts) + "}";
        }

        public static string Arr(IEnumerable<string> items) => "[" + string.Join(",", items) + "]";

        public static KeyValuePair<string, string> F(string key, string jsonValue) => new KeyValuePair<string, string>(key, jsonValue);
    }
}
