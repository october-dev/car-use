"""Aftermarket and race ECUs: TunerStudio-compatible ECUs (Speeduino, rusEFI,
MegaSquirt) and engine logs. Read-only for now.

    tsini   parse the ECU's TunerStudio .ini: every table, setting and live channel by name
    logs    read MegaLogViewer .msl and CSV logs (Haltech, Link, ECUMaster exports)

car-use speaks the published .ini format and protocol; it does not use or ship
TunerStudio. Point it at your ECU's own .ini (it comes with the firmware).
"""
