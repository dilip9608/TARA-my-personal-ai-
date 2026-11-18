import os, re, io, sys, gc, math, time, wave, json, types, queue, ctypes, asyncio, sqlite3, threading, subprocess, webbrowser, urllib.parse, urllib.request
import tkinter as tk
import keyboard, edge_tts, numpy as np, sounddevice as sd, speech_recognition as sr

for _m in ("av", "onnxruntime"): sys.modules[_m] = types.ModuleType(_m)
if os.path.exists(".env"):
    os.environ.update((k.strip(), v.strip().strip("\"'")) for k, v in (l.split("=", 1) for l in open(".env", encoding="utf-8-sig") if "=" in l and not l.startswith("#")))

DB, MODEL, VOICE = "tara.db", "tara-core", "en-US-AvaMultilingualNeural"
APPS = {
    "chrome": "chrome", "browser": "chrome", "edge": "msedge", "code": "code", "vscode": "code",
    "kicad": "kicad", "calc": "calc.exe", "calculator": "calc.exe", "notepad": "notepad.exe",
    "cmd": "wt.exe", "terminal": "wt.exe", "files": "explorer.exe", "explorer": "explorer.exe", "settings": "ms-settings:"
}
WEBS = {"youtube": "https://youtube.com", "github": "https://github.com", "gmail": "https://mail.google.com"}
BANNED_PHRASES = ("how can i assist you", "how may i help you", "as an ai", "i am an ai")

def db_exec(sql, params=()):
    with sqlite3.connect(DB) as c:
        c.execute("CREATE TABLE IF NOT EXISTS mem (id INTEGER PRIMARY KEY, k TEXT, v TEXT)")
        return c.execute(sql, params).fetchall()

def http_post(url: str, payload: dict, timeout=12):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    try: return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError:
        if "11434" in url:
            subprocess.Popen(["ollama", "serve"], creationflags=0x08000000); time.sleep(1.2)
            return urllib.request.urlopen(req, timeout=timeout)
        raise

# --- Single-Pass Continuous Neural TTS (Zero Inter-Sentence Pause, Zero Clipped Words) ---
_play_q, _abort_tts, _is_speaking, _tts_idx = queue.Queue(), False, False, 0

def _tts_worker():
    global _is_speaking, _tts_idx
    mci = ctypes.windll.winmm.mciSendStringW
    buf = ctypes.create_unicode_buffer(32)
    while True:
        text = _play_q.get()
        mp3 = None
        try:
            if _abort_tts: continue
            _tts_idx += 1
            mp3 = os.path.abspath(f"tts_stream_{_tts_idx % 6}.mp3")
            asyncio.run(edge_tts.Communicate(text, VOICE, rate="+0%", pitch="+0Hz").save(mp3))
            if not _abort_tts and os.path.exists(mp3):
                _is_speaking = True
                mci("close all", None, 0, 0)
                mci(f'open "{mp3}" type mpegvideo alias v', None, 0, 0)
                mci("play v", None, 0, 0)
                while not _abort_tts:
                    mci("status v mode", buf, 32, 0)
                    if buf.value != "playing": break
                    time.sleep(0.03)
                if not _abort_tts: time.sleep(0.35)
                mci("close v", None, 0, 0)
        except Exception: pass
        finally:
            if mp3 and os.path.exists(mp3):
                try: os.remove(mp3)
                except OSError: pass
            _is_speaking = False
            _play_q.task_done()

threading.Thread(target=_tts_worker, daemon=True).start()

def flush_tts():
    global _abort_tts
    _abort_tts = True
    while not _play_q.empty():
        try: _play_q.get_nowait(); _play_q.task_done()
        except Exception: break

def speak_full(text: str):
    global _abort_tts
    _abort_tts = False
    clean = re.sub(r"\[CMD:.*?\]|[*`#_~>\[\](){}]", "", text).replace('"', "'").replace("\n", " ")
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > 1: _play_q.put(clean)

def tts_wait():
    _play_q.join()
    time.sleep(0.25)

# --- Direct YouTube Auto-Player & Fast Router ---
def play_youtube_direct(query: str):
    try:
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=4).read().decode("utf-8", errors="ignore")
        m = re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
        if m:
            webbrowser.open(f"https://www.youtube.com/watch?v={m.group(1)}")
            return
    except Exception: pass
    webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}")

def fast_route(raw: str) -> str | None:
    t = re.sub(r"^(?:hey\s+|ok\s+)?tara[\s,]*", "", raw.strip(), flags=re.I).strip()
    low = re.sub(r"[.!?]+$", "", t.lower()).strip()

    if t.startswith("AIza") or low.startswith("key "):
        k = t[4:].strip() if low.startswith("key ") else t.strip()
        open(".env", "w", encoding="utf-8").write(f"GEMINI_API_KEY={k}\n")
        os.environ["GEMINI_API_KEY"] = k
        return "API key saved. Switched to Global mode."

    if any(w in low for w in ("status", "battery", "ram usage", "check ram")):
        class MEM(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [(f"u{i}", ctypes.c_ulonglong) for i in range(7)]
        m = MEM(ctypes.sizeof(MEM)); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return f"RAM is at {m.dwMemoryLoad}% ({(m.u0 - m.u1)//1024**3} of {m.u0//1024**3} GB used)."

    if low in ("free", "free ram", "clear ram"):
        try: http_post("http://localhost:11434/api/generate", {"model": MODEL, "keep_alive": 0}, 2)
        except Exception: pass
        return "Cleared local model from RAM."

    if "ports" in low:
        import serial.tools.list_ports
        pts = [p.device for p in serial.tools.list_ports.comports()]
        return "Active COM ports: " + (", ".join(pts) if pts else "None plugged in.")

    if low.startswith("smd "):
        c = low[4:].replace(" ", "").upper()
        v = float(c.replace("R", ".")) if "R" in c else (int(c[:-1]) * (10 ** int(c[-1])) if c.isdigit() and len(c) in (3, 4) else -1)
        return f"{v/1e6:g} megaohms" if v >= 1e6 else (f"{v/1e3:g} kiloohms" if v >= 1e3 else (f"{v:g} ohms" if v >= 0 else "Invalid SMD code."))

    if low.startswith("remember"):
        fact = re.sub(r"^remember(?:\s+that)?\s+", "", t, flags=re.I)
        db_exec("INSERT INTO mem (k, v) VALUES ('fact', ?)", (fact,)); return f"Saved to memory: {fact}"

    if "memories" in low or "what do you remember" in low:
        return " • ".join(r[0] for r in db_exec("SELECT v FROM mem WHERE k='fact' ORDER BY id DESC LIMIT 4")) or "Memory bank is empty."

    if "youtube" in low or low.startswith(("yt ", "play ")):
        q = re.sub(r"^(?:please\s+|can you\s+)?(?:yt|youtube|search youtube for|play)\s+|\s+(?:in|on)\s+youtube.*$", "", t, flags=re.I).strip()
        threading.Thread(target=play_youtube_direct, args=(q,), daemon=True).start()
        return f"Playing {q} on YouTube."

    if low.startswith(("google ", "search for ", "search google for ")):
        q = re.sub(r"^(?:google|search google for|search for)\s+", "", t, flags=re.I).strip()
        webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote_plus(q)}")
        return f"Searching Google for {q}."

    if any(low.startswith(p) for p in ("open ", "launch ", "start ")):
        target = re.sub(r"^(?:open|launch|start)\s+(?:the\s+|app\s+)?", "", low).strip()
        for k, v in WEBS.items():
            if k in target: webbrowser.open(v); return f"Opening {k}."
        for k, v in APPS.items():
            if k in target:
                subprocess.Popen(f'start "" {v}', shell=True, creationflags=0x08000000)
                return f"Opening {k}."
        subprocess.Popen(f'start "" "{target}"', shell=True, creationflags=0x08000000)
        return f"Opening {target}."
    return None

# --- Single-Surface Hardware DWM Notch (Zero Double Corners, Zero Canvas Ovals, Zero Lag) ---
class TARA(tk.Tk):
    def __init__(self):
        super().__init__()
        self.bg = "#121211"
        self.fg_ivory = "#F2EFE9"
        self.fg_muted = "#8A867E"
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=self.bg)

        self.sw = self.winfo_screenwidth()
        self.top_hide = 8  # Hides top corners above screen bezel so only bottom DWM hardware curves show
        self.typing_open = False
        self.mode = "GLOBAL" if self.has_valid_key() else "LOCAL"
        self.state, self.phase, self.rms, self.smooth_rms = "idle", 0.0, 0.0, 0.0
        self.last_hk, self.chat_loop = 0.0, False
        self.recognizer, self.stt, self.rec_buf = sr.Recognizer(), None, []

        # Top Bar Frame (Uses native ClearType labels — zero canvas redraw overhead)
        self.top_bar = tk.Frame(self, bg=self.bg, height=36)
        self.top_bar.pack(fill="x", padx=14, pady=(self.top_hide + 6, 4))

        # Tiny 30x20 Waveform Canvas (Only updates 5 vertical rectangles — zero jagged curves)
        self.wave_cv = tk.Canvas(self.top_bar, width=30, height=20, bg=self.bg, highlightthickness=0, bd=0, cursor="hand2")
        self.wave_cv.pack(side="left")
        self.wave_cv.bind("<Button-1>", lambda e: self.toggle_mic())
        self.bars = [self.wave_cv.create_rectangle(3 + i*6, 7, 6 + i*6, 13, fill="#757067", width=0) for i in range(5)]

        # Right Controls (Close & Mode Badge)
        self.close_lbl = tk.Label(self.top_bar, text="✕", font=("Segoe UI", 9), bg=self.bg, fg="#6E6A63", cursor="hand2", padx=4)
        self.close_lbl.pack(side="right")
        self.close_lbl.bind("<Button-1>", lambda e: self.sleep_mode())

        self.badge_lbl = tk.Label(
            self.top_bar, text=self.mode, font=("Segoe UI", 8, "bold"),
            bg="#1E1D1B", fg="#8FB996" if self.mode == "GLOBAL" else self.fg_muted,
            padx=7, pady=1, cursor="hand2"
        )
        self.badge_lbl.pack(side="right", padx=(6, 6))
        self.badge_lbl.bind("<Button-1>", lambda e: self.toggle_mode(False))

        # Center Status / Prompt Label
        self.title_lbl = tk.Label(
            self.top_bar, text="Alt+V to talk  •  Click to type",
            font=("Segoe UI", 9), bg=self.bg, fg=self.fg_ivory, cursor="hand2", anchor="w"
        )
        self.title_lbl.pack(side="left", fill="x", expand=True, padx=10)
        self.title_lbl.bind("<Button-1>", lambda e: self.toggle_typing_bar())

        # Expanded Multi-Line Reply Label (Hidden when compact)
        self.reply_lbl = tk.Label(
            self, text="", font=("Segoe UI", 10), bg=self.bg, fg=self.fg_ivory,
            wraplength=490, justify="left", anchor="nw"
        )
        self.reply_lbl.bind("<Button-1>", lambda e: self.toggle_typing_bar())

        # Quick-Type Entry Bar (Hidden unless clicked or Alt+Space pressed)
        self.ent = tk.Entry(
            self, font=("Segoe UI", 10), bg="#1C1B19", fg=self.fg_ivory,
            insertbackground=self.fg_ivory, relief="flat", highlightthickness=1,
            highlightbackground="#2E2C29", highlightcolor="#C89D66"
        )
        self.ent.bind("<Return>", lambda e: self.submit(False))
        self.ent.bind("<Escape>", lambda e: self.collapse_or_sleep())

        keyboard.add_hotkey("alt+space", lambda: self.debounce(self.toggle_typing_bar))
        keyboard.add_hotkey("alt+v", lambda: self.debounce(self.toggle_mic))
        keyboard.add_hotkey("alt+q", lambda: self.debounce(self.grab_clip))

        self.set_layout(expanded=False)
        self.update_idletasks()
        self.apply_dwm_corners()
        self.animate_wave()

    def apply_dwm_corners(self):
        """Hardware anti-aliased Windows 11 DWM rounded corners on the single window surface."""
        try:
            dwm = ctypes.windll.dwmapi
            for hwnd in (self.winfo_id(), ctypes.windll.user32.GetParent(self.winfo_id())):
                if hwnd:
                    dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4)
                    dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(ctypes.c_int(0x00282624)), 4)
        except Exception:
            pass

    def set_layout(self, expanded: bool, reply_text: str = ""):
        """Instant <1ms layout snap — never resizes the window inside a 60fps loop."""
        if reply_text:
            self.reply_lbl.configure(text=reply_text)
        txt = self.reply_lbl.cget("text")

        if not expanded and not self.typing_open:
            self.reply_lbl.pack_forget()
            self.ent.pack_forget()
            w, h = 380, 48
        else:
            w = 530
            lines = max(1, math.ceil(len(txt) / 58)) if txt else 0
            if txt:
                self.reply_lbl.pack(fill="x", padx=18, pady=(0, 6))
            else:
                self.reply_lbl.pack_forget()
            if self.typing_open:
                self.ent.pack(fill="x", padx=16, pady=(2, 12), ipady=4)
            else:
                self.ent.pack_forget()
            h = 54 + (lines * 22 + 12 if txt else 0) + (42 if self.typing_open else 0)

        x = (self.sw - w) // 2
        self.geometry(f"{w}x{h}+{x}+{-self.top_hide}")

    def animate_wave(self):
        """Only moves the 5 tiny vertical rectangle bars — zero window resize, zero text redraw."""
        self.phase += 0.22
        self.smooth_rms = self.smooth_rms * 0.7 + self.rms * 0.3
        tone_map = {"idle": "#757067", "mic": "#E07A5F", "work": "#D4A359", "speak": "#8FB996"}
        col = "#8FB996" if _is_speaking else tone_map.get(self.state, "#757067")

        for i, bar in enumerate(self.bars):
            x1 = 3 + i * 6
            if self.state == "mic":
                mod = 0.55 + 0.45 * math.sin(self.phase * 2.0 + i)
                amp = max(2, min(9, int(2 + self.smooth_rms * 95 * mod)))
            elif _is_speaking or self.state == "speak":
                amp = 2 + int(6 * abs(math.sin(self.phase * 1.5 + i * 0.8)))
            elif self.state == "work":
                amp = 2 + int(4 * abs(math.sin(self.phase * 1.3 + i)))
            else:
                amp = 2 if i in (0, 4) else (3 if i in (1, 3) else 5)
            self.wave_cv.coords(bar, x1, 10 - amp, x1 + 3, 10 + amp)
            self.wave_cv.itemconfig(bar, fill=col)

        self.after(30 if (self.state != "idle" or _is_speaking) else 250, self.animate_wave)

    def has_valid_key(self) -> bool:
        k = os.environ.get("GEMINI_API_KEY", "")
        return bool(k and k != "YOUR_KEY_HERE" and len(k) > 20)

    def toggle_typing_bar(self, force=None):
        if not self.winfo_viewable():
            self.deiconify()
            self.apply_dwm_corners()
        self.typing_open = force if force is not None else not self.typing_open
        self.set_layout(expanded=self.typing_open or bool(self.reply_lbl.cget("text")))
        if self.typing_open:
            self.after(30, lambda: self.ent.focus_force())

    def collapse_or_sleep(self):
        if self.typing_open or self.reply_lbl.cget("text"):
            self.typing_open = False
            self.reply_lbl.configure(text="")
            self.title_lbl.configure(text="Alt+V to talk  •  Click to type", fg=self.fg_ivory)
            self.set_layout(expanded=False)
        else:
            self.sleep_mode()

    def set_status(self, state: str, subtitle: str = None):
        self.state = state
        clean = re.sub(r"\s+", " ", subtitle).strip() if subtitle else ""
        if state == "mic":
            self.title_lbl.configure(text="Listening...", fg="#E07A5F")
            self.set_layout(expanded=bool(self.reply_lbl.cget("text")))
        elif state == "work":
            self.title_lbl.configure(text=clean or "Thinking...", fg="#D4A359")
            self.set_layout(expanded=True, reply_text=clean if len(clean) > 36 else "")
        elif state == "speak" or _is_speaking:
            self.title_lbl.configure(text="T.A.R.A.", fg="#8FB996")
            self.set_layout(expanded=True, reply_text=clean)
        else:
            if clean:
                if len(clean) <= 38:
                    self.title_lbl.configure(text=clean, fg=self.fg_ivory)
                    self.reply_lbl.configure(text="")
                    self.set_layout(expanded=False)
                else:
                    self.title_lbl.configure(text="T.A.R.A.", fg=self.fg_muted)
                    self.set_layout(expanded=True, reply_text=clean)
            self.after(4500, self._auto_collapse_if_idle)

    def _auto_collapse_if_idle(self):
        if self.state == "idle" and not self.typing_open and not _is_speaking and not self.chat_loop:
            self.reply_lbl.configure(text="")
            self.title_lbl.configure(text="Alt+V to talk  •  Click to type", fg=self.fg_ivory)
            self.set_layout(expanded=False)

    def debounce(self, fn):
        if time.monotonic() - self.last_hk > 0.3:
            self.last_hk = time.monotonic(); self.after(0, fn)

    def sleep_mode(self, speak=False):
        self.chat_loop, self.typing_open = False, False
        flush_tts(); self.stt = None; gc.collect()
        try: http_post("http://localhost:11434/api/generate", {"model": MODEL, "keep_alive": 0}, 1)
        except Exception: pass
        if speak: speak_full("Catch you later. Hit Alt V anytime.")
        self.reply_lbl.configure(text="")
        self.set_layout(expanded=False)
        self.after(200, self.withdraw)

    def grab_clip(self):
        keyboard.send("ctrl+c"); time.sleep(0.08)
        self.toggle_typing_bar(True)
        self.ent.delete(0, "end"); self.ent.insert(0, "clip: ")

    def toggle_mic(self):
        if not self.winfo_viewable():
            self.deiconify()
            self.apply_dwm_corners()
        flush_tts()
        self.chat_loop = not self.chat_loop
        if self.chat_loop:
            self.start_listen_turn()
        else:
            self.rms = 0.0
            self.set_status("idle", "Alt+V to talk  •  Click to type")

    def start_listen_turn(self):
        if not self.chat_loop: return
        while _is_speaking: time.sleep(0.05)
        self.rec_buf, self.rms = [], 0.0
        self.set_status("mic")
        t_start, t_voice, spoke, speech_chunks, floor = time.monotonic(), time.monotonic(), False, 0, []
        thresh = 0.045

        def cb(indata, f, t, s):
            nonlocal t_voice, spoke, speech_chunks, thresh
            if _is_speaking: return
            self.rec_buf.append(indata.copy())
            self.rms = float(np.sqrt(np.mean(indata**2)))
            if len(floor) < 8:
                floor.append(self.rms)
                thresh = max(0.042, float(np.mean(floor)) * 3.2)
            elif self.rms > thresh:
                speech_chunks += 1
                if speech_chunks >= 5:
                    spoke, t_voice = True, time.monotonic()
            else:
                if not spoke: speech_chunks = max(0, speech_chunks - 1)

        def watcher():
            try:
                with sd.InputStream(samplerate=16000, channels=1, dtype="float32", callback=cb):
                    while self.chat_loop:
                        time.sleep(0.06); now = time.monotonic()
                        if spoke and (now - t_voice) > 1.0: break
                        if not spoke and (now - t_start) > 12.0:
                            self.chat_loop = False
                            self.after(0, lambda: self.set_status("idle", "Alt+V to talk  •  Click to type"))
                            return
                self.rms = 0.0
                if self.chat_loop and spoke:
                    self.after(0, lambda: self.set_status("work", "Recognizing speech..."))
                    self.transcribe()
            except Exception:
                self.chat_loop = False; self.after(0, lambda: self.set_status("idle", "Mic error"))

        threading.Thread(target=watcher, daemon=True).start()

    def transcribe(self):
        try:
            audio = np.concatenate(self.rec_buf, axis=0).flatten()
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            if peak < 0.05 or audio.size < 8000:
                self.after(100, self.start_listen_turn); return

            norm_pcm = ((audio / peak) * 0.85 * 32767).astype(np.int16).tobytes()
            audio_data = sr.AudioData(norm_pcm, 16000, 2)
            txt = ""

            try:
                txt = self.recognizer.recognize_google(audio_data, language="en-IN").strip()
            except sr.UnknownValueError:
                self.after(100, self.start_listen_turn); return
            except sr.RequestError:
                if not self.stt:
                    from faster_whisper import WhisperModel
                    self.stt = WhisperModel("tiny.en", device="cpu", compute_type="int8", cpu_threads=4)
                segs, _ = self.stt.transcribe(audio, beam_size=2, language="en", vad_filter=False, condition_on_previous_text=False)
                txt = " ".join(s.text.strip() for s in segs if s.no_speech_prob < 0.4).strip()

            if txt and len(txt) > 1:
                self.after(0, lambda: (self.ent.delete(0, "end"), self.ent.insert(0, txt), self.submit(True)))
            else:
                self.after(100, self.start_listen_turn)
        except Exception:
            self.after(100, self.start_listen_turn)

    def toggle_mode(self, speak=False, target=None):
        self.mode = target if target else ("GLOBAL" if self.mode == "LOCAL" else "LOCAL")
        if self.mode == "GLOBAL" and not self.has_valid_key():
            self.mode = "LOCAL"
            msg = "Click here and paste a new AIza... key for Global."
        else:
            msg = f"Switched to {self.mode.lower()} mode."
        self.badge_lbl.configure(text=self.mode, fg="#8FB996" if self.mode == "GLOBAL" else self.fg_muted)
        self.set_status("idle", msg)
        if speak: threading.Thread(target=lambda: (speak_full(msg), tts_wait(), self.after(100, self.start_listen_turn)), daemon=True).start()

    def submit(self, speak=False):
        q = self.ent.get().strip()
        if not q: return
        flush_tts(); self.ent.delete(0, "end")
        low_q = re.sub(r"^(?:hey\s+)?tara[\s,]*", "", q.lower()).strip().rstrip(".!?")

        if low_q in ("quit", "exit", "sleep", "close", "stop", "bye"):
            self.sleep_mode(speak); return
        if "switch" in low_q or low_q in ("local mode", "global mode"):
            tgt = "LOCAL" if "local" in low_q else ("GLOBAL" if "global" in low_q else None)
            self.toggle_mode(speak, tgt); return

        fast = fast_route(q)
        if fast:
            if q.startswith("AIza") or low_q.startswith("key "):
                self.mode = "GLOBAL"
                self.badge_lbl.configure(text="GLOBAL", fg="#8FB996")
            self.set_status("speak" if speak else "idle", fast)
            if speak: threading.Thread(target=lambda: (speak_full(fast), tts_wait(), self.after(0, lambda: self.set_status("idle", fast)), self.after(100, self.start_listen_turn)), daemon=True).start()
            return

        self.set_status("work", f'"{q}"')
        threading.Thread(target=self.ask_llm, args=(q, speak), daemon=True).start()

    def ask_llm(self, q: str, speak: bool):
        if q.lower().startswith("clip:"):
            try: q = f"Clipboard:\n{self.clipboard_get()[:1200]}\nQuestion: {q[5:].strip() or 'Check this out.'}"
            except Exception: pass
        facts = "; ".join(r[0] for r in db_exec("SELECT v FROM mem WHERE k='fact' ORDER BY id DESC LIMIT 5"))
        hist = [json.loads(r[0]) for r in db_exec("SELECT v FROM mem WHERE k='chat4' ORDER BY id DESC LIMIT 6")][::-1]
        sys_msg = (
            "You are T.A.R.A., a sharp, warm, grounded co-builder and close friend. "
            "NEVER say 'Hello! How can I assist you today?' or sound like a generic support bot. "
            "Reply naturally in 1 to 2 short, complete, conversational sentences with real personality. "
            "If asked to open an app or play a song on YouTube, include [CMD: open app] or [CMD: play song on youtube]."
            + (f" Context: {facts}" if facts else "")
        )
        few_shot = [
            {"role": "user", "content": "hey"},
            {"role": "assistant", "content": "Hey! What are we building or testing right now?"},
            {"role": "user", "content": "how are you doing"},
            {"role": "assistant", "content": "Running clean and ready to roll. What's on your mind?"}
        ]
        ans = ""
        try:
            if self.mode == "GLOBAL" and self.has_valid_key():
                try:
                    u = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={os.environ['GEMINI_API_KEY']}"
                    chat_txt = "\n".join(f"{m['role']}: {m['content']}" for m in (few_shot + hist)) + f"\nuser: {q}"
                    payload = {"system_instruction": {"parts": [{"text": sys_msg}]}, "contents": [{"parts": [{"text": chat_txt}]}]}
                    r = json.loads(http_post(u, payload, 10).read().decode())
                    ans = r["candidates"][0]["content"]["parts"][0]["text"].strip()
                    clean_ans = re.sub(r"\[CMD:.*?\]", "", ans).strip()
                    self.after(0, lambda a=clean_ans: self.set_status("speak" if speak else "idle", a))
                except urllib.error.HTTPError as he:
                    if he.code in (400, 403):
                        os.environ["GEMINI_API_KEY"] = ""
                        self.mode = "LOCAL"
                        self.after(0, lambda: self.badge_lbl.configure(text="LOCAL", fg=self.fg_muted))
                except Exception:
                    self.mode = "LOCAL"
                    self.after(0, lambda: self.badge_lbl.configure(text="LOCAL", fg=self.fg_muted))

            if not ans:
                msgs = [{"role": "system", "content": sys_msg}] + few_shot + hist + [{"role": "user", "content": q}]
                with http_post("http://localhost:11434/api/chat", {"model": MODEL, "messages": msgs, "options": {"temperature": 0.65, "num_predict": 90}, "stream": True, "keep_alive": "5m"}, 25) as r:
                    for line in r:
                        tok = json.loads(line.decode()).get("message", {}).get("content", "")
                        ans += tok
                        clean_live = re.sub(r"\[CMD:.*?\]", "", ans).strip()
                        if any(b in clean_live.lower() for b in BANNED_PHRASES):
                            clean_live = "Hey! What are we building or testing right now?"
                            ans = clean_live
                        self.after(0, lambda c=clean_live: self.set_status("work", c))

            if ans:
                for m in re.findall(r"\[CMD:\s*(.+?)\]", ans): fast_route(m)
                clean_ans = re.sub(r"\[CMD:.*?\]", "", ans).strip()
                self.after(0, lambda c=clean_ans: self.set_status("speak" if speak else "idle", c))
                db_exec("INSERT INTO mem (k, v) VALUES ('chat4', ?)", (json.dumps({"role": "user", "content": q}),))
                db_exec("INSERT INTO mem (k, v) VALUES ('chat4', ?)", (json.dumps({"role": "assistant", "content": clean_ans}),))
                db_exec("DELETE FROM mem WHERE k='chat4' AND id NOT IN (SELECT id FROM mem WHERE k='chat4' ORDER BY id DESC LIMIT 10)")
                if speak:
                    speak_full(clean_ans)
                    tts_wait()
        except Exception as e:
            self.after(0, lambda err=str(e): self.set_status("idle", f"Hiccup: {err[:55]}"))
        finally:
            self.after(0, lambda: self.set_status("idle"))
            if self.chat_loop: self.after(150, self.start_listen_turn)

if __name__ == "__main__":
    if ctypes.windll.kernel32.CreateMutexW(None, False, "TARA_V9_CLEAN_MUTEX") and ctypes.windll.kernel32.GetLastError() == 183:
        sys.exit(0)
    TARA().mainloop()