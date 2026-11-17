# oplus-ota

Query OPPO/OnePlus/realme OTA servers for the latest full package and download it with aria2c.

```
uv run oplus-ota op11               # latest CN (ColorOS) full package: version, size, MD5, URL
uv run oplus-ota op11 -r eu         # OxygenOS EU
uv run oplus-ota op11 -d -o ~/ota   # download with aria2c (resumes, verifies MD5)
```

Download links are signed and expire after some hours; query again if aria2c fails.
The protocol follows [OTA Pulse](https://github.com/RemuruSama/OTA-Pulse) (Apache-2.0), see NOTICE.
