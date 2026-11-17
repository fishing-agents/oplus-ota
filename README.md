# oplus-ota

Query OPPO/OnePlus/realme OTA servers for the latest full package and download it with aria2c.
Ships the OTA Pulse device catalog (~150 devices, all regions).

```
uv run oplus-ota download                     # interactive: pick device (type to filter), then region
uv run oplus-ota devices op11                 # regions and models of a device
uv run oplus-ota regions                      # region -> NV id -> server
uv run oplus-ota query op11                   # latest CN full package: version, patch, size, MD5, changelog, link
uv run oplus-ota query "OnePlus 11" -r eu     # by name; region CN, EU, IN, GLO, ...
uv run oplus-ota query PHB110 -a 15 --json    # by model, older Android group, JSON
uv run oplus-ota download op11 -o ~/ota       # aria2c: 16 connections, resume, MD5 check
uv run oplus-ota download op11 -n             # print the aria2c command only
uv run oplus-ota url op11 -r in               # bare signed link, for scripts
uv run oplus-ota resolve '<downloadCheck link>'  # check a link is still valid
uv run oplus-ota phone                        # update for the adb-connected phone's build
```

`op<N>` is short for `OnePlus <N>`. A missing or ambiguous device or region opens a picker; without a terminal the region defaults to CN.
`--from <ota version>` asks as a given build instead of the group's lowest.
Download links are signed and expire after some hours; query again if aria2c fails.

The protocol and `catalog/*.json` come from [OTA Pulse](https://github.com/RemuruSama/OTA-Pulse) (Apache-2.0), see NOTICE.
