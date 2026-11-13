# T.A.R.A. (v2 — OpenJarvis Architecture)

A single-file (~160 lines), offline-first personal AI partner for Windows. Built on native `tkinter`, `urllib`, `sqlite3`, `faster-whisper` (INT8), and Ollama (`tara-core`).

## Footprint
- **Idle RAM:** ~28 MB
- **Source Code:** 1 file (`tara.py`), zero external UI/HTTP wrappers

## Hotkeys & Commands
- `Alt + Space`: Toggle top-center pill
- `Alt + V`: Continuous hands-free voice partner mode (auto-VAD turn-taking)
- `Alt + Q`: Grab highlighted text/code from any active window (`clip:`)
- **Fast-Paths (<10ms):** `status`, `free`, `ports`, `ser COMx CMD`, `smd 472`, `remember ...`, `memories`, `open ...`, `yt ...`, `google ...`, `quit`
- **Cloud Fallback:** Prefix with `cloud:` for Gemini 2.5 Flash