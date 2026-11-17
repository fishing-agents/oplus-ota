# SPDX-FileCopyrightText: 2026 Reza Jelveh
#
# SPDX-License-Identifier: Apache-2.0

"""oplus-ota CLI entry point."""

import dataclasses
import json
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
import questionary
import typer
from rich.console import Console
from rich.table import Table

from oplus_ota import catalog
from oplus_ota.protocol import DOWNLOAD_HEADERS, OtaError, Package, query

app = typer.Typer(help="Query and download OPPO/OnePlus/realme OTA packages", no_args_is_help=True, rich_markup_mode="rich")
out, err = Console(highlight=False), Console(stderr=True, highlight=False)

Device = Annotated[str | None, typer.Argument(help="Device name or model, e.g. 'OnePlus 11', op11, PHB110 (omit to pick)")]
Region = Annotated[str | None, typer.Option("-r", "--region", help="CN, EU, IN, GLO, ... (omit to pick; see [bold]regions[/])")]
Android = Annotated[str | None, typer.Option("-a", "--android", help="Firmware group, e.g. 16 (default: newest)")]
From = Annotated[str | None, typer.Option("--from", help="Ask as this OTA version, e.g. PHB110_11.H.13_3130_202607172124")]
Beta = Annotated[bool, typer.Option("--beta", help="Ask for beta builds")]
Json = Annotated[bool, typer.Option("--json", help="Print JSON")]

SHORT = {"op": "oneplus"}  # op11 -> oneplus11
SERVER_STYLE = {"CN": "red", "EU": "blue", "IN": "yellow", "GL": "green"}


@app.command()
def devices(search: Annotated[str, typer.Argument(help="Filter by name or model")] = ""):
    """List known devices with their regions and models."""
    rows: dict[str, dict[str, str]] = {}
    for v in catalog.match(_expand(search)) if search else catalog.load():
        rows.setdefault(v.device, {})[v.region] = v.model
    if not rows:
        _fail(f"no device matches '{search}'")
    t = _table("Device", "Regions")
    for name in sorted(rows):
        t.add_row(f"[bold]{name}[/]", "  ".join(f"{_region(r)}:{m}" for r, m in sorted(rows[name].items())))
    out.print(t)


@app.command()
def regions():
    """List regions, their NV ids and servers."""
    t = _table("Region", "NV id", "Server")
    for name, (nv, srv) in catalog.REGIONS.items():
        t.add_row(_region(name), nv, f"[{SERVER_STYLE[srv]}]{srv}[/]")
    out.print(t)


@app.command("query")
def query_cmd(
    device: Device = None,
    region: Region = None,
    android: Android = None,
    from_version: From = None,
    beta: Beta = False,
    as_json: Json = False,
):
    """Show the latest full package: version, size, MD5, link."""
    _show(_query(device, region, android, from_version, beta), as_json)


@app.command()
def url(device: Device = None, region: Region = None, android: Android = None, from_version: From = None):
    """Print only the signed download link (for scripts)."""
    print(_query(device, region, android, from_version, False).url)


@app.command()
def download(
    device: Device = None,
    region: Region = None,
    android: Android = None,
    from_version: From = None,
    beta: Beta = False,
    output_dir: Annotated[Path, typer.Option("-o", "--output-dir", help="Download directory")] = Path("."),
    connections: Annotated[int, typer.Option("-x", "--connections", help="aria2c connections", min=1, max=16)] = 16,
    dry_run: Annotated[bool, typer.Option("-n", "--dry-run", help="Print the aria2c command only")] = False,
    yes: Annotated[bool, typer.Option("-y", "--yes", help="Don't ask before downloading")] = False,
):
    """Download the latest full package with aria2c (resumes, checks MD5)."""
    pkg = _query(device, region, android, from_version, beta)
    _show(pkg, False)
    cmd = _aria2c(pkg, output_dir, connections)
    if dry_run:
        print(" ".join(f"'{c}'" if any(ch in c for ch in " &|") else c for c in cmd))
        return
    if not shutil.which("aria2c"):
        _fail("aria2c not found")
    free = shutil.disk_usage(output_dir if output_dir.exists() else Path.cwd()).free
    if free < pkg.size:
        _fail(f"{_size(free)} free in {output_dir}, need {_size(pkg.size)}")
    if not yes and not typer.confirm(f"Download {_size(pkg.size)} to {output_dir}/{cmd[cmd.index('-o') + 1]}?", default=True):
        raise typer.Exit(1)
    rc = subprocess.call(cmd)
    (out if rc == 0 else err).print("[green]✓ done, MD5 verified[/]" if rc == 0 else f"[red]✗ aria2c exited {rc}[/]")
    raise typer.Exit(rc)


@app.command()
def resolve(link: Annotated[str, typer.Argument(help="downloadCheck link")]):
    """Check a downloadCheck link is still valid and show the CDN URL."""
    with _status("Resolving"), httpx.Client(headers=DOWNLOAD_HEADERS, follow_redirects=True, timeout=30) as c:
        r = c.get(link, headers={"Range": "bytes=0-0"})
    if r.status_code not in (200, 206) or "json" in r.headers.get("content-type", ""):
        _fail(f"link invalid or expired (HTTP {r.status_code}): {r.text[:200]}")
    total = int(r.headers.get("content-range", "").rpartition("/")[2] or r.headers.get("content-length") or 0)
    out.print(f"[green]✓ valid[/], {_size(total)}\n[dim]{r.url}[/]")


@app.command()
def phone(beta: Beta = False, as_json: Json = False):
    """Check the phone connected via adb for an update to its current build."""
    ota, android = _adb_prop("ro.build.version.ota"), _adb_prop("ro.build.version.release")
    if not ota:
        _fail("no phone over adb, or ro.build.version.ota missing")
    prefix = ota.split("_")[0]
    region = next((r for r, (nv, _) in catalog.REGIONS.items() if prefix.endswith(nv)), None)
    model = prefix.removesuffix(catalog.REGIONS[region][0]) if region else prefix
    hits = catalog.find(model, region) if region else [v for r in ("CN", "IN", "GLO") for v in catalog.find(model, r)][:1]
    if not hits:
        _fail(f"{model} not in catalog; try: query <model> -r <region> --from {ota}")
    err.print(f"[dim]Phone:[/] {ota} (Android {android})")
    _show(_ask(hits[0], ota, beta, int(android or hits[0].android)), as_json)


def _expand(s: str) -> str:
    low = s.lower()
    for k, v in SHORT.items():
        if low.startswith(k) and low[len(k) :].isdigit():
            return v + low[len(k) :]
    return s


def _query(device: str | None, region: str | None, android: str | None, from_version: str | None, beta: bool) -> Package:
    v = _pick(device, region, android)
    return _ask(v, from_version or v.base_version, beta, v.android)


def _pick(device: str | None, region: str | None, android: str | None) -> catalog.Variant:
    """Resolve device/region from arguments, asking interactively for whatever is missing or ambiguous."""
    tty = sys.stdin.isatty() and sys.stderr.isatty()
    if not device:
        if not tty:
            _fail("missing DEVICE (no terminal to ask on)")
        device = _choose("Device", sorted({v.device for v in catalog.load()}))
    variants = [v for v in catalog.match(_expand(device)) if android is None or catalog._norm(android) in catalog._norm(v.group)]
    names = sorted({v.device for v in variants})
    if len(names) > 1 and tty:
        device = _choose("Device", names)
        variants = [v for v in variants if v.device == device]
    avail = sorted({v.region for v in variants})
    if not avail:
        _fail(f"no device matches '{device}'; see 'devices'")
    if region is None:
        region = avail[0] if len(avail) == 1 else _choose("Region", avail) if tty else "CN"
    hits = catalog.find(_expand(device), region, android, variants)
    if not hits:
        _fail(f"no {device} variant for region {region}; available: {', '.join(avail)}")
    return hits[0]


def _choose(what: str, choices: list[str]) -> str:
    """Arrow-key list, type to filter when long. Ctrl-C aborts."""
    long = len(choices) > 8
    answer = questionary.select(
        f"{what}:", choices, use_search_filter=long, use_jk_keys=not long, instruction="(type to filter)" if long else " "
    ).ask()
    if answer is None:
        raise typer.Exit(130)
    return answer


def _ask(v: catalog.Variant, ota: str, beta: bool, android: int) -> Package:
    err.print(f"[dim]Device:[/] [bold]{v.device}[/] {_region(v.region)} {v.product} [dim]({v.group})[/]")
    try:
        with _status(f"Asking {v.server} server"):
            return query(v.product, ota, v.server, v.nv, android, v.req_mode, beta)
    except (OtaError, httpx.HTTPError) as e:
        _fail(e)


def _aria2c(pkg: Package, out_dir: Path, conns: int) -> list[str]:
    name = f"{pkg.version or pkg.ota_version}.zip".replace("(", "_").replace(")", "").replace(" ", "_")
    cmd = ["aria2c", "-x", str(conns), "-s", str(conns), "-c", "-d", str(out_dir), "-o", name, "--auto-file-renaming=false"]
    cmd += [f"--header={k}: {v}" for k, v in DOWNLOAD_HEADERS.items()]
    return [*cmd, *([f"--checksum=md5={pkg.md5}"] if pkg.md5 else []), pkg.url]


def _show(pkg: Package, as_json: bool) -> None:
    if as_json:
        print(json.dumps(dataclasses.asdict(pkg), indent=2, ensure_ascii=False))
        return
    when = datetime.fromtimestamp(pkg.published / 1000, UTC).strftime("%Y-%m-%d") if pkg.published else "?"
    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold cyan", justify="right", min_width=9)
    t.add_column()
    for k, v in (
        ("Version", f"[bold green]{pkg.version}[/]"),
        ("OTA", pkg.ota_version),
        ("Android", pkg.android),
        ("Patch", pkg.security_patch),
        ("Published", when),
        ("Size", _size(pkg.size)),
        ("MD5", f"[dim]{pkg.md5}[/]"),
    ):
        if v:
            t.add_row(k, v)
    out.print(t)
    # Links unwrapped so they stay copyable; [link] makes them clickable in capable terminals.
    for k, link in (("Changelog", pkg.changelog), ("URL", pkg.url)):
        if link:
            out.print(f"[bold cyan]{k:>9}[/]  [link={link}]{link}[/]", soft_wrap=True)


def _table(*cols: str) -> Table:
    t = Table(box=None, header_style="bold cyan", pad_edge=False)
    for c in cols:
        t.add_column(c)
    return t


def _region(r: str) -> str:
    return f"[{SERVER_STYLE.get(catalog.REGIONS.get(r, ('', 'EU'))[1], 'white')}]{r}[/]"


def _size(n: int) -> str:
    return f"{n / 2**30:.2f} GiB"


@contextmanager
def _status(msg: str):
    with err.status(f"{msg}…", spinner="dots"):
        yield


def _adb_prop(name: str) -> str:
    try:
        return subprocess.run(["adb", "shell", "getprop", name], check=False, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _fail(msg: object) -> None:
    err.print(f"[bold red]error:[/] {msg}")
    raise typer.Exit(1)
