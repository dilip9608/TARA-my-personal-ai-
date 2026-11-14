import os, re, sys, time, json, types, queue, ctypes, asyncio, sqlite3, threading, subprocess, webbrowser, urllib.parse, urllib.request, concurrent.futures
import tkinter as tk
import keyboard, edge_tts, numpy as np, sounddevice as sd

for _m in ("av", "onnxruntime"): sys.modules[_m] = types.ModuleType(_m)
if os.path.exists(".env"): os.environ.update(l.strip().split("=", 1) for l in open(".env", encoding="utf-8-sig") if "=" in l)
DB, MODEL = "tara.db", "tara-core"
APPS = {"code": "code", "vscode": "code", "kicad": "kicad", "calc": "calc.exe", "cmd": "wt.exe", "settings": "ms-settings:"}
WEBS = {"youtube": "https://youtube.com", "github": "https://github.com", "gmail": "https://mail.google.com"}

def db_exec(sql, params=()):
    with sqlite3.connect(DB) as c:
        c.execute("CREATE TABLE IF NOT EXISTS mem (id INTEGER PRIMARY KEY, k TEXT, v TEXT)")
        return c.execute(sql, params).fetchall()

def http_post(url: str, payload: dict, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError:
        if "11434" in url:
            subprocess.Popen(["ollama", "serve"], creationflags=0x08000000)
            time.sleep(1.2)
            return urllib.request.urlopen(req, timeout=timeout)
        raise
_sapi = subprocess.Popen(
    ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
     "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
     "$s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::Female); $s.Rate = 1; "
     "while(($l = [Console]::In.ReadLine()) -ne $null) { if($l){ $s.Speak($l) }; [Console]::Out.WriteLine('DONE') }"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", creationflags=0x08000000
)
_synth_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
_play_q, _tts_idx = queue.Queue(), 0

def _synth_mp3(text: str, idx: int) -> str | None:
    path = os.path.abspath(f"tts_{idx % 4}.mp3")
    try:
        asyncio.run(edge_tts.Communicate(text, "en-US-AvaNeural", rate="+5%").save(path))
        return path
    except Exception:
        return None

def _tts_Loop():
    mci = ctypes.windll.winmm.mciSendStringW
    while True:
        text, fut = _play_q.get()
        try:
            mp3 = fut.result()
            if mp3 and os.path.exists(mp3):
                mci(f'open "{mp3}" type mpegvideo alias v', None, 0, 0)
                mci("play v wait", None, 0, 0)
                mci("close v", None, 0, 0)
                try: os.remove(mp3)
                except OSError: pass
            else:
                _sapi.stdin.write(text + "\n"); _sapi.stdin.flush(); _sapi.stdout.readline()
        finally:
            _play_q.task_done()

threading.Thread(target=_tts_Loop, daemon=True).start()

def enqueue_tts(text: str):
    global _tts_idx
    clean = re.sub(r"\[CMD:.*?\]|[*`#_~>\[\](){}]", "", text).replace('"', "'").replace("\n", " ").strip()
    if len(clean) > 1:
        _tts_idx += 1
        _play_q.put((clean, _synth_pool.submit(_synth_mp3, clean, _tts_idx)))

def tts_wait():
    _play_q.join()
    
def fast_route(raw: str) -> str | None:
    t = re.sub(r"^(?:hey\s+)?tara[\s,]*", "", raw.strip(), flags=re.I).strip()
    low = t.lower().rstrip(".!?")
    if low in ("status", "check status", "system status", "battery", "ram"):
        class MEM(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [(f"u{i}", ctypes.c_ulonglong) for i in range(7)]
        m = MEM(ctypes.sizeof(MEM)); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return f"RAM is at {m.dwMemoryLoad} percent, using {(m.u0 - m.u1)//1024**3} of {m.u0//1024**3} gigabytes."
    if low in ("free", "free ram", "clear ram"):
        try: http_post("http://localhost:11434/api/generate", {"model": MODEL, "keep_alive": 0}, 2)
        except Exception: pass
        return "Local model unloaded from RAM."
    if low in ("quit", "exit", "shut down", "shutdown"):
        try: http_post("http://localhost:11434/api/generate", {"model": MODEL, "keep_alive": 0}, 1)
        except Exception: pass
        os._exit(0)
    if low in ("ports", "check ports", "scan ports"):
        import serial.tools.list_ports
        pts = [f"{p.device} ({p.description})" for p in serial.tools.list_ports.comports()]
        return "Active ports: " + (", ".join(pts) if pts else "None detected.")
    if low.startswith("smd "):
        c = low[4:].replace(" ", "").upper()
        v = float(c.replace("R", ".")) if "R" in c else (int(c[:-1]) * (10 ** int(c[-1])) if c.isdigit() and len(c) in (3, 4) else -1)
        return f"{v/1e6:g} MΩ" if v >= 1e6 else (f"{v/1e3:g} kΩ" if v >= 1e3 else (f"{v:g} Ω" if v >= 0 else "Invalid SMD"))
    if low.startswith(("remember that ", "remember ")):
        fact = re.sub(r"^remember(?:\s+that)?\s+", "", t, flags=re.I)
        db_exec("INSERT INTO mem (k, v) VALUES ('fact', ?)", (fact,)); return f"Remembered: {fact}"
    if low in ("memories", "what do you remember", "show memories"):
        return "\n".join(f"- {r[0]}" for r in db_exec("SELECT v FROM mem WHERE k='fact' ORDER BY id DESC LIMIT 8")) or "Memory bank is empty."
    if low.startswith(("yt ", "youtube ", "search youtube for ", "play ")):
        q = urllib.parse.quote_plus(re.sub(r"^(?:yt|youtube|search youtube for|play)\s+", "", t, flags=re.I))
        webbrowser.open(f"https://www.youtube.com/results?search_query={q}"); return "Opened YouTube."
    if low.startswith(("google ", "search google for ", "search for ")):
        q = urllib.parse.quote_plus(re.sub(r"^(?:google|search google for|search for)\s+", "", t, flags=re.I))
        webbrowser.open(f"https://www.google.com/search?q={q}"); return "Opened Google."
    if low.startswith(("open ", "launch ", "start ")):
        target = re.sub(r"^(?:open|launch|start)\s+", "", low).strip()
        if target in WEBS: webbrowser.open(WEBS[target]); return f"Opened {target}."
        if target in APPS:
            os.startfile(APPS[target]) if APPS[target].endswith(":") else subprocess.Popen(APPS[target], shell=True)
            return f"Launched {target}."
        try: os.startfile(target); return f"Launched {target}."
        except Exception: return f"Could not find {target}."
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
        self.mode = "LOCAL"
        self.badge = tk.Label(self.row, text="LOCAL", font=("Consolas", 9, "bold"), bg="#1C1C1A", fg="#8C8A82", padx=6, pady=3, cursor="hand2")
        self.badge.pack(side="right", padx=(6, 0))
        self.badge.bind("<Button-1>", lambda e: self.toggle_mode(False))
        self.ent.pack(side="left", fill="both", expand=True, ipady=4)
        self.ent.bind("<Return>", lambda e: self.submit(False))
        self.ent.bind("<Escape>", lambda e: self.toggle_ui(False))
        self.last_q = ""
        self.ent.bind("<Up>", lambda e: (self.ent.delete(0, "end"), self.ent.insert(0, self.last_q)))
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
    def toggle_mode(self, speak=False):
        self.mode = "GLOBAL" if self.mode == "LOCAL" else "LOCAL"
        self.badge.configure(text=self.mode, fg="#D79921" if self.mode == "GLOBAL" else "#8C8A82")
        msg = f"Switched to {self.mode.lower()} AI."
        self.reset_ent(msg)
        if speak: threading.Thread(target=lambda: (enqueue_tts(msg), tts_wait(), self.after(200, self.start_listen_turn)), daemon=True).start()

    def submit(self, speak=False):
        q = self.ent.get().strip()
        if not q: return
        self.last_q = q; self.ent.delete(0, "end")
        clean_cmd = re.sub(r"^(?:hey\s+)?tara[\s,]*", "", q.lower()).strip().rstrip(".!?")
        if clean_cmd in ("switch", "switch mode", "switch ai", "change mode"):
            self.toggle_mode(speak); return
        fast = fast_route(q)
        self.geometry(f"{self.w}x{self.h_exp}+{self.x}+12"); self.out.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        if fast:
            self.out.insert("end", f"\n> {q}\n{fast}\n"); self.out.see("end")
            if speak: threading.Thread(target=lambda: (enqueue_tts(fast), tts_wait(), self.after(200, self.start_listen_turn)), daemon=True).start()
            return
        self.state = "work"; self.out.insert("end", f"\nYou: {q}\nTARA [{self.mode}]: "); self.out.see("end")
        threading.Thread(target=self.ask_llm, args=(q, speak), daemon=True).start()

    def ask_llm(self, q: str, speak: bool):
        clip_ctx = ""
        if q.lower().startswith("clip:"):
            try: clip_ctx = f"Clipboard:\n{self.clipboard_get()[:1500]}\n"
            except Exception: pass
            q = q[5:].strip() or "Explain or fix this clipboard content."
        facts = [r[0] for r in db_exec("SELECT v FROM mem WHERE k='fact' ORDER BY id DESC LIMIT 5")]
        hist = [r[0] for r in db_exec("SELECT v FROM mem WHERE k='chat' ORDER BY id DESC LIMIT 6")][::-1]
        ctx = ("Facts: " + "; ".join(facts) + "\n" if facts else "") + clip_ctx + "\n".join(hist) + f"\nYou: {q}\nTARA:"
        ans, s_buf = "", ""
        try:
            if self.mode == "GLOBAL" and os.environ.get("GEMINI_API_KEY"):
                u = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={os.environ['GEMINI_API_KEY']}"
                r = json.loads(http_post(u, {"contents": [{"parts": [{"text": ctx}]}]}, 12).read().decode())
                ans = r["candidates"][0]["content"]["parts"][0]["text"].strip()
                self.after(0, lambda: (self.out.insert("end", ans + "\n"), self.out.see("end")))
                if speak:
                    for sent in re.split(r"(?<=[.!?])\s+|\n+", ans): enqueue_tts(sent)
            else:
                with http_post("http://localhost:11434/api/generate", {"model": MODEL, "prompt": ctx, "stream": True, "keep_alive": "10m"}, 30) as r:
                    ui_buf = ""
                    for line in r:
                        tok = json.loads(line.decode()).get("response", "")
                        ans += tok; ui_buf += tok; s_buf += tok
                        if len(ui_buf) >= 12 or "\n" in ui_buf:
                            c = ui_buf; ui_buf = ""
                            self.after(0, lambda c=c: (self.out.insert("end", c), self.out.see("end")))
                        if speak and re.search(r"[.!?]\s|\n", s_buf) and len(s_buf) > 15:
                            parts = re.split(r"(?<=[.!?])\s+|\n+", s_buf, maxsplit=1)
                            if len(parts) > 1:
                                enqueue_tts(parts[0]); s_buf = parts[1]
                    if ui_buf: self.after(0, lambda c=ui_buf: self.out.insert("end", c))
                    self.after(0, lambda: (self.out.insert("end", "\n"), self.out.see("end")))
                    if speak and s_buf.strip(): enqueue_tts(s_buf)
            if ans:
                for m in re.findall(r"\[CMD:\s*(.+?)\]", ans): fast_route(m)
                clean_ans = re.sub(r"\[CMD:.*?\]", "", ans).strip()
                db_exec("INSERT INTO mem (k, v) VALUES ('chat', ?)", (f"You: {q}\nTARA: {clean_ans}",))
                db_exec("DELETE FROM mem WHERE k='chat' AND id NOT IN (SELECT id FROM mem WHERE k='chat' ORDER BY id DESC LIMIT 6)")
            if speak: tts_wait()
        except Exception as e:
            self.after(0, lambda err=str(e): self.out.insert("end", f"ERR: {err}\n"))
        finally:
            self.after(0, lambda: setattr(self, "state", "idle"))
            if self.chat_loop: time.sleep(0.2); self.after(0, self.start_listen_turn)
if __name__ == "__main__":
    if ctypes.windll.kernel32.CreateMutexW(None, False, "TARA_V2_MUTEX") and ctypes.windll.kernel32.GetLastError() == 183:
        sys.exit(0)
    TARA().mainloop()