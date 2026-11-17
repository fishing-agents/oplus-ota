# SPDX-FileCopyrightText: 2026 Reza Jelveh
#
# SPDX-License-Identifier: Apache-2.0

"""Component OTA v3 protocol: encrypted query against the OPPO update servers."""

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from oplus_ota.config import SERVERS, user_file

# Headers the CDN wants on downloadCheck links.
DOWNLOAD_HEADERS = {"userId": "oplus-ota|16002018", "User-Agent": "okhttp/3.12.12"}


class OtaError(Exception):
    """The update server refused the query or offered nothing."""


@dataclass(frozen=True)
class Package:
    version: str
    ota_version: str
    url: str
    size: int
    md5: str
    security_patch: str
    android: str = ""
    published: int = 0  # ms since epoch
    changelog: str = ""


def _ctr(key: bytes, iv: bytes) -> Cipher:
    return Cipher(algorithms.AES(key), modes.CTR(iv))


def _protected_key(key_b64: str, pubkey: str) -> str:
    pub = serialization.load_der_public_key(base64.b64decode(pubkey))
    oaep = padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)
    return base64.b64encode(pub.encrypt(key_b64.encode(), oaep)).decode()


def query(
    model: str, ota_version: str, server: str, nv: str = "", android: int = 16, req_mode: str = "manual", beta: bool = False
) -> Package:
    """Ask a server (CN, EU, IN, GL) for the latest full package for this model.
    nv is the region's NV id (e.g. NV44); without it the server's default carrier is used."""
    srv = SERVERS[server]
    now = int(time.time() * 1000)
    prefix = "_".join(ota_version.split("_")[:2])
    fields = {
        "language": "zh-CN" if server == "CN" else "en-EN",
        "romVersion": prefix,
        "otaVersion": ota_version,
        "androidVersion": f"Android {android}" if android >= 17 else f"Android{android}.0",
        "colorOSVersion": f"ColorOS {android}.0" if android >= 17 else f"ColorOS{android}",
        "model": model,
        "uRegion": server,
        "trackRegion": server,
        "imei": "0" * 15,
        "imei1": "0" * 15,
        "deviceId": hashlib.sha256(b"0").hexdigest(),
    }
    body = fields | {
        "productName": model,
        "operator": "unknown",
        "mode": "1" if beta else "0",
        "registrationId": "unknown",
        "version": "3",
        "type": "1",
        "otaPrefix": prefix,
        "isRealme": "0",
        "time": str(now),
        "canCheckSelf": "0",
        "gray": "0",
        "reqMode": req_mode,
    }
    key, iv = os.urandom(32), os.urandom(16)
    enc = _ctr(key, iv).encryptor()
    cipher = enc.update(json.dumps(body).encode()) + enc.finalize()
    protected = _protected_key(base64.b64encode(key).decode(), srv.pubkey)
    headers = fields | {
        "infVersion": "1",
        "operator": "unknown",
        "nvCarrier": nv or srv.carrier,
        "mode": req_mode,
        "channel": "pc",
        "version": "2",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "NULL",
        "protectedKey": json.dumps(
            {"SCENE_1": {"protectedKey": protected, "version": str(now + 86400000), "negotiationVersion": srv.negotiation}}
        ),
    }
    params = json.dumps({"cipher": base64.b64encode(cipher).decode(), "iv": base64.b64encode(iv).decode()})
    r = httpx.post(srv.url, content=json.dumps({"params": params}), headers=headers, timeout=30)
    r.raise_for_status()
    resp = r.json()
    if resp.get("responseCode", 200) != 200:
        hint = f"; if the {server} key rotated, update {user_file()}" if resp.get("responseCode") == 500 else ""
        raise OtaError(f"server error {resp.get('responseCode')}: {resp.get('errMsg')}{hint}")
    try:
        wrapped = json.loads(resp["body"])
        dec = _ctr(key, base64.b64decode(wrapped["iv"])).decryptor()
        content = json.loads(dec.update(base64.b64decode(wrapped["cipher"])) + dec.finalize())
    except (KeyError, TypeError, ValueError) as e:
        raise OtaError(f"{server} server reply unreadable ({e}); its key may have rotated, update {user_file()}") from e
    return parse(content)


def parse(content: dict) -> Package:
    """Pick the first component's package from a decrypted response."""
    root = content.get("body", content)
    if root.get("checkFailReason"):
        raise OtaError(f"update check failed: {root['checkFailReason']}")
    comps = root.get("components") or []
    if not comps:
        raise OtaError("no update offered")
    pkt = comps[0]["componentPackets"]
    return Package(
        version=root.get("realVersionName") or root.get("versionName", ""),
        ota_version=root.get("realOtaVersion") or root.get("otaVersion", ""),
        url="".join((pkt.get("manualUrl") or pkt["url"]).split()),
        size=int(pkt.get("size") or 0),
        md5=pkt.get("md5", ""),
        security_patch=root.get("securityPatch", ""),
        android=root.get("realAndroidVersion") or root.get("androidVersion", ""),
        published=int(root.get("publishedTime") or 0),
        changelog="".join(((root.get("description") or {}).get("panelUrl") or "").split()),
    )
