# SPDX-FileCopyrightText: 2026 Reza Jelveh
#
# SPDX-License-Identifier: Apache-2.0

"""Server and region table: bundled servers.json, overridable per user."""

import json
import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


@dataclass(frozen=True)
class Server:
    url: str
    pubkey: str  # base64 DER RSA key the request key is encrypted with
    negotiation: str  # id of that key pair
    carrier: str  # nvCarrier fallback when no region NV id is given


def user_file() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "oplus-ota" / "servers.json"


def _load() -> dict:
    """Bundled table, with servers/regions from the user file merged over it entry by entry."""
    data = json.loads(resources.files(__package__).joinpath("servers.json").read_text())
    if (f := user_file()).is_file():
        user = json.loads(f.read_text())
        for section in ("servers", "regions"):
            for k, v in user.get(section, {}).items():
                data[section][k] = data[section].get(k, {}) | v
    return data


_DATA = _load()
SERVERS = {k: Server(**v) for k, v in _DATA["servers"].items()}
# Display region -> (NV id, server). NV ids select the carrier build on the server.
REGIONS = {k: (v["nv"], v["server"]) for k, v in _DATA["regions"].items()}
