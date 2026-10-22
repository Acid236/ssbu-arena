// SPDX-License-Identifier: GPL-3.0-or-later
// SSBU Arena accounts (Supabase, the same project as ssbuarena.com): sign in through the website in the browser (its
// CAPTCHA needs one: SignInWithBrowser) or with email and password where no CAPTCHA is asked, keep the session
// (the refresh token, encrypted for this Windows user with DPAPI, in config\session.dat), read the player's profile and
// ask for a lobby ticket. The ticket ("<user id>|<name>|<expiry>.<HMAC>") is signed by the database (public.lobby_ticket)
// and checked by the lobby server (tools/net/rb_lobby.c): online play needs a signed-in player. The publishable key below
// is meant for clients; what it can do is decided by Row Level Security and the database functions.
using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

namespace Arena
{
    public sealed class Profile
    {
        public string Id, Email, Username;
        public int Tag, Elo;
        public string Display => Username + "#" + Tag.ToString("0000");
    }

    public static class Account
    {
        public const string Url = "https://gnufjvqwynxmudpgrded.supabase.co";
        public const string Key = "sb_publishable_v5DkzLiVBpTnDMy6BdpI7A_rqZSSQWz";
        public const string SignUpPage = "https://ssbuarena.com/signup";
        public const string AccountPage = "https://ssbuarena.com/account";
        public static string LauncherSignInPage => Environment.GetEnvironmentVariable("SSBU_ARENA_SIGNIN_PAGE") ?? "https://ssbuarena.com/launcher";   // (test: a local site)

        static readonly string SessionFile = Path.Combine(Core.Cfg, "session.dat");
        static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        static string access, refresh;
        static DateTime accessUntil;
        public static Profile Me;

        static Account() { ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12; }

        public static bool SignedIn => Me != null;

        /// <summary>the last session of this PC, if any: refreshed and its profile read. Returns false (no exception) when
        /// there is none or it was revoked; the error text when the server cannot be reached.</summary>
        public static bool Resume(out string error)
        {
            error = null;
            string rt = LoadRefresh();
            if (rt == null) return false;
            try { TokenRequest("refresh_token", new Dictionary<string, object> { { "refresh_token", rt } }); LoadProfile(); return true; }
            catch (ArenaHttpException e) { if (e.Status == 400 || e.Status == 401) { SignOut(); return false; } error = e.Message; return false; }
            catch (Exception e) { error = e.Message; return false; }
        }

        /// <summary>throws with a message for the player on a refused sign-in</summary>
        public static void SignIn(string email, string password)
        {
            try { TokenRequest("password", new Dictionary<string, object> { { "email", email }, { "password", password } }); }
            catch (ArenaHttpException e) when (e.Status == 400)
            {
                throw new Exception(e.Body.Contains("not_confirmed") || e.Body.Contains("Email not confirmed")
                    ? "Your email is not confirmed yet: open the link we sent you, then sign in."
                    : "Wrong email or password.");
            }
            LoadProfile();
        }

        /// <summary>sign-in on ssbuarena.com/launcher in the player's browser, where Supabase's CAPTCHA (Cloudflare Turnstile)
        /// can run: the page signs in with a session of its own that it does not keep, then sends the browser to
        /// http://127.0.0.1:&lt;port&gt;/callback?state=..&amp;refresh_token=.. (a loopback redirect, RFC 8252). This listens there
        /// (only this PC can reach it), checks the state and turns the refresh token into this launcher's session.
        /// Throws with a message for the player; cancel stops the wait.</summary>
        public static void SignInWithBrowser(System.Threading.CancellationToken cancel)
        {
            var listener = new System.Net.Sockets.TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            try
            {
                int port = ((IPEndPoint)listener.LocalEndpoint).Port;
                var raw = new byte[24];
                using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(raw);
                string state = BitConverter.ToString(raw).Replace("-", "").ToLowerInvariant();
                Core.Open(LauncherSignInPage + "?port=" + port + "&state=" + state);
                DateTime until = DateTime.UtcNow.AddMinutes(10);
                while (true)
                {
                    var accept = listener.AcceptTcpClientAsync();
                    while (!accept.Wait(250))
                    {
                        cancel.ThrowIfCancellationRequested();
                        if (DateTime.UtcNow > until) throw new Exception("The sign-in in the browser took too long: try again.");
                    }
                    using (var client = accept.Result)
                    using (var stream = client.GetStream())
                    {
                        stream.ReadTimeout = 5000;
                        string line = new StreamReader(stream, Encoding.ASCII).ReadLine() ?? "";   // GET /callback?.. HTTP/1.1
                        var parts = line.Split(' ');
                        string target = parts.Length >= 2 ? parts[1] : "";
                        var q = System.Web.HttpUtility.ParseQueryString(target.Contains("?") ? target.Substring(target.IndexOf('?') + 1) : "");
                        bool ours = parts[0] == "GET" && target.StartsWith("/callback?") && q["state"] == state && !string.IsNullOrEmpty(q["refresh_token"]);
                        Reply(stream, ours ? "Signed in: go back to the SSBU Arena launcher. You can close this tab."
                                           : "This is the SSBU Arena launcher's sign-in: nothing to do here.");
                        if (!ours) continue;                      // a stray request (favicon, another page): keep waiting
                        TokenRequest("refresh_token", new Dictionary<string, object> { { "refresh_token", q["refresh_token"] } });
                        LoadProfile();
                        return;
                    }
                }
            }
            finally { listener.Stop(); }
        }

        static void Reply(Stream s, string text)
        {
            string html = "<!doctype html><meta charset=utf-8><title>SSBU Arena</title><body style=\"background:#0a1424;color:#e8f1fa;" +
                          "font:18px system-ui;display:grid;place-items:center;height:90vh\"><p>" + WebUtility.HtmlEncode(text) + "</p>";
            byte[] body = Encoding.UTF8.GetBytes(html);
            byte[] head = Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\n" +
                                                  "Connection: close\r\nContent-Length: " + body.Length + "\r\n\r\n");
            s.Write(head, 0, head.Length);
            s.Write(body, 0, body.Length);
        }

        public static void SignOut()
        {
            if (access != null) try { Http("POST", "/auth/v1/logout", "{}", access); } catch { }
            access = refresh = null; Me = null;
            try { File.Delete(SessionFile); } catch { }
        }

        /// <summary>a fresh lobby ticket (8 hours) for the game (SSBU_ONLINE_TICKET)</summary>
        public static string LobbyTicket()
        {
            EnsureAccess();
            return Json.Deserialize<string>(Http("POST", "/rest/v1/rpc/lobby_ticket", "{}", access));
        }

        static void EnsureAccess()
        {
            if (access != null && DateTime.UtcNow < accessUntil) return;
            if (refresh == null) throw new Exception("Not signed in.");
            TokenRequest("refresh_token", new Dictionary<string, object> { { "refresh_token", refresh } });
        }

        static void TokenRequest(string grant, Dictionary<string, object> body)
        {
            var r = Json.Deserialize<Dictionary<string, object>>(Http("POST", "/auth/v1/token?grant_type=" + grant, Json.Serialize(body), null));
            access = (string)r["access_token"];
            refresh = (string)r["refresh_token"];
            accessUntil = DateTime.UtcNow.AddSeconds(Convert.ToDouble(r["expires_in"]) - 60);
            var user = (Dictionary<string, object>)r["user"];
            Me = new Profile { Id = (string)user["id"], Email = user.ContainsKey("email") ? user["email"] as string : "" };
            SaveRefresh(refresh);
        }

        static void LoadProfile()
        {
            var rows = Json.Deserialize<List<Dictionary<string, object>>>(Http("GET", "/rest/v1/profiles?select=username,tag,elo&id=eq." + Me.Id, null, access));
            if (rows.Count == 0) throw new Exception("This account has no Arena profile.");
            Me.Username = (string)rows[0]["username"];
            Me.Tag = Convert.ToInt32(rows[0]["tag"]);
            Me.Elo = Convert.ToInt32(rows[0]["elo"]);
        }

        sealed class ArenaHttpException : Exception
        {
            public int Status; public string Body;
            public ArenaHttpException(int status, string body) : base("Server answered " + status) { Status = status; Body = body ?? ""; }
        }

        static string Http(string method, string path, string body, string bearer)
        {
            var rq = (HttpWebRequest)WebRequest.Create(Url + path);
            rq.Method = method;
            rq.Timeout = 15000;
            rq.Headers["apikey"] = Key;
            if (bearer != null) rq.Headers["Authorization"] = "Bearer " + bearer;
            rq.Accept = "application/json";
            if (body != null)
            {
                var b = Encoding.UTF8.GetBytes(body);
                rq.ContentType = "application/json";
                using (var s = rq.GetRequestStream()) s.Write(b, 0, b.Length);
            }
            try
            {
                using (var rs = (HttpWebResponse)rq.GetResponse())
                using (var sr = new StreamReader(rs.GetResponseStream(), Encoding.UTF8)) return sr.ReadToEnd();
            }
            catch (WebException e) when (e.Response is HttpWebResponse hr)
            {
                string text = "";
                try { using (var sr = new StreamReader(hr.GetResponseStream(), Encoding.UTF8)) text = sr.ReadToEnd(); } catch { }
                throw new ArenaHttpException((int)hr.StatusCode, text);
            }
            catch (WebException e) { throw new Exception("Cannot reach the Arena server: " + e.Message); }
        }

        // the refresh token, for this Windows user only (DPAPI)
        static void SaveRefresh(string token)
        {
            try { File.WriteAllBytes(SessionFile, ProtectedData.Protect(Encoding.UTF8.GetBytes(token), Encoding.ASCII.GetBytes("ssbu-arena session"), DataProtectionScope.CurrentUser)); } catch { }
        }

        static string LoadRefresh()
        {
            try { return File.Exists(SessionFile) ? Encoding.UTF8.GetString(ProtectedData.Unprotect(File.ReadAllBytes(SessionFile), Encoding.ASCII.GetBytes("ssbu-arena session"), DataProtectionScope.CurrentUser)) : null; }
            catch { return null; }
        }
    }
}
