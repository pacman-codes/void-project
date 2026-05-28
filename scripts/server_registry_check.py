from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.server_registry import (
    load_enabled_server_nodes,
    load_panel_credentials,
)


def main() -> None:
    servers = load_enabled_server_nodes()

    print(f"enabled_servers={len(servers)}")

    for server in servers:
        print()
        print(f"code={server.code}")
        print(f"display_name={server.display_name}")
        print(f"provider={server.provider}")
        print(f"endpoint={server.endpoint}")
        print(f"priority={server.priority}")
        print(f"panel={server.panel_origin}{server.panel_path}")
        print(f"inbound_id={server.inbound_id}")
        print(f"flow={server.flow}")
        print(f"fp={server.fingerprint}")
        print(f"sni={server.sni}")
        print(f"sid={server.short_id}")
        print(f"spx={server.spider_x}")
        print(f"direct_cidr={server.direct_cidr}")

        credentials = load_panel_credentials(server)
        print(f"secret_username_len={len(credentials.username)}")
        print(f"secret_password_len={len(credentials.password)}")


if __name__ == "__main__":
    main()
