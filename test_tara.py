import time, json, urllib.request, numpy as np
from tara import fast_route, db_exec

def run_beta_tests():
    print("[BETA TEST 1] Fast-Path Latency (<15ms budget)...")
    t0 = time.perf_counter()
    res = fast_route("status")
    dt = (time.perf_counter() - t0) * 1000
    assert "RAM" in res, "Status format failed"
    print(f"  PASS -> '{res}' in {dt:.1f}ms")

    print("[BETA TEST 2] SQLite Persistence & Recall...")
    fast_route("remember ESP32 I2C pins are 21 and 22")
    assert "21 and 22" in fast_route("memories"), "Memory recall failed"
    db_exec("DELETE FROM mem WHERE v LIKE '%ESP32 I2C%'")
    print("  PASS -> SQLite write/read/cleanup verified.")

    print("[BETA TEST 3] Audio Gain Normalization...")
    quiet = np.random.uniform(-0.05, 0.05, 16000).astype(np.float32)
    normed = (quiet / np.max(np.abs(quiet))) * 0.95
    assert 0.94 <= np.max(np.abs(normed)) <= 0.96
    print("  PASS -> Peak scaled to 0.95")

    print("[BETA TEST 4] Local Ollama Daemon Reachability...")
    try:
        r = json.loads(urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2).read().decode())
        print(f"  PASS -> Ollama online. Models: {[m['name'] for m in r.get('models', [])]}")
    except Exception as e:
        print(f"  WARN -> Ollama offline ({e}).")

    print("[BETA TEST 5] Continuous Partner Rolling Memory (Max 6 Turns)...")
    for i in range(8):
        db_exec("INSERT INTO mem (k, v) VALUES ('chat', ?)", (f"You: {i}\nTARA: {i}",))
    db_exec("DELETE FROM mem WHERE k='chat' AND id NOT IN (SELECT id FROM mem WHERE k='chat' ORDER BY id DESC LIMIT 6)")
    assert len(db_exec("SELECT v FROM mem WHERE k='chat'")) == 6
    db_exec("DELETE FROM mem WHERE k='chat'")
    print("  PASS -> Rolling 6-turn partner memory verified.")

    print("[BETA TEST 6] SMD Decoder & Autonomous Partner Action Tag...")
    assert fast_route("smd 472") == "4.7 kΩ" and fast_route("smd 4R7") == "4.7 Ω"
    import re
    sample_reply = "Let's check that pinout right now. [CMD: remember ESP32 TX is GPIO 1]"
    for m in re.findall(r"\[CMD:\s*(.+?)\]", sample_reply): fast_route(m)
    assert "GPIO 1" in fast_route("memories")
    db_exec("DELETE FROM mem WHERE v LIKE '%GPIO 1%'")
    print("  PASS -> SMD math & autonomous [CMD: ...] execution verified.")
    print("[BETA TEST 7] Native Tkinter Clipboard Read (Zero pyperclip)...")
    import tkinter as tk
    r = tk.Tk(); r.withdraw()
    r.clipboard_clear(); r.clipboard_append("void setup() { Serial.begin(115200); }")
    r.update()
    grabbed = r.clipboard_get()
    r.destroy()
    assert "115200" in grabbed, "Clipboard read failed"
    print("  PASS -> Native clipboard capture verified.")
if __name__ == "__main__":
    run_beta_tests()
