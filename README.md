# mcp-server-tidb

MCP server implementation for TiDB (serverless) database.

## Prerequisites

- uv (Python package installer)

## Installation

```
# Clone the repository
git clone https://github.com/c4pt0r/mcp-server-tidb
cd mcp-server-tidb

# Install the package and dependencies using uv
uv venv
uv pip install -e .
```

## Configuration

Go [tidbcloud.com](tidbcloud.com) to create a free TiDB database cluster

Configuration can be provided through environment variables, or using .env:
- `TIDB_HOST` - TiDB host address, e.g. 'gateway01.us-east-1.prod.aws.tidbcloud.com'
- `TIDB_PORT` - TiDB port (default: 4000)
- `TIDB_USERNAME` - Database username, e.g.  'xxxxxxxxxx.\<username\>'
- `TIDB_PASSWORD` - Database password
- `TIDB_DATABASE` - Database name, default is test

## Run with Claude Desktop

Config Claude Desktop, [HOWTO](https://modelcontextprotocol.io/quickstart/user)

`claude_desktop_config.json`:

```
{
  "mcpServers": {
      "tidb": {
          "command": "uv",
          "args": [
              "--directory",
              "/path/to/mcp-server-tidb",
              "run",
              "src/main.py"
          ]
      }
  }
}
```


If you're running mcp-server-tidb in WSL, the `claude_desktop_config.json` should look like this:

```
{
	"mcpServers": {
		"tool-with-env-vars": {
			"command": "wsl.exe",
			"args": [
				"bash",
				"-c",
				"/path/to/uv --directory /path/to/mcp-server-tidb run python /path/to/mcp-server-tidb/src/main.py"
			]
		}
	}
}

