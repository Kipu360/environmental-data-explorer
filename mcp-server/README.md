# kipu-tools

Servidor MCP de solo lectura sobre los Parquet de Kipu360.

Un proceso que habla JSON-RPC 2.0 por stdin/stdout. No necesita HTTP, ni auth, ni
nube. Sirve para probar el contrato con cualquier cliente MCP.

## Qué expone

| Tool | Qué hace |
|---|---|
| `run_sql` | una consulta SELECT o WITH, máximo 25 filas |
| `describe_table` | columnas y tipos de `<dataset>.<tabla>` |
| `search_catalog` | busca tablas por nombre o por columna |

Las tablas se ven como `sediments.results`, `soils.stations`, `flora.samples`.
Salen de los Parquet en `../environmental-data-explorer/data/*/data/*.parquet`.

Hoy son 51 tablas, leídas del disco. El paso siguiente es apuntar `data_root` a
las URLs de Hugging Face.

## Correrlo

```bash
/data/users/julio/.conda/envs/deep/bin/python server.py
```

Habla por stdin y stdout. Los mensajes de estado van a stderr, para no romper el
protocolo. Si querés probarlo sin cliente:

```bash
/data/users/julio/.conda/envs/deep/bin/python test_client.py
```

## Conectarlo a un cliente

Claude Desktop, `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "kipu-tools": {
      "command": "/data/users/julio/.conda/envs/deep/bin/python",
      "args": ["/data/users/julio/apps/kipu-360/mcp-server/server.py"]
    }
  }
}
```

opencode, `~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "kipu-tools": {
      "type": "local",
      "command": ["/data/users/julio/.conda/envs/deep/bin/python",
                  "/data/users/julio/apps/kipu-360/mcp-server/server.py"],
      "enabled": true
    }
  }
}
```

## Límites

- Solo `SELECT` y `WITH`. Una consulta por llamada.
- Bloquea escritura, `COPY`, `ATTACH`, `PRAGMA` y las funciones que leen archivos.
- 25 filas y 5 segundos por consulta.
- DuckDB en memoria, con una vista por tabla.

## Lo que falta

- Transporte HTTP para que lo use un agente remoto.
- Token y cuota por cliente.
- Apuntar a los Parquet de Hugging Face en vez del disco.
- Log de auditoría por consulta.
- Tests con las preguntas reales.
