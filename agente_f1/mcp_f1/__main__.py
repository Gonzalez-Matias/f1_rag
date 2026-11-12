"""python -m agente_f1.mcp_f1  ->  servidor MCP "f1-data" por stdio."""
from .servidor import mcp

if __name__ == "__main__":
    mcp.run()  # stdio
