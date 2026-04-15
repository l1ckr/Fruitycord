# Fruitycord

______          _ _                           _ 
│  ___│        (_) │                         │ │
│ │_ _ __ _   _ _│ │_ _   _  ___ ___  _ __ __│ │
│  _│ '__│ │ │ │ │ __│ │ │ │╱ __╱ _ ╲│ '__╱ _` │
│ │ │ │  │ │_│ │ │ │_│ │_│ │ (_│ (_) │ │ │ (_│ │
╲_│ │_│   ╲__,_│_│╲__│╲__, │╲___╲___╱│_│  ╲__,_│
                       __╱ │                    
                      │___╱                     

                                     

Discord Rich Presence for **FL Studio 25** on **macOS**.

Shows the name of your current project in Discord automatically — no manual input needed.

## Features

- Detects FL Studio automatically (supports `FL Studio`, `OsxFL`, `FLStudio` process names)
- Reliably detects the current project name using three methods in priority order
- Auto-reconnects if Discord is closed and reopened
- Resets the elapsed timer when you switch projects
- Clears the presence when FL Studio is closed
- Exponential backoff for Discord reconnect attempts
- Zero external dependencies beyond `pypresence`

## Requirements

- macOS (tested on macOS 15)
- Python 3.8+
- FL Studio 25 (also works with FL Studio 2024 / 2025)
- Discord desktop app

## Installation & Use

```bash
pip install pypresence
```

Then clone or download this repo:

```bash
git clone https://github.com/l1ckr/fruitycord.git
cd fruitycord
```

Run:
```bash
python3 fruitycord.py
```

Make sure **"Display current activity as a status message"** is enabled in Discord  
(Settings → Privacy & Safety).

## Configuration

All initial data required is already placed in the code, however you are free to change it however you want or use your own discord app ID.
User-facing settings are at the top of `fruitycord.py`:

| Setting | Default | Description |
|---|---|---|
| `CLIENT_ID` | `"YOUR_APPLICATION_ID"` | Discord application ID |
| `UPDATE_INTERVAL` | `15` | Seconds between presence updates (min 15) |
| `DETAILS_TEXT` | `"Making music in FL Studio 25"` | Top line in the presence card |
| `UNKNOWN_PROJECT` | `"Unknown project"` | Text shown when no project is detected |
| `LARGE_IMAGE_KEY` | `"flstudio"` | Art asset key for the large icon |
| `SMALL_IMAGE_KEY` | `"apple"` | Art asset key for the small icon (set to `""` to disable) |

## How project detection works

FL Studio on macOS does **not** display the project name in the window title bar, and closes the file descriptor immediately after loading the project into memory. Standard approaches like reading the window title or checking open files with `lsof` are therefore unreliable on their own.

Fruitycord uses three methods in priority order:

| # | Method | How | When it works |
|---|---|---|---|
| 1 | **lsof** | Reads open file descriptors of the FL Studio process | For ~1 second right after a project opens |
| 2 | **AppleScript** | Reads the window title and `AXDocument` accessibility attribute | Rarely works for FL Studio, kept as a fallback |
| 3 | **Backup scan** | Finds the most recently modified file across all `Projects/*/Backup/` folders | Updates every ~10 min via FL Studio's autosave |

**The key insight behind method 3:** FL Studio writes autosaves exclusively into the *currently open* project's `Backup/` folder. The freshest autosave file across all projects always points to the active one — regardless of whether the main `.flp` has been manually saved.

Once a project name is detected it is cached in memory. The cache is cleared when FL Studio exits, so switching projects is reflected as soon as the next autosave is written (typically within 10 minutes, or immediately after Ctrl+S).

## Auto-start on login

Copy the plist template from the bottom of `fruitycord.py`, save it to  
`~/Library/LaunchAgents/com.fruitycord.plist`, then:

```bash
# Load (starts now and on every login)
launchctl load ~/Library/LaunchAgents/com.fruitycord.plist

# Check logs
tail -f /tmp/fruitycord.log

# Stop
launchctl unload ~/Library/LaunchAgents/com.fruitycord.plist
```

## TODO:

- [x] Project name detection;
- [ ] Project bpm, plugin, current window activity;
- [ ] Standalone client launcher and shortcut;
- [ ] Dock notification for ease of life;
- [ ] EP on spotify (optional)

## License

MIT
