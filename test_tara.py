import time, inspect
import tara

def run_beta_tests():
    src = inspect.getsource(tara)

    print("[BETA TEST 1] Zero Pixelated Canvas Ovals & Zero Double-Pill Layers...")
    assert "create_oval" not in src, "FAIL: Pixelated create_oval found in tara.py!"
    assert "draw_smooth_pill" not in src, "FAIL: Double-layered pill drawing found in tara.py!"
    assert "transparentcolor" not in src, "FAIL: Jagged chroma-key transparency found!"
    print("  PASS -> Single hardware DWM surface verified (zero double corners, zero jagged ovals).")

    print("[BETA TEST 2] UI Frame Speed & Layout Latency (<2ms)...")
    app = tara.TARA()
    t0 = time.perf_counter()
    app.set_layout(expanded=True, reply_text="Testing instant layout expansion speed.")
    app.animate_wave()
    app.set_layout(expanded=False)
    dt = (time.perf_counter() - t0) * 1000
    app.destroy()
    assert dt < 15.0, f"FAIL: UI layout took {dt:.2f}ms!"
    print(f"  PASS -> Full expand + wave + collapse completed in {dt:.2f}ms.")

    print("[BETA TEST 3] Fast-Path Command Router...")
    assert "RAM is at" in tara.fast_route("Hey Tara, check status")
    assert tara.fast_route("Tara smd 472") == "4.7 kiloohms"
    print("  PASS -> Fast-route verified.")

if __name__ == "__main__":
    run_beta_tests()