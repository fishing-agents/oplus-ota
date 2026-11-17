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


@dataclass(frozen=True)
class Server:
    url: str
    pubkey: str
    negotiation: str
    carrier: str


SERVERS = {
    "CN": Server(
        "https://component-otapc-cn.allawntech.com/update/v3",
        "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEApXYGXQpNL7gmMzzvajHaoZIHQQvBc2cOEhJc7/tsaO4sT0unoQnwQKfNQCuv7qC1Nu32eCLuewe9LSYhDXr9KSBWjOcCFXVXteLO9WCaAh5hwnUoP/5/Wz0jJwBA+yqs3AaGLA9wJ0+B2lB1vLE4FZNE7exUfwUc03fJxHG9nCLKjIZlrnAAHjRCd8mpnADwfkCEIPIGhnwq7pdkbamZcoZfZud1+fPsELviB9u447C6bKnTU4AaMcR9Y2/uI6TJUTcgyCp+ilgU0JxemrSIPFk3jbCbzamQ6Shkw/jDRzYoXpBRg/2QDkbq+j3ljInu0RHDfOeXf3VBfHSnQ66HCwIDAQAB",
        "1615879139745",
        "10010111",
    ),
    "EU": Server(
        "https://component-otapc-eu.allawnos.com/update/v3",
        "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAh8/EThsK3f0WyyPgrtXb/D0Xni6UZNppaQHUqHWo976cybl92VxmehE0ISObnxERaOtrlYmTPIxkVC9MMueDvTwZ1l0KxevZVKU0sJRxNR9AFcw6D7k9fPzzpNJmhSlhpNbt3BEepdgibdRZbacF3NWy3ejOYWHgxC+I/Vj1v7QU5gD+1OhgWeRDcwuV4nGY1ln2lvkRj8EiJYXfkSq/wUI5AvPdNXdEqwou4FBcf6mD84G8pKDyNTQwwuk9lvFlcq4mRqgYaFg9DAgpDgqVK4NTJWM7tQS1GZuRA6PhupfDqnQExyBFhzCefHkEhcFywNyxlPe953NWLFWwbGvFKwIDAQAB",
        "1615897067573",
        "01000100",
    ),
    "IN": Server(
        "https://component-otapc-in.allawnos.com/update/v3",
        "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwYtghkzeStC9YvAwOQmWylbp74Tj8hhi3f9IlK7A/CWrGbLgzz/BeKxNb45zBN8pgaaEOwAJ1qZQV5G4nProWCPOP1ro1PkemFJvw/vzOOT5uN0ADnHDzZkZXCU/knxqUSfLcwQlHXsYhNsAm7uOKjY9YXF4zWzYN0eFPkML3Pj/zg7hl/ov9clB2VeyI1/blMHFfcNA/fvqDTENXcNBIhgJvXiCpLcZqp+aLZPC5AwY/sCb3j5jTWer0Rk0ZjQBZE1AncwYvUx4mA65U59cWpTyl4c47J29MsQ66hqWv6eBHlDNZSEsQpHePUqgsf7lmO5Wd7teB8ugQki2oz1Y5QIDAQAB",
        "1615896309308",
        "00011011",
    ),
    "GL": Server(
        "https://component-otapc-sg.allawnos.com/update/v3",
        "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAkA980wxi+eTGcFDiw2I6RrUeO4jL/Aj3Yw4dNuW7tYt+O1sRTHgrzxPD9SrOqzz7G0KgoSfdFHe3JVLPN+U1waK+T0HfLusVJshDaMrMiQFDUiKajb+QKr+bXQhVofH74fjat+oRJ8vjXARSpFk4/41x5j1Bt/2bHoqtdGPcUizZ4whMwzap+hzVlZgs7BNfepo24PWPRujsN3uopl+8u4HFpQDlQl7GdqDYDj2zNOHdFQI2UpSf0aIeKCKOpSKF72KDEESpJVQsqO4nxMwEi2jMujQeCHyTCjBZ+W35RzwT9+0pyZv8FB3c7FYY9FdF/+lvfax5mvFEBd9jO+dpMQIDAQAB",
        "1615895993238",
        "00011011",
    ),
}

# Headers the CDN wants on downloadCheck links.
DOWNLOAD_HEADERS = {"userId": "oplus-ota|16002018", "User-Agent": "okhttp/3.12.12"}


@dataclass(frozen=True)
class Package:
    version: str
    ota_version: str
    url: str
    size: int
    md5: str
    security_patch: str


def _ctr(key: bytes, iv: bytes) -> Cipher:
    return Cipher(algorithms.AES(key), modes.CTR(iv))


def _protected_key(key_b64: str, pubkey: str) -> str:
    pub = serialization.load_der_public_key(base64.b64decode(pubkey))
    oaep = padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)
    return base64.b64encode(pub.encrypt(key_b64.encode(), oaep)).decode()


def query(model: str, ota_version: str, region: str, android: int = 16) -> Package:
    """Ask the region's server for the latest full package for this model."""
    srv = SERVERS[region]
    now = int(time.time() * 1000)
    prefix = "_".join(ota_version.split("_")[:2])
    fields = {
        "language": "zh-CN" if region == "CN" else "en-EN",
        "romVersion": prefix,
        "otaVersion": ota_version,
        "androidVersion": f"Android{android}.0",
        "colorOSVersion": f"ColorOS{android}",
        "model": model,
        "uRegion": region,
        "trackRegion": region,
        "imei": "0" * 15,
        "imei1": "0" * 15,
        "deviceId": hashlib.sha256(b"0").hexdigest(),
    }
    body = fields | {
        "productName": model, "operator": "unknown", "mode": "0", "registrationId": "unknown", "version": "3", "type": "1",
        "otaPrefix": prefix, "isRealme": "0", "time": str(now), "canCheckSelf": "0", "gray": "0", "reqMode": "manual",
    }
    key, iv = os.urandom(32), os.urandom(16)
    enc = _ctr(key, iv).encryptor()
    cipher = enc.update(json.dumps(body).encode()) + enc.finalize()
    protected = _protected_key(base64.b64encode(key).decode(), srv.pubkey)
    headers = fields | {
        "infVersion": "1", "operator": "unknown", "nvCarrier": srv.carrier, "mode": "manual", "channel": "pc", "version": "2",
        "Accept": "application/json", "Content-Type": "application/json", "User-Agent": "NULL",
        "protectedKey": json.dumps({"SCENE_1": {"protectedKey": protected, "version": str(now + 86400000), "negotiationVersion": srv.negotiation}}),
    }
    params = json.dumps({"cipher": base64.b64encode(cipher).decode(), "iv": base64.b64encode(iv).decode()})
    r = httpx.post(srv.url, content=json.dumps({"params": params}), headers=headers, timeout=30)
    r.raise_for_status()
    resp = r.json()
    if resp.get("responseCode", 200) != 200:
        raise RuntimeError(f"server error {resp.get('responseCode')}: {resp.get('errMsg')}")
    wrapped = json.loads(resp["body"])
    dec = _ctr(key, base64.b64decode(wrapped["iv"])).decryptor()
    return parse(json.loads(dec.update(base64.b64decode(wrapped["cipher"])) + dec.finalize()))


def parse(content: dict) -> Package:
    """Pick the first component's package from a decrypted response."""
    root = content.get("body", content)
    if root.get("checkFailReason"):
        raise RuntimeError(f"update check failed: {root['checkFailReason']}")
    comps = root.get("components") or []
    if not comps:
        raise RuntimeError("no update offered")
    pkt = comps[0]["componentPackets"]
    return Package(
        version=root.get("realVersionName") or root.get("versionName", ""),
        ota_version=root.get("realOtaVersion") or root.get("otaVersion", ""),
        url="".join((pkt.get("manualUrl") or pkt["url"]).split()),
        size=int(pkt.get("size") or 0),
        md5=pkt.get("md5", ""),
        security_patch=root.get("securityPatch", ""),
    )
