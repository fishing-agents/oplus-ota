# SPDX-FileCopyrightText: 2026 Reza Jelveh
#
# SPDX-License-Identifier: Apache-2.0

"""Device catalog: bundled OPPO/OnePlus/realme JSON from OTA Pulse."""

import json
import re
from dataclasses import dataclass
from importlib import resources

# Display region -> (NV id, server). NV ids select the carrier build on the server.
REGIONS = {
    "GLO": ("NVA7", "GL"),
    "CN": ("NV97", "CN"),
    "VN": ("NV3C", "EU"),
    "IN": ("NV1B", "IN"),
    "EU": ("NV44", "EU"),
    "TR": ("NV51", "GL"),
    "RU": ("NV37", "EU"),
    "MEA": ("NVA6", "EU"),
    "SA": ("NV83", "EU"),
    "SG": ("NV2C", "EU"),
    "TH": ("NV39", "EU"),
    "LATAM": ("NV9A", "EU"),
    "BR": ("NV9E", "GL"),
    "TW": ("NV1A", "EU"),
    "MY": ("NV38", "EU"),
    "ID": ("NV33", "EU"),
    "KZ": ("NV5A", "EU"),
    "OCA": ("NVA5", "EU"),
    "PH": ("NV3D", "EU"),
    "LK": ("NV60", "EU"),
    "GENSHIN IMPACT": ("NV97", "CN"),
}
ALIASES = {"GL": "GLO", "GLOBAL": "GLO", "EEA": "EU"}


@dataclass(frozen=True)
class Variant:
    device: str
    group: str  # e.g. "Android 16"
    region: str  # display region, e.g. CN, EU
    model: str  # productModel
    product: str  # productName sent to the server
    letter: str  # firmware letter, H = Android 16 on most devices
    req_mode: str = "manual"

    @property
    def server(self) -> str:
        return REGIONS.get(self.region, ("", "EU"))[1]

    @property
    def nv(self) -> str:
        return REGIONS.get(self.region, ("", ""))[0]

    @property
    def android(self) -> int:
        m = re.search(r"\d+", self.group)
        return int(m.group()) if m else 16

    @property
    def base_version(self) -> str:
        """Lowest version of the group; the server answers with the latest full package."""
        return f"{self.model}{self.nv}_11.{self.letter}.01_0001_100001010000"


def _variants(dev: dict) -> list[Variant]:
    base = dev.get("variants") or []
    out = []
    for group, spec in dev.get("firmwareGroups", {}).items():
        if isinstance(spec, list):
            items, letter, mode = spec, None, None
        elif isinstance(spec, str):
            items, letter, mode = base, spec, None
        else:
            items, letter, mode = base, spec.get("versionLetter", "A"), spec.get("reqMode")
        for v in items:
            region = v.get("displayName") or v.get("region")
            model = v.get("productModel") or v.get("model") or v.get("productName")
            if not region or not model:
                continue
            out.append(
                Variant(
                    device=dev["name"],
                    group=group,
                    region=ALIASES.get(region.upper(), region.upper()),
                    model=model,
                    product=v.get("productName") or model,
                    letter=letter or v.get("versionLetter", "A"),
                    req_mode=mode or v.get("reqMode", "manual"),
                )
            )
    return out


def load() -> list[Variant]:
    pkg = resources.files("oplus_ota.catalog")
    return [v for f in sorted(pkg.iterdir()) if f.name.endswith(".json") for d in json.loads(f.read_text()) for v in _variants(d)]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def match(device: str, catalog: list[Variant] | None = None) -> list[Variant]:
    """Variants of a device given by name or model; exact matches win over substrings."""
    q = _norm(device)
    vs = catalog if catalog is not None else load()
    return [v for v in vs if q in (_norm(v.model), _norm(v.product), _norm(v.device))] or [v for v in vs if q in _norm(v.device)]


def find(device: str, region: str, group: str | None = None, catalog: list[Variant] | None = None) -> list[Variant]:
    """Variants matching a device, a region and optionally an Android group; newest group first."""
    r = ALIASES.get(region.upper(), region.upper())
    hits = [v for v in match(device, catalog) if v.region == r and (group is None or _norm(group) in _norm(v.group))]
    return sorted(hits, key=lambda v: v.android, reverse=True)
