#!/usr/bin/env python3
"""kipu-tools: servidor MCP de solo lectura sobre los Parquet de Kipu360.

Habla JSON-RPC 2.0 por stdin/stdout, sin dependencias fuera de duckdb.
Tools: run_sql, describe_table, search_catalog.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.getenv("KIPU_MCP_CONFIG", HERE / "config.json"))

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|copy|attach|detach|install|load|"
    r"export|import|pragma|set|call|vacuum|checkpoint|read_csv|read_csv_auto|"
    r"read_json|read_json_auto|read_parquet|read_text|glob)\b",
    re.IGNORECASE,
)


def log(*args):
    print(*args, file=sys.stderr, flush=True)


class Catalog:
    """Los Parquet del proyecto, expuestos como <dataset>.<tabla>."""

    def __init__(self, data_root: Path, max_rows: int, timeout_s: float):
        self.data_root = data_root
        self.max_rows = max_rows
        self.timeout_s = timeout_s
        self.tables = self._scan()
        self.conn = duckdb.connect(database=":memory:")
        self.conn.execute("SET threads TO 2")
        self._create_views()

    def _scan(self) -> dict[str, Path]:
        tables = {}
        for path in sorted(self.data_root.glob("*/data/*.parquet")):
            dataset = path.parent.parent.name
            name = re.sub(r"[^a-z0-9_]", "_", path.stem.lower())
            tables[f"{dataset}.{name}"] = path
        return tables

    def _create_views(self):
        for qualified, path in self.tables.items():
            dataset, table = qualified.split(".", 1)
            self.conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{dataset}"')
            literal = str(path).replace("'", "''")
            self.conn.execute(
                f'CREATE OR REPLACE VIEW "{dataset}"."{table}" AS '
                f"SELECT * FROM read_parquet('{literal}')"
            )

    def _guard(self, sql: str) -> str:
        text = sql.strip().rstrip(";").strip()
        if not text:
            raise ValueError("La consulta está vacía.")
        if not re.match(r"^(select|with)\b", text, re.IGNORECASE):
            raise ValueError("Solo se permiten SELECT y WITH.")
        without_strings = re.sub(r"'([^']|'')*'", "''", text)
        match = FORBIDDEN.search(without_strings)
        if match:
            raise ValueError(f"No se permite '{match.group(0)}' en una consulta.")
        if ";" in without_strings:
            raise ValueError("Una sola consulta por llamada.")
        return text

    def run_sql(self, sql: str) -> dict:
        text = self._guard(sql)
        wrapped = f"SELECT * FROM ({text}) AS _q LIMIT {self.max_rows + 1}"
        timer = threading.Timer(self.timeout_s, self.conn.interrupt)
        timer.start()
        try:
            cursor = self.conn.execute(wrapped)
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchall()
        except duckdb.InterruptException:
            raise ValueError(f"La consulta pasó de {self.timeout_s} segundos.")
        finally:
            timer.cancel()
        truncated = len(rows) > self.max_rows
        rows = rows[: self.max_rows]
        return {
            "columns": columns,
            "rows": [[str(v) if v is not None else None for v in row] for row in rows],
            "returned": len(rows),
            "truncated": truncated,
            "max_rows": self.max_rows,
        }

    def describe_table(self, table: str) -> dict:
        name = table.strip()
        if name not in self.tables:
            raise ValueError(f"No existe la tabla '{name}'. Usá search_catalog.")
        rows = self.conn.execute(f'DESCRIBE "{name.split(".")[0]}"."{name.split(".")[1]}"').fetchall()
        return {
            "table": name,
            "columns": [{"name": r[0], "type": r[1]} for r in rows],
        }

    def search_catalog(self, query: str, limit: int = 15) -> dict:
        needle = query.strip().lower()
        hits = []
        for qualified in self.tables:
            if needle in qualified:
                hits.append({"table": qualified, "reason": "nombre de tabla"})
        if not hits:
            for qualified in self.tables:
                dataset, table = qualified.split(".", 1)
                cols = self.conn.execute(
                    f'DESCRIBE "{dataset}"."{table}"'
                ).fetchall()
                for col in cols:
                    if needle in col[0].lower():
                        hits.append({"table": qualified, "reason": f"columna {col[0]}"})
                        break
        return {"query": query, "tables": hits[:limit], "total": len(hits)}


TOOL_SPECS = [
    {
        "name": "run_sql",
        "description": (
            "Ejecuta una consulta SQL de solo lectura sobre los Parquet del proyecto. "
            "Una sola consulta por llamada, máximo 25 filas."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "Consulta SELECT o WITH."}},
            "required": ["sql"],
        },
    },
    {
        "name": "describe_table",
        "description": "Devuelve las columnas y tipos de una tabla, por ejemplo sediments.results.",
        "inputSchema": {
            "type": "object",
            "properties": {"table": {"type": "string", "description": "Nombre <dataset>.<tabla>."}},
            "required": ["table"],
        },
    },
    {
        "name": "search_catalog",
        "description": "Busca tablas por nombre o por columna. Sirve para descubrir qué hay.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Texto a buscar."}},
            "required": ["query"],
        },
    },
]


class Server:
    def __init__(self, catalog: Catalog, name: str, version: str):
        self.catalog = catalog
        self.name = name
        self.version = version

    def handle(self, message: dict) -> dict | None:
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            requested = params.get("protocolVersion")
            return self._ok(msg_id, {
                "protocolVersion": requested if isinstance(requested, str) else "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.name, "version": self.version},
            })
        if method in ("notifications/initialized", "initialized"):
            return None
        if method == "ping":
            return self._ok(msg_id, {})
        if method == "tools/list":
            return self._ok(msg_id, {"tools": TOOL_SPECS})
        if method == "tools/call":
            return self._call(msg_id, params)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Método no soportado: {method}"},
        }

    def _call(self, msg_id, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "run_sql":
                result = self.catalog.run_sql(args.get("sql", ""))
            elif name == "describe_table":
                result = self.catalog.describe_table(args.get("table", ""))
            elif name == "search_catalog":
                result = self.catalog.search_catalog(args.get("query", ""))
            else:
                raise ValueError(f"Tool desconocida: {name}")
            return self._ok(msg_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "isError": False,
            })
        except Exception as error:
            return self._ok(msg_id, {
                "content": [{"type": "text", "text": f"Error: {error}"}],
                "isError": True,
            })

    @staticmethod
    def _ok(msg_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main():
    config = json.loads(CONFIG_PATH.read_text())
    raw_root = Path(os.getenv("KIPU_DATA_ROOT", config["data_root"]))
    data_root = raw_root if raw_root.is_absolute() else (HERE.parent / raw_root).resolve()
    if not data_root.exists():
        log(f"No existe data_root: {data_root}")
        sys.exit(1)

    catalog = Catalog(
        data_root=data_root,
        max_rows=int(config.get("max_rows", 25)),
        timeout_s=float(config.get("timeout_seconds", 5)),
    )
    server = Server(catalog, config.get("server_name", "kipu-tools"), config.get("version", "0.1.0"))
    log(f"kipu-tools listo: {len(catalog.tables)} tablas en {data_root}")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            log("mensaje inválido")
            continue
        response = server.handle(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
