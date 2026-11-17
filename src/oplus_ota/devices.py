# SPDX-FileCopyrightText: 2026 Reza Jelveh
#
# SPDX-License-Identifier: Apache-2.0

"""Known devices: name -> region -> variant."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Variant:
    model: str
    region: str  # server: CN, EU, IN, GL
    letter: str = "H"  # firmware group, H = Android 16

    @property
    def base_version(self) -> str:
        """Lowest version of the group; the server answers with the latest full package."""
        return f"{self.model}_11.{self.letter}.01_0001_100001010000"


DEVICES: dict[str, dict[str, Variant]] = {
    "op11": {
        "cn": Variant("PHB110", "CN"),
        "eu": Variant("CPH2449EEA", "EU"),
        "gl": Variant("CPH2449", "GL"),
        "in": Variant("CPH2447", "IN"),
    },
}
