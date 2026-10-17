"""Per-model capability schema, recovered from the Windows build.

``Eye-CareU.exe`` embeds 43 ``<VCPTree>`` documents (one per supported monitor
family).  Reverse engineering shows only five distinct feature signatures.
Each document looks like::

    <VCPTree>
      <VCPList>
        <VCPcode Type="BI Type"   Name="BI Type"   Category="BI Type"   Value="BI"/>
        <VCPcode Type="BI Sensor" Name="BI Sensor" Category="BI Sensor" Value="on"/>
        <VCPcode Type="Brightness" Name="Brightness" Category="Brightness" Value="on"/>
        <VCPcode Type="LowBlueLight" ... Value="plus"/>
        <VCPcode Type="LowLightReminderEnable" ... Value="on"/>
        <VCPcode Type="SetOsdPivot" ... Value="on"/>
        <VCPcode Type="Volume" ... Value="on"/>
        <VCPcode Type="MaxVolume" ... Value="100"/>
      </VCPList>
    </VCPTree>

The Linux port does not need a hard-coded model table: support is discovered at
runtime from the monitor's own MCCS capability string (``Get Capabilities
Reply``) plus EDID.  This module keeps the *observed* Windows signatures so the
port can reproduce the original feature gating and offer a compatibility view.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# The nine feature tokens that appear across all 43 embedded schemas.
KNOWN_FEATURES: tuple[str, ...] = (
    "BI Type",
    "BI Sensor",
    "Brightness",
    "BrightnessForcePauseSyncTime",
    "LowBlueLight",
    "LowLightReminderEnable",
    "SetOsdPivot",
    "Volume",
    "MaxVolume",
)

# The five distinct signatures, with the number of schema documents each
# signature covered in the shipped build (observed evidence, not a guess).
OBSERVED_SIGNATURES: tuple[tuple[int, tuple[str, ...]], ...] = (
    (19, ("BI Sensor", "BI Type", "Brightness", "LowBlueLight",
          "LowLightReminderEnable", "MaxVolume", "Volume")),
    (8, ("BI Sensor", "BI Type", "Brightness", "BrightnessForcePauseSyncTime",
         "LowBlueLight", "LowLightReminderEnable", "MaxVolume", "SetOsdPivot",
         "Volume")),
    (6, ("BI Sensor", "BI Type", "Brightness", "BrightnessForcePauseSyncTime",
         "LowBlueLight", "LowLightReminderEnable", "MaxVolume", "Volume")),
    (6, ("Brightness", "LowBlueLight", "MaxVolume", "Volume")),
    (4, ("BI Sensor", "BI Type", "Brightness", "LowBlueLight",
         "LowLightReminderEnable", "Volume")),
)

# Monitor families listed in the shipped release note (v1.5.5.0).  Used only to
# present a "known model" hint; actual support is decided by EDID + MCCS.
KNOWN_MODELS: tuple[str, ...] = (
    "GW2790QP", "BL2790QP", "BL2490TE", "BL2790TE", "GW2491P", "GW2491PE",
    "BL2491P", "GW2791P", "GW2791PE", "BL2791P", "GW2490P", "GW2490PE",
    "BL2490P", "GW2790P", "GW2790PE", "BL2790P", "GW2291", "BL2291",
    "GW2490", "GW2490E", "GW2490T", "GW2790", "GW2790E", "GW2790T",
    "GW2790QT", "GW3290QT", "GW2790Q", "GW2491", "GW2491E", "GW2791",
    "GW2791E", "GW2490C", "GW2490CE", "GW2490TC", "GW2490TE", "GW2790C",
    "GW2790CE", "GW2790TC", "GW2790TE", "BL2490C", "BL2790C", "BL2490TC",
    "BL2790TC", "BL2486TC", "BL2490", "BL2490T", "BL2786TC", "BL2790",
    "BL2790Q", "BL2790QT", "BL2790T", "BL3290QT", "EW2880U", "EW3280U",
    "EW3880R", "GW2485TC", "GW2486TC", "GW2785TC", "GW2786TC",
)

# Feature -> the Eye-Care capability it enables in the port.
CAPABILITY_MAP: dict[str, str] = {
    "Brightness": "brightness",
    "Volume": "volume",
    "LowBlueLight": "low_blue_light",
    "BI Type": "brightness_intelligence",
    "BI Sensor": "ambient_light",
    "LowLightReminderEnable": "low_light_reminder",
    "SetOsdPivot": "pivot",
    "BrightnessForcePauseSyncTime": "brightness_sync",
    "MaxVolume": "volume",
}


@dataclass(slots=True)
class MonitorCapabilities:
    """Resolved feature support for one attached monitor."""

    capabilities: set[str] = field(default_factory=set)
    raw_features: dict[str, str] = field(default_factory=dict)
    is_known_model: bool = False
    model: str = ""
    bi_type: str = ""          # "BI" (Brightness Intelligence) or "VO" (Visual Optimizer)
    max_volume: int = 100
    low_blue_light_mode: str = ""  # "plus", "normal", ...

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


def signature_for(features: set[str]) -> tuple[str, ...]:
    """Return the observed signature tuple that best matches *features*."""
    for _count, signature in OBSERVED_SIGNATURES:
        if set(signature) == features:
            return signature
    return tuple(sorted(features))
