# SPDX-FileCopyrightText: 2026 Reza Jelveh
#
# SPDX-License-Identifier: Apache-2.0

from typer.testing import CliRunner

from oplus_ota import catalog, cli
from oplus_ota.protocol import Package, parse

PKG = Package("PHB110_16.0.5.1301(CN01)", "PHB110_11.H.14", "https://x/downloadCheck?a=1&b=2", 2**30, "abc", "2026-10-01")
run = CliRunner().invoke


def test_parse_prefers_manual_url_and_strips_whitespace():
    content = {"body": {"components": [{"componentPackets": {"manualUrl": "https://a/ b", "url": "u", "size": "5"}}]}}
    assert parse(content).url == "https://a/b"


def test_catalog_op11_regions_and_base_versions():
    eu = catalog.find("OnePlus 11", "EU")[0]
    assert (eu.product, eu.server, eu.base_version) == ("CPH2449EEA", "EU", "CPH2449NV44_11.H.01_0001_100001010000")
    assert catalog.find("PHB110", "CN")[0].device == "OnePlus 11"
    assert catalog.find("op11", "gl") == [] and cli._expand("op11") == "oneplus11"
    assert catalog.find(cli._expand("op11"), "gl")[0].region == "GLO"


def test_download_dry_run_builds_aria2c_command(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "query", lambda *a: calls.append(a) or PKG)
    r = run(cli.app, ["download", "op11", "-r", "eu", "-n", "-o", "/tmp/x"])
    assert r.exit_code == 0, r.output
    assert calls[0][:4] == ("CPH2449EEA", "CPH2449NV44_11.H.01_0001_100001010000", "EU", "NV44")
    assert "-o PHB110_16.0.5.1301_CN01.zip" in r.output and "--checksum=md5=abc" in r.output
    assert "'--header=userId: oplus-ota|16002018'" in r.output and f"'{PKG.url}'" in r.output


def test_unknown_region_lists_available():
    r = run(cli.app, ["query", "op11", "-r", "br"])
    assert r.exit_code == 1 and "have: CN, EU, GLO, IN" in r.output


def test_devices_filter():
    r = run(cli.app, ["devices", "op11"])
    assert r.exit_code == 0 and "OnePlus 11: CN:PHB110 EU:CPH2449 GLO:CPH2449 IN:CPH2447" in r.output
