# Kota Kow (`KotaKow`)

A lightweight, polished Windows 11 desktop voice-typing application built in Python (PySide6) with clean **Bengali Unicode + English** dictation, a Wispr Flow-style non-focus-stealing floating recording pill, and a strict **BYOK (Bring Your Own Key)** dual AI engine.

---

## Highlights

- **Global Hotkey & Hands-Free Lock (Windows 11 Safe):**
  - Default hotkey: **`Left Ctrl + Left Win`** (fully customizable in Settings).
  - Uses a low-level Windows keyboard hook (`WH_KEYBOARD_LL`) that suppresses the Windows Start Menu during hotkey chords while keeping normal single `Win` key usage completely intact.
  - **Push-to-Talk:** Hold the hotkey (`>300ms`) to record; release to transcribe & auto-paste.
  - **Hands-Free Lock:** Double-tap the hotkey (`≤400ms`) to lock recording ON. Press the hotkey once again or click **`✓`** on the floating pill to stop & paste.
  - **Cancel Anytime:** Press **`Esc`** or click **`✕`** on the floating pill to discard immediately.
- **Minimal Non-Focus-Stealing Floating Pill:**
  - Appears bottom-center just above the Windows taskbar only while recording or processing.
  - Exact 3-element layout: subtle **`✕`** cancel button, smooth live audio waveform (transitions to minimal pulsing loader while processing), and solid **`✓`** confirm button.
  - Uses `WindowDoesNotAcceptFocus`, `WA_ShowWithoutActivating`, Win32 `WS_EX_NOACTIVATE`, and `WM_MOUSEACTIVATE` so active cursors in Chrome, WhatsApp, VS Code, or Notepad never lose focus.
  - In-memory synthesized start/stop/cancel chimes (zero external audio files).
- **Zero-FFmpeg, Zero-Disk Audio Capture:**
  - Captures 16kHz 16-bit mono WAV strictly in RAM (`sounddevice` + `numpy` + `wave`), up to 5 minutes per dictation. Audio is never saved to disk.
- **Dual AI Engine (Strict BYOK):**
  - All keys and settings are stored locally in `%APPDATA%\KotaKow\config.json` — zero hardcoded keys, safe to share `KotaKow.exe` with anyone.
  - **Google Gemini API (Primary):** Direct inline audio-to-text with dynamic model discovery (*Fetch Models / Test*) prioritizing the fastest available Flash-Lite / Flash audio-capable model.
  - **Groq API (Optional Auto-Backup):** `whisper-large-v3` speech-to-text + selectable Groq chat cleanup model.
  - **Smart Routing:** Works with Gemini only, Groq only, or both (automatically falling back to Groq on HTTP 429 / quota errors).
- **3 Language Modes (Settings Only):**
  - **Auto (Default):** Clean Bengali Unicode + English code-switching, intelligent punctuation (`।`, `,`, `?`, `:`), filler removal, self-corrections, and optional Smart Formatting (lists + paragraphs).
  - **বাংলা (Bengali Only):** Strictly Bengali Unicode script (e.g., `Chrome` → `ক্রোম`, `Option` → `অপশন`).
  - **English (English Only):** Strictly clean grammatical English.
- **Modern 4-Tab UI + System Tray:**
  - **Top-Right Theme Switcher:** Light, Dark, or System (auto-follows Windows 11 theme) + 5 Accent Color presets (Teal, Blue, Indigo, Emerald, Coral).
  - **Dashboard:** Total Words & Average WPM, Daily Streak & 90-Day Activity Heatmap, Desktop App Usage breakdown, Today's API Usage (Gemini & Groq).
  - **History:** Local SQLite with lazy-loading collapsible Month → Date dropdowns, search, 1-click Copy, single Delete, 90-day rolling auto-purge, and a full **Manage History** menu.
  - **Dictionary:** Custom names, brands, and technical terms automatically injected into every AI prompt.
  - **Settings:** Masked API keys, model fetchers, language mode, hotkey recorder, microphone picker, sound & volume controls, Smart Formatting, Accent picker, Start with Windows, and editable advanced prompt.

---

## Automatic Portable `.exe` Build via GitHub Actions

No local Python setup is required to produce a standalone shareable Windows executable!

1. Create a new GitHub repository and push this project folder to the `main` (or `master`) branch:
   ```bash
   git init
   git add .
   git commit -m "Initial Kota Kow release"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<your-repo>.git
   git push -u origin main
   ```
2. Open your repository on GitHub and click the **Actions** tab.
3. Wait for **Build KotaKow Portable Windows EXE** to finish (usually ~2–3 minutes on `windows-latest`).
4. Click the completed workflow run and download **`KotaKow-Windows-x64`** under **Artifacts** — inside is your single portable **`KotaKow.exe`** ready to run or share!
5. *(Optional)* Pushing a version tag such as `git tag v1.0.0 && git push origin v1.0.0` automatically creates a GitHub Release with `KotaKow.exe` attached.

---

## Project Structure

```text
├── .github/workflows/build.yml   # Automated Windows --onefile --noconsole build
├── main.py                       # Entry point (single-instance IPC, tray, theme watcher)
├── requirements.txt              # Python dependencies
├── build_exe.bat                 # Optional local Windows PyInstaller build script
├── scripts/
│   └── generate_icon.py          # Pure-stdlib multi-resolution .ico generator for CI
└── kotakow/
    ├── __init__.py               # App name & version constants
    ├── config.py                 # %APPDATA%\KotaKow\config.json & Windows startup registry
    ├── database.py               # SQLite history, 90-day purge, analytics, dictionary
    ├── assets.py                 # Procedural QIcon & .ico generator
    ├── chimes.py                 # In-memory numpy synthesized chimes
    ├── audio_capture.py          # 16kHz 16-bit mono in-memory WAV capture
    ├── hotkey_hook.py            # Windows WH_KEYBOARD_LL hook (Start-Menu safe)
    ├── autopaste.py              # Active app detection + UTF-16 clipboard & SendInput Ctrl+V
    ├── ai_engine.py              # Dual BYOK engine (Gemini primary + Groq backup)
    ├── controller.py             # Push-to-Talk / Hands-Free state machine
    └── ui/
        ├── theme.py              # Light/Dark/System + 5 accents + Bengali font stack
        ├── floating_pill.py      # Non-focus-stealing minimal bottom-center capsule
        ├── tray.py               # System Tray icon & menu
        ├── main_window.py        # Sidebar navigation, theme switcher, onboarding
        └── tabs/
            ├── dashboard_tab.py  # 4 metric cards + 90-day activity heatmap
            ├── history_tab.py    # Lazy-loading Month/Date accordions + Manage History
            ├── dictionary_tab.py # Custom vocabulary manager
            └── settings_tab.py   # Full BYOK & audio/hotkey/appearance settings
```

---

## Running Locally from Source (Optional)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Or double-click `build_exe.bat` on Windows to compile `dist\KotaKow.exe` locally.
