#!/usr/bin/env python3
"""Cliente de prueba: levanta el servidor y hace el ciclo completo de MCP."""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON = sys.executable


def send(process, message):
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    return json.loads(line) if line else None


def call(process, msg_id, name, arguments):
    return send(process, {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })


def main():
    env = dict(os.environ)
    sibling = (HERE.parent / "environmental-data-explorer" / "data")
    if sibling.exists():
        env.setdefault("KIPU_DATA_ROOT", str(sibling))
    process = subprocess.Popen(
        [PYTHON, str(HERE / "server.py")],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        init = send(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2025-06-18",
                                         "capabilities": {},
                                         "clientInfo": {"name": "test", "version": "0"}}})
        print("initialize:", init["result"]["serverInfo"])

        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()

        tools = send(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in tools["result"]["tools"]]
        print("tools:", names)

        search = call(process, 3, "search_catalog", {"query": "results"})
        print("search_catalog:", search["result"]["content"][0]["text"][:180])

        describe = call(process, 4, "describe_table", {"table": "sediments.results"})
        print("describe_table:", describe["result"]["content"][0]["text"][:200])

        query = call(process, 5, "run_sql", {
            "sql": "SELECT * FROM sediments.results LIMIT 3"
        })
        print("run_sql:", query["result"]["content"][0]["text"][:300])

        bad = call(process, 6, "run_sql", {"sql": "DROP TABLE sediments.results"})
        print("guard:", bad["result"]["isError"], bad["result"]["content"][0]["text"][:120])
    finally:
        process.terminate()
        err = process.stderr.read()
        if err:
            print("stderr:", err.strip()[:300])


if __name__ == "__main__":
    main()
