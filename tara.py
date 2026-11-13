import os, re, sys, time, json, types, ctypes, sqlite3, threading, subprocess, webbrowser, urllib.parse, urllib.request
import tkinter as tk
import keyboard, numpy as np, sounddevice as sd

for _m in ("av", "onnxruntime"): sys.modules[_m] = types.ModuleType(_m)
os.environ.setdefault("GEMINI_API_KEY", "AIzaSyAqWtDTfCKYflJJ7IlT8Vyv4mCjSNfYboE")
DB, MODEL = "tara.db", "tara-core"
APPS = {"code": "code", "vscode": "code", "kicad": "kicad", "calc": "calc.exe", "cmd": "wt.exe", "settings": "ms-settings:"}
WEBS = {"youtube": "https://youtube.com", "github": "https://github.com", "gmail": "https://mail.google.com"}

def db_exec(sql, params=()):
    with sqlite3.connect(DB) as c:
        c.execute("CREATE TABLE IF NOT EXISTS mem (id INTEGER PRIMARY KEY, k TEXT, v TEXT)")
        return c.execute(sql, params).fetchall()

def http_post(url: str, payload: dict, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)

def speak_sync(text: str):
    clean = text.replace('"', "'").replace("\n", " ")[:400]
    cmd = f'Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak("{clean}")'
    subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", cmd], creationflags=0x08000000)

def fast_route(raw: str) -> str | None:
    t, low = raw.strip(), raw.strip().lower()
    if low == "status":
        class MEM(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [(f"u{i}", ctypes.c_ulonglong) for i in range(7)]
        m = MEM(ctypes.sizeof(MEM)); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return f"RAM {m.dwMemoryLoad}% ({(m.u0 - m.u1)//1024**3}/{m.u0//1024**3}GB)"
    if low == "free":
        try: http_post("http://localhost:11434/api/generate", {"model": MODEL, "keep_alive": 0}, 2)
        except Exception: pass
        return "RAM freed."
    if low in ("quit", "exit"):
        try: http_post("http://localhost:11434/api/generate", {"model": MODEL, "keep_alive": 0}, 1)
        except Exception: pass
        os._exit(0)
    if low == "ports":
        import serial.tools.list_ports
        pts = [f"{p.device} ({p.description})" for p in serial.tools.list_ports.comports()]
        return "Ports: " + (", ".join(pts) if pts else "None")
    if low.startswith("ser "):
        import serial
        p = t.split(" ", 2)
        with serial.Serial(p[1].upper(), 115200, timeout=1) as s:
            if len(p) > 2: s.write((p[2] + "\n").encode()); time.sleep(0.15)
            return f"[{p[1].upper()}]: " + (s.read_all().decode(errors="ignore").strip() or "Sent.")
    if low.startswith("smd "):
        c = t[4:].strip().upper()
        v = float(c.replace("R", ".")) if "R" in c else (int(c[:-1]) * (10 ** int(c[-1])) if c.isdigit() and len(c) in (3, 4) else -1)
        return f"{v/1e6:g} MΩ" if v >= 1e6 else (f"{v/1e3:g} kΩ" if v >= 1e3 else (f"{v:g} Ω" if v >= 0 else "Invalid SMD"))
    if low.startswith("remember "):
        db_exec("INSERT INTO mem (k, v) VALUES ('fact', ?)", (t[9:].strip(),)); return "Stored."
    if low == "memories":
        return "\n".join(f"- {r[0]}" for r in db_exec("SELECT v FROM mem WHERE k='fact' ORDER BY id DESC LIMIT 8")) or "Empty."
    if low.startswith(("yt ", "google ")):
        q = urllib.parse.quote_plus(t.split(" ", 1)[1])
        webbrowser.open(f"https://www.youtube.com/results?search_query={q}" if low.startswith("yt ") else f"https://www.google.com/search?q={q}")
        return f"Opened: {t}"
    if low.startswith("open "):
        target = low[5:].strip()
        if target in WEBS: webbrowser.open(WEBS[target]); return f"Web: {target}"
        if target in APPS:
            os.startfile(APPS[target]) if APPS[target].endswith(":") else subprocess.Popen(APPS[target], shell=True)
            return f"App: {target}"
        try: os.startfile(target); return f"Launched: {target}"
        except Exception: return f"Not found: {target}"
    return None

class TARA(tk.Tk):
    def __init__(self):
        super().__init__()
        self.overrideredirect(True); self.attributes("-topmost", True); self.configure(bg="#141413")
        self.w, self.h_col, self.h_exp = 480, 42, 180
        self.x = (self.winfo_screenwidth() - self.w) // 2
        self.geometry(f"{self.w}x{self.h_col}+{self.x}+12")

        self.row = tk.Frame(self, bg="#141413"); self.row.pack(fill="x", padx=8, pady=6)
        self.cv = tk.Canvas(self.row, width=24, height=24, bg="#141413", highlightthickness=0); self.cv.pack(side="left", padx=(0, 6))
        self.ent = tk.Entry(self.row, font=("Consolas", 11), bg="#1C1C1A", fg="#E6E4DD", insertbackground="#E6E4DD",
                            relief="flat", highlightthickness=1, highlightbackground="#2E2E2B", highlightcolor="#2E2E2B")
        self.ent.pack(side="left", fill="both", expand=True, ipady=4)
        self.ent.bind("<Return>", lambda e: self.submit(False))
        self.ent.bind("<Escape>", lambda e: self.toggle_ui(False))
        self.out = tk.Text(self, font=("Consolas", 10), bg="#1C1C1A", fg="#E6E4DD", relief="flat", wrap="word", height=7)

        self.state, self.phase, self.rms, self.last_hk, self.chat_loop = "idle", 0, 0.0, 0.0, False
        self.stt, self.rec_buf = None, []
        keyboard.add_hotkey("alt+space", lambda: self.debounce(self.toggle_ui))
        keyboard.add_hotkey("alt+v", lambda: self.debounce(self.toggle_mic))
        keyboard.add_hotkey("alt+q", lambda: self.debounce(self.grab_clip))
        self.anim()

    def debounce(self, fn):
        if time.monotonic() - self.last_hk > 0.35:
            self.last_hk = time.monotonic(); self.after(0, fn)

    def anim(self):
        self.cv.delete("all"); self.phase = (self.phase + 18) % 360
        if self.state == "idle": self.cv.create_oval(6, 6, 18, 18, outline="#8C8A82", width=1.5)
        elif self.state == "mic":
            r = min(11, 5 + int(self.rms * 40))
            self.cv.create_oval(12 - r, 12 - r, 12 + r, 12 + r, outline="#CC241D", width=2)
        elif self.state == "work":
            self.cv.create_arc(4, 4, 20, 20, start=self.phase, extent=240, outline="#D79921", width=2, style="arc")
        self.after(40 if self.state != "idle" else 250, self.anim)

    def toggle_ui(self, force=None):
        if force if force is not None else not self.winfo_viewable():
            self.out.pack_forget(); self.geometry(f"{self.w}x{self.h_col}+{self.x}+12"); self.deiconify(); self.ent.focus_force()
        else: self.withdraw()
    def grab_clip(self):
            keyboard.send("ctrl+c")
            time.sleep(0.08)
            self.toggle_ui(True)
            self.ent.delete(0, "end")
            self.ent.insert(0, "clip: ")
    def toggle_mic(self):
        if not self.winfo_viewable(): self.toggle_ui(True)
        if self.state == "mic":
            self.force_send = True  # Pressing Alt+V while listening forces immediate transcription
        else:
            self.chat_loop = True
            self.start_listen_turn()

    def start_listen_turn(self):
        if not self.chat_loop: return
        self.state, self.rec_buf, self.force_send = "mic", [], False
        self.ent.configure(highlightbackground="#CC241D", highlightcolor="#CC241D")
        self.ent.delete(0, "end"); self.ent.insert(0, "Listening... (speak, or press Alt+V to send)")
        t_start, t_voice, spoke = time.monotonic(), time.monotonic(), False

        def cb(indata, f, t, s):
            nonlocal t_voice, spoke
            self.rec_buf.append(indata.copy())
            self.rms = float(np.sqrt(np.mean(indata**2)))
            if self.rms > 0.005:  # Sensitive enough for quiet laptop mics
                spoke, t_voice = True, time.monotonic()

        def watcher():
            try:
                with sd.InputStream(samplerate=16000, channels=1, dtype="float32", callback=cb):
                    while self.chat_loop and not self.force_send:
                        time.sleep(0.06); now = time.monotonic()
                        if spoke and (now - t_voice) > 1.2: break
                        if not spoke and (now - t_start) > 8.0:
                            self.chat_loop = False
                            self.after(0, lambda: self.reset_ent("Mic sleep (no speech detected)."))
                            return
                if self.chat_loop or self.force_send:
                    self.after(0, lambda: (setattr(self, "state", "work"), self.ent.delete(0, "end"), self.ent.insert(0, "Transcribing...")))
                    self.transcribe()
            except Exception as e:
                self.chat_loop = False
                self.after(0, lambda err=str(e): self.show_err(f"MIC ERR: {err}"))

        threading.Thread(target=watcher, daemon=True).start()

    def transcribe(self):
        try:
            audio = np.concatenate(self.rec_buf, axis=0).flatten() if self.rec_buf else np.array([])
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            if audio.size < 3200 or peak < 0.002:
                self.after(0, lambda: self.reset_ent(f"Too quiet (peak={peak:.4f})."))
                if self.chat_loop and not self.force_send: self.after(400, self.start_listen_turn)
                return
            audio = (audio / peak) * 0.95
            if not self.stt:
                self.after(0, lambda: (self.ent.delete(0, "end"), self.ent.insert(0, "Loading Whisper tiny.en (first run)...")))
                from faster_whisper import WhisperModel
                self.stt = WhisperModel("tiny.en", device="cpu", compute_type="int8", cpu_threads=4)
            segs, _ = self.stt.transcribe(audio, beam_size=1, language="en", vad_filter=False)
            txt = " ".join(s.text for s in segs).strip().rstrip(".!?")
            if txt.lower() in ("stop", "stop listening", "bye", "sleep"):
                self.chat_loop = False; self.after(0, lambda: self.reset_ent("Talk soon.")); return
            if txt:
                if self.force_send: self.chat_loop = False  # Manual Alt+V stop = single turn
                self.after(0, lambda: (self.reset_ent(txt), self.submit(True)))
            else:
                self.after(0, self.start_listen_turn if self.chat_loop else lambda: self.reset_ent("Didn't catch that."))
        except Exception as e:
            self.chat_loop = False
            self.after(0, lambda err=str(e): self.show_err(f"STT ERR: {err}"))

    def show_err(self, msg: str):
        self.reset_ent("Error.")
        self.geometry(f"{self.w}x{self.h_exp}+{self.x}+12")
        self.out.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.out.insert("end", f"\n{msg}\n"); self.out.see("end")

    def reset_ent(self, txt=""):
        self.state = "idle"; self.ent.configure(highlightbackground="#2E2E2B", highlightcolor="#2E2E2B")
        self.ent.delete(0, "end"); self.ent.insert(0, txt)

    def submit(self, speak=False):
        q = self.ent.get().strip()
        if not q: return
        self.ent.delete(0, "end"); fast = fast_route(q)
        self.geometry(f"{self.w}x{self.h_exp}+{self.x}+12"); self.out.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        if fast:
            self.out.insert("end", f"\n> {q}\n{fast}\n"); self.out.see("end")
            if speak: threading.Thread(target=lambda: (speak_sync(fast), self.after(200, self.start_listen_turn)), daemon=True).start()
            return
        self.state = "work"; self.out.insert("end", f"\nYou: {q}\nTARA: "); self.out.see("end")
        threading.Thread(target=self.ask_llm, args=(q, speak), daemon=True).start()

    def ask_llm(self, q: str, speak: bool):
        clip_ctx = ""
        if q.lower().startswith("clip:"):
            try: clip_ctx = f"Clipboard:\n{self.clipboard_get()[:1500]}\n"
            except Exception: pass
            q = q[5:].strip() or "Explain or fix this clipboard content."
        facts = [r[0] for r in db_exec("SELECT v FROM mem WHERE k='fact' ORDER BY id DESC LIMIT 5")]
        hist = [r[0] for r in db_exec("SELECT v FROM mem WHERE k='chat' ORDER BY id DESC LIMIT 6")][::-1]
        sys_p = (
            "You are T.A.R.A., an equal thinking partner and co-builder. Talk naturally like a sharp close friend in 1-3 sentences. "
            "If the user wants an app opened, a YouTube search, or a fact remembered, append [CMD: open app], [CMD: yt query], or [CMD: remember fact] at the end.\n"
        )
        ctx = ("Facts: " + "; ".join(facts) + "\n" if facts else "") + clip_ctx + "\n".join(hist) + f"\nYou: {q}\nTARA:"
        ans = ""
        try:
            if q.lower().startswith("cloud:") and os.environ.get("GEMINI_API_KEY"):
                u = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={os.environ['GEMINI_API_KEY']}"
                r = json.loads(http_post(u, {"contents": [{"parts": [{"text": ctx}]}]}, 12).read().decode())
                ans = r["candidates"][0]["content"]["parts"][0]["text"].strip()
                self.after(0, lambda: (self.out.insert("end", ans + "\n"), self.out.see("end")))
            else:
                with http_post("http://localhost:11434/api/generate", {"model": MODEL, "prompt": ctx, "stream": True, "keep_alive": "10m"}, 30) as r:
                    buf = ""
                    for line in r:
                        tok = json.loads(line.decode()).get("response", "")
                        ans += tok; buf += tok
                        if len(buf) >= 12 or "\n" in buf:
                            c = buf; buf = ""
                            self.after(0, lambda c=c: (self.out.insert("end", c), self.out.see("end")))
                    if buf: self.after(0, lambda c=buf: self.out.insert("end", c))
                    self.after(0, lambda: (self.out.insert("end", "\n"), self.out.see("end")))
            if ans:
                db_exec("INSERT INTO mem (k, v) VALUES ('chat', ?)", (f"You: {q}\nTARA: {ans.strip()}",))
                db_exec("DELETE FROM mem WHERE k='chat' AND id NOT IN (SELECT id FROM mem WHERE k='chat' ORDER BY id DESC LIMIT 6)")
                for m in re.findall(r"\[CMD:\s*(.+?)\]", ans):
                    fast_route(m)
                ans = re.sub(r"\[CMD:.*?\]", "", ans).strip()
            if speak and ans: speak_sync(ans)
        except Exception as e:
            self.after(0, lambda: self.out.insert("end", f"ERR: {e}\n"))
        finally:
            self.after(0, lambda: setattr(self, "state", "idle"))
            if self.chat_loop: time.sleep(0.25); self.after(0, self.start_listen_turn)

if __name__ == "__main__":
    if ctypes.windll.kernel32.CreateMutexW(None, False, "TARA_V2_MUTEX") and ctypes.windll.kernel32.GetLastError() == 183:
        sys.exit(0)
    TARA().mainloop()