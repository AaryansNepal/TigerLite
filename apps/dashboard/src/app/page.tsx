"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { createClient } from "@/lib/supabase/client";

type Mode = "signin" | "signup";

export default function HomePage() {
  const router = useRouter();
  const supabase = createClient();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [info, setInfo] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setInfo(null);

    // Clear any stale session before authenticating. Without this, leftover
    // cookies from a prior signed-in session can leak into the new request:
    // signUp succeeds in creating the new user, but the browser still has
    // the OLD user's cookie, so /home renders the old account's data.
    await supabase.auth.signOut();

    if (mode === "signin") {
      const { data, error } = await supabase.auth.signInWithPassword({ email, password });
      setBusy(false);
      if (error) {
        setErr(error.message);
        return;
      }
      if (!data.session) {
        setErr("Sign in succeeded but no session was returned. Try again.");
        return;
      }
      // Force a server re-render so middleware sees the new cookie before navigating.
      router.refresh();
      router.push("/home");
      return;
    }

    // signup
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: `${window.location.origin}/home` },
    });
    setBusy(false);
    if (error) {
      setErr(error.message);
      return;
    }
    if (!data.session) {
      // Email confirmation is enabled in Supabase. The user exists but isn't
      // signed in yet. Don't push to /home — show a "check your email" note.
      setInfo(`Account created. Check ${email} for a confirmation link, then sign in.`);
      setMode("signin");
      setPassword("");
      return;
    }
    router.refresh();
    router.push("/home");
  }

  return (
    <main className="min-h-screen bg-white text-black flex flex-col items-center justify-between py-10 px-6">
      <header className="w-full max-w-md flex items-center justify-between text-[10px] uppercase tracking-widest font-pixel">
        <span>v2.0</span>
        <span>· tigerlite ·</span>
        <a
          href="https://github.com/AaryansNepal/TigerLite"
          target="_blank"
          rel="noreferrer"
          className="hover:underline"
        >
          github
        </a>
      </header>

      <section className="w-full max-w-md flex flex-col items-center gap-10 mt-12">
        <div className="text-center space-y-4 select-none">
          <h1 className="font-pixel text-3xl sm:text-4xl leading-[1.4]">
            TIGER
            <br />
            LITE
          </h1>
          <p className="font-mono text-xs sm:text-sm text-black/70">
            ai ops, on autopilot.
          </p>
        </div>

        <div className="w-full border-2 border-black p-6 space-y-5">
          <div className="grid grid-cols-2 border-2 border-black font-pixel text-[10px] uppercase">
            <button
              type="button"
              onClick={() => {
                setMode("signin");
                setErr(null);
              }}
              className={`py-3 transition-colors ${
                mode === "signin"
                  ? "bg-black text-white"
                  : "bg-white text-black hover:bg-black/5"
              }`}
            >
              sign in
            </button>
            <button
              type="button"
              onClick={() => {
                setMode("signup");
                setErr(null);
              }}
              className={`py-3 transition-colors border-l-2 border-black ${
                mode === "signup"
                  ? "bg-black text-white"
                  : "bg-white text-black hover:bg-black/5"
              }`}
            >
              sign up
            </button>
          </div>

          <form onSubmit={onSubmit} className="space-y-3">
            <label className="block">
              <span className="font-pixel text-[9px] uppercase tracking-widest text-black/60">
                email
              </span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="you@domain.com"
                className="mt-1 w-full border-2 border-black bg-white px-3 py-2 font-mono text-sm placeholder:text-black/30 focus:outline-none focus:bg-black/5"
                autoComplete="email"
              />
            </label>
            <label className="block">
              <span className="font-pixel text-[9px] uppercase tracking-widest text-black/60">
                password
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={mode === "signup" ? 8 : 1}
                placeholder={mode === "signup" ? "8+ characters" : "••••••••"}
                className="mt-1 w-full border-2 border-black bg-white px-3 py-2 font-mono text-sm placeholder:text-black/30 focus:outline-none focus:bg-black/5"
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
              />
            </label>

            <button
              type="submit"
              disabled={busy}
              className="w-full border-2 border-black bg-black text-white py-3 font-pixel text-[11px] uppercase tracking-widest hover:bg-white hover:text-black disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {busy
                ? mode === "signin"
                  ? "entering..."
                  : "creating..."
                : mode === "signin"
                  ? "enter →"
                  : "create →"}
            </button>

            {err && (
              <p className="font-mono text-xs border-2 border-black bg-black text-white px-3 py-2">
                ! {err}
              </p>
            )}
            {info && (
              <p className="font-mono text-xs border-2 border-black bg-white text-black px-3 py-2">
                &gt; {info}
              </p>
            )}
          </form>
        </div>

        <p className="font-mono text-xs text-black/60 text-center">
          {mode === "signin" ? (
            <>
              new here?{" "}
              <button
                onClick={() => setMode("signup")}
                className="underline hover:no-underline"
              >
                create an account
              </button>
            </>
          ) : (
            <>
              already have one?{" "}
              <button
                onClick={() => setMode("signin")}
                className="underline hover:no-underline"
              >
                sign in
              </button>
            </>
          )}
        </p>
      </section>

      <footer className="w-full max-w-md mt-12 border-t-2 border-black pt-4 font-pixel text-[9px] uppercase tracking-widest text-black/60 flex items-center justify-between">
        <span>© tigerlite</span>
        <span>made for ops</span>
      </footer>
    </main>
  );
}
