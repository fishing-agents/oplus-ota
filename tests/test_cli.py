# SPDX-FileCopyrightText: 2026 Reza Jelveh
#
# SPDX-License-Identifier: Apache-2.0

from typer.testing import CliRunner

from oplus_ota import cli
from oplus_ota.protocol import Package, parse

PKG = Package("PHB110_16.0.5.1301(CN01)", "PHB110_11.H.14", "https://x/downloadCheck?a=1", 2**30, "abc", "2026-10-01")


def test_parse_prefers_manual_url_and_strips_whitespace():
    content = {"body": {"components": [{"componentPackets": {"manualUrl": "https://a/ b", "url": "u", "size": "5"}}]}}
    assert parse(content).url == "https://a/b"


def test_download_builds_aria2c_command(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "query", lambda *a: PKG)
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/aria2c")
    calls = []
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: calls.append(cmd) or 0)
    r = CliRunner().invoke(cli.app, ["op11", "-d", "-o", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert calls[0][-1] == PKG.url
    assert "--checksum=md5=abc" in calls[0] and "--header=userId: oplus-ota|16002018" in calls[0]


def test_unknown_device_exits_1():
    assert CliRunner().invoke(cli.app, ["nope"]).exit_code == 1
