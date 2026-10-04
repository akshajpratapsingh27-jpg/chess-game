# Chess Game

A browser-based chess game powered by the Vice chess engine written in C. Play
as White against the engine, with legal move highlighting and engine replies.

## Run on Windows

1. Install GCC (MinGW) and Node.js, and make sure both `gcc` and `node` are on
   your `PATH`.
2. Double-click `run-chess-game.bat` in this folder.
3. Open <http://127.0.0.1:3000> in a browser.
4. Keep the command window open while playing. Press Ctrl+C there to stop.

The launcher compiles the C sources into `vice12_smp.exe` before starting the
local Node.js bridge. The engine uses the included `performance.bin` Polyglot
opening book when started normally; the web game disables book moves so engine
replies are calculated for the current game.

## Files

- `chess-game.html` — browser board and game interface.
- `chess-server.js` — local HTTP server and UCI bridge to the C engine.
- `run-chess-game.bat` — Windows build-and-run launcher.
- `*.c`, `*.h`, `makefile` — chess engine source and build files.
- `performance.bin` — optional Polyglot opening book for the standalone engine.
- `BluePaperBG.png`, `styles.css` — included visual assets.

The C engine can also be run directly as a UCI engine in a compatible chess GUI.
