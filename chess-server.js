const http = require("http");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const readline = require("readline");

const HOST = "127.0.0.1";
const PORT = Number(process.env.PORT || 3000);
const ENGINE = process.env.VICE_ENGINE ||
  path.join(__dirname, process.platform === "win32" ? "vice12_smp.exe" : "vice12_smp");
const MOVE_PATTERN = /^[a-h][1-8][a-h][1-8][qrbn]?$/;

function readRequest(request) {
  return new Promise((resolve, reject) => {
    let body = "";
    request.setEncoding("utf8");
    request.on("data", chunk => {
      body += chunk;
      if (body.length > 100_000) {
        reject(new Error("Request is too large."));
        request.destroy();
      }
    });
    request.on("end", () => {
      try {
        resolve(JSON.parse(body));
      } catch {
        reject(new Error("Request body must be valid JSON."));
      }
    });
    request.on("error", reject);
  });
}

function validateMoves(moves) {
  if (!Array.isArray(moves) || moves.length > 512 ||
      moves.some(move => typeof move !== "string" || !MOVE_PATTERN.test(move))) {
    throw new Error("Moves must be an array of UCI moves.");
  }
}

function runEngine(moves, { play = false, depth = 8 } = {}) {
  return new Promise((resolve, reject) => {
    const engine = spawn(ENGINE, [], { cwd: __dirname, windowsHide: true });
    const output = readline.createInterface({ input: engine.stdout });
    let stderr = "";
    let settled = false;
    let stage = "uci";
    let legalMoves = [];
    let isCheck = false;
    let bestMove = "";
    let timer;

    const fail = error => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      output.close();
      engine.kill();
      reject(error);
    };

    const finish = result => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      engine.stdin.write("quit\n");
      output.close();
      resolve(result);
    };

    const send = command => engine.stdin.write(command + "\n");
    const setPosition = history => send(`position startpos${history.length ? ` moves ${history.join(" ")}` : ""}`);

    timer = setTimeout(() => fail(new Error("Chess engine timed out.")), 30_000);

    output.on("line", line => {
      if (stage === "uci" && line === "uciok") {
        send("setoption name Book value false");
        send("setoption name Threads value 1");
        setPosition(play ? moves.slice(0, -1) : moves);
        stage = play ? "player-legal" : "current-legal";
        send("legalmoves");
        return;
      }

      if ((stage === "player-legal" || stage === "current-legal" || stage === "terminal-legal") &&
          line.startsWith("info string legalmoves")) {
        const status = line.endsWith(" status check") ? "check" : "safe";
        const text = line.replace(/ status (?:check|safe)$/, "").slice("info string legalmoves".length).trim();
        legalMoves = text ? text.split(/\s+/) : [];
        isCheck = status === "check";

        if (stage === "player-legal") {
          if (!legalMoves.includes(moves[moves.length - 1])) {
            fail(Object.assign(new Error("That move is not legal in this position."), { statusCode: 400 }));
            return;
          }
          setPosition(moves);
          stage = "bestmove";
          send(`go depth ${depth}`);
          return;
        }

        if (stage === "terminal-legal") {
          finish({ bestMove: "0000", legalMoves, isCheck });
          return;
        }

        finish(play ? { bestMove, legalMoves, isCheck } : { legalMoves, isCheck });
        return;
      }

      if (stage === "bestmove" && line.startsWith("bestmove ")) {
        bestMove = line.split(/\s+/)[1];
        if (bestMove === "0000") {
          setPosition(moves);
          stage = "terminal-legal";
          send("legalmoves");
          return;
        }
        setPosition([...moves, bestMove]);
        stage = "current-legal";
        send("legalmoves");
      }
    });

    engine.stderr.on("data", chunk => {
      stderr += chunk.toString();
      if (stderr.length > 4000) stderr = stderr.slice(-4000);
    });
    engine.on("error", error => fail(new Error(`Could not start chess engine at "${ENGINE}": ${error.message}`)));
    engine.on("close", code => {
      if (!settled) fail(new Error(`Chess engine exited unexpectedly (${code}). ${stderr.trim()}`));
    });
    engine.stdin.on("error", error => fail(new Error(`Could not communicate with chess engine: ${error.message}`)));
    send("uci");
  });
}

function sendJson(response, status, data) {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "Access-Control-Allow-Origin": `http://${HOST}:${PORT}`
  });
  response.end(JSON.stringify(data));
}

const server = http.createServer(async (request, response) => {
  if (request.method === "GET" && request.url === "/") {
    fs.createReadStream(path.join(__dirname, "chess-game.html"))
      .on("error", () => {
        response.writeHead(500);
        response.end("Could not load chess-game.html.");
      })
      .pipe(response);
    return;
  }

  if (request.method === "POST" && (request.url === "/api/legal" || request.url === "/api/play")) {
    try {
      const body = await readRequest(request);
      validateMoves(body.moves);
      const isPlay = request.url === "/api/play";
      if (isPlay && body.moves.length === 0) {
        throw Object.assign(new Error("Submit a move to play."), { statusCode: 400 });
      }
      const depth = Number.isInteger(body.depth) ? Math.max(1, Math.min(body.depth, 12)) : 8;
      const result = await runEngine(body.moves, { play: isPlay, depth });
      sendJson(response, 200, result);
    } catch (error) {
      sendJson(response, error.statusCode || 500, { error: error.message });
    }
    return;
  }

  sendJson(response, 404, { error: "Not found." });
});

server.listen(PORT, HOST, () => {
  console.log(`Chess game available at http://${HOST}:${PORT}`);
  console.log(`Using engine: ${ENGINE}`);
});
