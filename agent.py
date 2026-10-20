"""Local chess agent for the C++ Vice engine.

This program is intentionally local-only. It can play in the terminal against
you or run self-play games against the bundled UCI engine. It does not open a
browser, connect to Chess.com, automate an account, or submit online moves.

The small learning layer stores move outcomes in ``agent_state.json``. The
engine remains the primary chess player; learned statistics only influence a
small, controlled amount of local exploration during future games.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable


UCI_MOVE = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")
LEGAL_PREFIX = "info string legalmoves"


class UciEngine:
    """Small line-oriented UCI client for the local C++ engine."""

    def __init__(self, executable: Path, timeout: float = 30.0) -> None:
        self.executable = executable
        self.timeout = timeout
        self.process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None

    def start(self) -> None:
        if self.process is not None:
            self.close()
        if not self.executable.exists():
            raise FileNotFoundError(
                f"Chess engine not found: {self.executable}\n"
                "Build the C++ engine first with g++ or make."
            )

        self._lines = queue.Queue()
        self.process = subprocess.Popen(
            [str(self.executable)],
            cwd=str(self.executable.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert self.process.stdout is not None
        self._reader = threading.Thread(
            target=self._read_output,
            args=(self.process.stdout,),
            name="vice-uci-reader",
            daemon=True,
        )
        self._reader.start()

        self.command("uci")
        self._wait_for(lambda line: line == "uciok")
        self.command("setoption name Book value false")
        self.command("setoption name Threads value 1")
        self.command("isready")
        self._wait_for(lambda line: line == "readyok")

    def _read_output(self, output: Iterable[str]) -> None:
        for line in output:
            self._lines.put(line.rstrip("\r\n"))
        self._lines.put(None)

    def command(self, text: str) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("The chess engine is not running.")
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def _wait_for(self, predicate: Any) -> str:
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for the local chess engine.")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty as error:
                raise TimeoutError("Timed out waiting for the local chess engine.") from error
            if line is None:
                raise RuntimeError("The local chess engine exited unexpectedly.")
            if predicate(line):
                return line

    def position(self, moves: list[str]) -> None:
        validate_history(moves)
        command = "position startpos"
        if moves:
            command += " moves " + " ".join(moves)
        self.command(command)

    def legal_moves(self, moves: list[str]) -> tuple[list[str], bool]:
        self.position(moves)
        self.command("legalmoves")
        line = self._wait_for(lambda value: value.startswith(LEGAL_PREFIX))
        payload = line[len(LEGAL_PREFIX) :].strip()
        in_check = payload.endswith(" status check")
        payload = re.sub(r" status (?:check|safe)$", "", payload).strip()
        legal = payload.split() if payload else []
        return legal, in_check

    def best_move(self, moves: list[str], depth: int) -> str:
        self.position(moves)
        self.command(f"go depth {max(1, min(depth, 20))}")
        line = self._wait_for(lambda value: value.startswith("bestmove "))
        move = line.split()[1]
        # The bundled engine closes its UCI output after a completed search
        # when driven through a Windows pipe. Start a clean session before the
        # next query so local self-play remains reliable.
        self.close(graceful=False)
        self.start()
        return move

    def close(self, graceful: bool = True) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        try:
            if process.poll() is None and graceful and process.stdin is not None:
                try:
                    process.stdin.write("quit\n")
                    process.stdin.flush()
                except OSError:
                    pass
            if process.poll() is None and graceful:
                try:
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if process.poll() is None:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def __enter__(self) -> "UciEngine":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class LearningStore:
    """Persistent, local-only move-outcome statistics."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {
            "version": 1,
            "games": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "self_play_decisive": 0,
            "positions": {},
        }
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                loaded = json.load(stream)
            if loaded.get("version") == 1 and isinstance(loaded.get("positions"), dict):
                self.data.update(loaded)
        except (OSError, ValueError, AttributeError):
            print(f"Warning: ignoring invalid learning state: {self.path}", file=sys.stderr)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=self.path.stem + ".",
            suffix=".tmp",
            dir=self.path.parent,
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(self.data, stream, indent=2, sort_keys=True)
                stream.write("\n")
            Path(temporary_name).replace(self.path)
        except BaseException:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass
            raise

    @staticmethod
    def key(moves: list[str]) -> str:
        return " ".join(moves) if moves else "startpos"

    def record_game(
        self,
        transcript: list[tuple[str, str, str]],
        winner: str | None,
        agent_side: str | None = None,
    ) -> None:
        self.data["games"] += 1
        if winner == "draw" or winner is None:
            self.data["draws"] += 1
        elif agent_side is None:
            self.data["self_play_decisive"] += 1
        elif agent_side == winner:
            self.data["wins"] += 1
        else:
            self.data["losses"] += 1

        positions: dict[str, Any] = self.data["positions"]
        for position, side, move in transcript:
            stats = positions.setdefault(position, {}).setdefault(
                move, {"visits": 0, "score": 0}
            )
            stats["visits"] += 1
            if winner in (None, "draw"):
                continue
            value = 1 if side == winner else -1
            stats["score"] += value


class LocalAgent:
    """Engine-backed local player with modest outcome-based exploration."""

    def __init__(
        self,
        engine: UciEngine,
        store: LearningStore,
        rng: random.Random,
        exploration: float = 0.08,
    ) -> None:
        self.engine = engine
        self.store = store
        self.rng = rng
        self.exploration = exploration

    def choose_move(self, moves: list[str], legal: list[str], depth: int) -> str:
        if not legal:
            raise ValueError("Cannot choose a move from an empty move list.")

        position = self.store.data["positions"].get(self.store.key(moves), {})
        learned: list[tuple[float, int, str]] = []
        for move in legal:
            stats = position.get(move, {})
            visits = int(stats.get("visits", 0))
            score = int(stats.get("score", 0))
            if visits:
                learned.append((score / visits, visits, move))

        # Explore occasionally so self-play can collect local experience.
        if self.rng.random() < self.exploration:
            return self.rng.choice(legal)

        engine_move = self.engine.best_move(moves, depth)
        if engine_move not in legal:
            return self.rng.choice(legal)

        # A repeatedly successful local move can be selected occasionally, but
        # the tested engine move remains the normal/default choice.
        if learned:
            learned.sort(reverse=True)
            value, visits, move = learned[0]
            if move != engine_move and visits >= 3 and value >= 0.67 and self.rng.random() < 0.20:
                return move
        return engine_move


def validate_history(moves: list[str]) -> None:
    if len(moves) > 512 or any(UCI_MOVE.fullmatch(move) is None for move in moves):
        raise ValueError("Move history contains an invalid UCI move.")


def side_name(ply: int) -> str:
    return "white" if ply % 2 == 0 else "black"


def winner_from_terminal(side_to_move: str, in_check: bool) -> str:
    if not in_check:
        return "draw"
    return "black" if side_to_move == "white" else "white"


def run_self_play(
    agent: LocalAgent,
    store: LearningStore,
    games: int,
    depth: int,
    max_plies: int,
) -> None:
    for number in range(1, games + 1):
        moves: list[str] = []
        transcript: list[tuple[str, str, str]] = []
        winner: str | None = None

        for _ in range(max_plies):
            legal, in_check = agent.engine.legal_moves(moves)
            if not legal:
                winner = winner_from_terminal(side_name(len(moves)), in_check)
                break

            side = side_name(len(moves))
            position = store.key(moves)
            move = agent.choose_move(moves, legal, depth)
            if move not in legal:
                raise RuntimeError(f"Engine selected an illegal move: {move}")
            transcript.append((position, side, move))
            moves.append(move)
        else:
            winner = "draw"

        store.record_game(transcript, winner, agent_side=None)
        store.save()
        print(
            f"game {number}/{games}: {winner}; plies={len(moves)}; "
            f"stored_games={store.data['games']}"
        )


def run_terminal_game(
    agent: LocalAgent,
    store: LearningStore,
    human_side: str,
    depth: int,
    max_plies: int,
) -> None:
    engine_side = "black" if human_side == "white" else "white"
    moves: list[str] = []
    agent_transcript: list[tuple[str, str, str]] = []

    for _ in range(max_plies):
        legal, in_check = agent.engine.legal_moves(moves)
        side = side_name(len(moves))
        if not legal:
            winner = winner_from_terminal(side, in_check)
            print("checkmate" if in_check else "stalemate", f"({winner})")
            store.record_game(agent_transcript, winner, agent_side=engine_side)
            store.save()
            return

        print(f"\n{side} to move. Legal moves: {' '.join(legal)}")
        if side == human_side:
            while True:
                move = input("Your move (UCI, or quit): ").strip().lower()
                if move in {"quit", "exit"}:
                    print("Game ended without recording a result.")
                    return
                if move in legal:
                    break
                print("That is not legal. Enter one of the listed UCI moves.")
        else:
            position = store.key(moves)
            move = agent.choose_move(moves, legal, depth)
            agent_transcript.append((position, side, move))
            print(f"Local engine move: {move}")
        moves.append(move)

    print(f"Move limit ({max_plies} plies) reached; recording a draw.")
    store.record_game(agent_transcript, "draw", agent_side=engine_side)
    store.save()


def show_status(store: LearningStore) -> None:
    positions: dict[str, Any] = store.data["positions"]
    learned_moves = sum(len(value) for value in positions.values())
    print(f"learning state: {store.path}")
    print(f"games: {store.data['games']}")
    print(f"wins/losses/draws: {store.data['wins']}/{store.data['losses']}/{store.data['draws']}")
    print(f"decisive self-play games: {store.data.get('self_play_decisive', 0)}")
    print(f"positions: {len(positions)}")
    print(f"learned moves: {learned_moves}")


def default_engine_path() -> Path:
    directory = Path(__file__).resolve().parent
    executable = "vice12_smp.exe" if os.name == "nt" else "vice12_smp"
    return directory / executable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local-only self-improving chess agent for the bundled C++ engine."
    )
    parser.add_argument("--engine", type=Path, default=default_engine_path())
    parser.add_argument("--state", type=Path, default=Path(__file__).with_name("agent_state.json"))
    parser.add_argument("--seed", type=int, default=None, help="Seed local exploration for repeatable runs.")
    parser.add_argument("--exploration", type=float, default=0.08)

    commands = parser.add_subparsers(dest="command", required=True)

    self_play = commands.add_parser("self-play", help="Run local engine-vs-engine training games.")
    self_play.add_argument("--games", type=int, default=1)
    self_play.add_argument("--depth", type=int, default=3)
    self_play.add_argument("--max-plies", type=int, default=160)

    play = commands.add_parser("play", help="Play a local terminal game against the engine.")
    play.add_argument("--side", choices=("white", "black"), default="white")
    play.add_argument("--depth", type=int, default=5)
    play.add_argument("--max-plies", type=int, default=240)

    commands.add_parser("status", help="Show the local learning-state summary.")
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    if not 0 <= arguments.exploration <= 1:
        parser.error("--exploration must be between 0 and 1")

    if arguments.command == "self-play" and (arguments.games < 1 or arguments.max_plies < 1):
        parser.error("self-play requires positive --games and --max-plies")
    if arguments.command == "play" and arguments.max_plies < 1:
        parser.error("play requires a positive --max-plies")

    store = LearningStore(arguments.state)
    if arguments.command == "status":
        show_status(store)
        return 0

    rng = random.Random(arguments.seed)
    with UciEngine(arguments.engine) as engine:
        agent = LocalAgent(engine, store, rng, arguments.exploration)
        if arguments.command == "self-play":
            run_self_play(agent, store, arguments.games, arguments.depth, arguments.max_plies)
        else:
            run_terminal_game(agent, store, arguments.side, arguments.depth, arguments.max_plies)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, TimeoutError, ValueError) as error:
        print(f"agent error: {error}", file=sys.stderr)
        raise SystemExit(1)
