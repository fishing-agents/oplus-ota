# SPDX-FileCopyrightText: 2026 Reza Jelveh
#
# SPDX-License-Identifier: Apache-2.0

"""oplus-ota CLI entry point."""

import dataclasses
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import typer

from oplus_ota import catalog
from oplus_ota.protocol import DOWNLOAD_HEADERS, Package, query

app = typer.Typer(help="Query and download OPPO/OnePlus/realme OTA packages", no_args_is_help=True)

DeviceArg = typer.Argument(..., help="Device name or model, e.g. 'OnePlus 11', op11, PHB110, CPH2449")
RegionOpt = typer.Option("CN", "-r", "--region", help="Region: CN, EU, IN, GLO, ... (see 'regions')")
GroupOpt = typer.Option(None, "-a", "--android", help="Firmware group, e.g. 16 (default: newest)")
FromOpt = typer.Option(None, "--from", help="Current OTA version, e.g. PHB110_11.H.13_3130_202607172124")
BetaOpt = typer.Option(False, "--beta", help="Ask for beta builds")
JsonOpt = typer.Option(False, "--json", help="Print JSON")

SHORT = {"op": "oneplus"}  # op11 -> oneplus11


@app.command()
def devices(search: str = typer.Argument("", help="Filter by name or model")):
    """List known devices with their regions and models."""
    rows: dict[str, set[str]] = {}
    for v in catalog.match(_expand(search)) if search else catalog.load():
        rows.setdefault(v.device, set()).add(f"{v.region}:{v.model}")
    for name in sorted(rows):
        typer.echo(f"{name}: {' '.join(sorted(rows[name]))}")
    if not rows:
        _fail(f"no device matches '{search}'")


@app.command()
def regions():
    """List regions, their NV ids and servers."""
    for name, (nv, srv) in catalog.REGIONS.items():
        typer.echo(f"{name:6} {nv}  {srv}")


@app.command("query")
def query_cmd(
    device: str = DeviceArg, region: str = RegionOpt, android: str | None = GroupOpt, from_version: str | None = FromOpt,
    beta: bool = BetaOpt, as_json: bool = JsonOpt,
):
    """Show the latest full package: version, size, MD5, link."""
    pkg = _query(device, region, android, from_version, beta)
    _show(pkg, as_json)


@app.command()
def url(device: str = DeviceArg, region: str = RegionOpt, android: str | None = GroupOpt, from_version: str | None = FromOpt):
    """Print only the signed download link (for scripts)."""
    typer.echo(_query(device, region, android, from_version, False).url)


@app.command()
def download(
    device: str = DeviceArg, region: str = RegionOpt, android: str | None = GroupOpt, from_version: str | None = FromOpt,
    beta: bool = BetaOpt,
    output_dir: Path = typer.Option(Path("."), "-o", "--output-dir", help="Download directory"),
    connections: int = typer.Option(16, "-x", "--connections", help="aria2c connections"),
    dry_run: bool = typer.Option(False, "-n", "--dry-run", help="Print the aria2c command instead of running it"),
):
    """Download the latest full package with aria2c (resumes, checks MD5)."""
    pkg = _query(device, region, android, from_version, beta)
    _show(pkg, False)
    name = _filename(pkg)
    cmd = ["aria2c", "-x", str(connections), "-s", str(connections), "-c", "-d", str(output_dir), "-o", name, "--auto-file-renaming=false"]
    cmd += [f"--header={k}: {v}" for k, v in DOWNLOAD_HEADERS.items()]
    if pkg.md5:
        cmd.append(f"--checksum=md5={pkg.md5}")
    cmd.append(pkg.url)
    if dry_run:
        typer.echo(" ".join(f"'{c}'" if " " in c or "&" in c else c for c in cmd))
        return
    if not shutil.which("aria2c"):
        _fail("aria2c not found")
    raise typer.Exit(subprocess.call(cmd))


@app.command()
def resolve(link: str = typer.Argument(..., help="downloadCheck link")):
    """Follow a downloadCheck link to the CDN URL; shows whether it is still valid."""
    with httpx.Client(headers=DOWNLOAD_HEADERS, follow_redirects=True, timeout=30) as c:
        r = c.get(link, headers={"Range": "bytes=0-0"})
    if r.status_code not in (200, 206) or "json" in r.headers.get("content-type", ""):
        _fail(f"HTTP {r.status_code}: {r.text[:200]}")
    total = r.headers.get("content-range", "").rpartition("/")[2] or r.headers.get("content-length", "?")
    typer.echo(f"OK {total} bytes\n{r.url}")


@app.command()
def phone(as_json: bool = JsonOpt, beta: bool = BetaOpt):
    """Check the phone connected via adb for an update to its current build."""
    ota, android = _adb_prop("ro.build.version.ota"), _adb_prop("ro.build.version.release")
    if not ota:
        _fail("no phone over adb, or ro.build.version.ota missing")
    region = next((r for r, (nv, _) in catalog.REGIONS.items() if ota.split("_")[0].endswith(nv)), None)
    model = ota.split("_")[0].removesuffix(catalog.REGIONS[region][0]) if region else ota.split("_")[0]
    hits = catalog.find(model, region) if region else [v for r in ("CN", "IN", "GLO") for v in catalog.find(model, r)][:1]
    if not hits:
        _fail(f"{model} not in catalog; use 'query <model> -r <region> --from {ota}'")
    v = hits[0]
    typer.echo(f"Phone:    {v.device} {v.region} {ota} (Android {android})", err=True)
    try:
        pkg = query(v.product, ota, v.server, v.nv, int(android or v.android), v.req_mode, beta)
    except Exception as e:
        _fail(e)
    _show(pkg, as_json)


def _expand(s: str) -> str:
    low = s.lower()
    for k, v in SHORT.items():
        if low.startswith(k) and low[len(k):].isdigit():
            return v + low[len(k):]
    return s


def _query(device: str, region: str, android: str | None, from_version: str | None, beta: bool) -> Package:
    hits = catalog.find(_expand(device), region, android)
    if not hits:
        avail = sorted({v.region for v in catalog.match(_expand(device))})
        _fail(f"no {device} variant for region {region}" + (f" (have: {', '.join(avail)})" if avail else "; see 'devices'"))
    v = hits[0]
    typer.echo(f"Device:   {v.device} {v.region} {v.product} ({v.group})", err=True)
    try:
        return query(v.product, from_version or v.base_version, v.server, v.nv, v.android, v.req_mode, beta)
    except Exception as e:
        _fail(e)


def _filename(pkg: Package) -> str:
    return f"{pkg.version or pkg.ota_version}.zip".replace("(", "_").replace(")", "").replace(" ", "_")


def _show(pkg: Package, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(dataclasses.asdict(pkg), indent=2, ensure_ascii=False))
        return
    when = datetime.fromtimestamp(pkg.published / 1000, UTC).strftime("%Y-%m-%d") if pkg.published else "?"
    typer.echo(f"Version:   {pkg.version}\nOTA:       {pkg.ota_version}\nAndroid:   {pkg.android}\nPatch:     {pkg.security_patch}")
    typer.echo(f"Published: {when}\nSize:      {pkg.size / 2**30:.2f} GiB\nMD5:       {pkg.md5}")
    if pkg.changelog:
        typer.echo(f"Changelog: {pkg.changelog}")
    typer.echo(f"URL:       {pkg.url}")


def _adb_prop(name: str) -> str:
    try:
        return subprocess.run(["adb", "shell", "getprop", name], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _fail(msg: object) -> None:
    typer.echo(f"error: {msg}", err=True)
    raise typer.Exit(1)
