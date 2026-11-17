# SPDX-FileCopyrightText: 2026 Reza Jelveh
#
# SPDX-License-Identifier: Apache-2.0

"""oplus-ota CLI entry point."""

import shutil
import subprocess
from pathlib import Path

import typer

from oplus_ota.devices import DEVICES
from oplus_ota.protocol import DOWNLOAD_HEADERS, query

app = typer.Typer(help="Query and download OPPO/OnePlus/realme OTA packages", no_args_is_help=True)


@app.command()
def main(
    device: str = typer.Argument(..., help=f"Device: {', '.join(DEVICES)}"),
    region: str = typer.Option("cn", "-r", "--region", help="Region variant: cn, eu, gl, in"),
    from_version: str | None = typer.Option(None, "--from", help="Current OTA version (default: lowest of the Android 16 group)"),
    download: bool = typer.Option(False, "-d", "--download", help="Download with aria2c"),
    output_dir: Path = typer.Option(Path("."), "-o", "--output-dir", help="Download directory"),
    connections: int = typer.Option(16, "-x", "--connections", help="aria2c connections per server"),
):
    variant = DEVICES.get(device.lower(), {}).get(region.lower())
    if not variant:
        _fail(f"unknown device/region: {device}/{region}")
    try:
        pkg = query(variant.model, from_version or variant.base_version, variant.region)
    except Exception as e:
        _fail(e)
    typer.echo(f"Version:  {pkg.version}\nOTA:      {pkg.ota_version}\nPatch:    {pkg.security_patch}")
    typer.echo(f"Size:     {pkg.size / 2**30:.2f} GiB\nMD5:      {pkg.md5}\nURL:      {pkg.url}")
    if download:
        _aria2c(pkg.url, pkg.md5, output_dir, connections)


def _aria2c(url: str, md5: str, out: Path, conns: int) -> None:
    if not shutil.which("aria2c"):
        _fail("aria2c not found")
    cmd = ["aria2c", "-x", str(conns), "-s", str(conns), "-c", "-d", str(out), "--auto-file-renaming=false"]
    cmd += [f"--header={k}: {v}" for k, v in DOWNLOAD_HEADERS.items()]
    if md5:
        cmd.append(f"--checksum=md5={md5}")
    raise typer.Exit(subprocess.call([*cmd, url]))


def _fail(msg: object) -> None:
    typer.echo(f"error: {msg}", err=True)
    raise typer.Exit(1)
