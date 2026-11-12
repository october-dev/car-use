# Which adapter

car-use talks to ELM327-style adapters over Wi-Fi or USB. It grades what you actually have with `car-use dongle-doctor`. The grade is a measurement of that session, not a promise about a model we have not tried.

| Kind | What you get | Why |
| --- | --- | --- |
| OBDLink and other STN adapters | The doctor can recognise an STN chip and, when it is fast and the VIN read works, grade it A. | They answer the ST commands clones drop, and they are the ones the simulator's `stn` profile copies. |
| Genuine ELM327 | A full AT command set when the chip is real. Many listings that say "ELM327 v1.5" or "v2.1" are not this. | v1.5 was never a real ELM version. The doctor ignores the version string and counts missing commands. |
| Cheap Wi-Fi or USB clones | Basic reads often work. The grade is usually B or C: slower, some AT commands missing. | Fine for error codes and the common sensors. Many never sleep. Unplug them when you leave the car. |
| Bluetooth LE | Not supported. doctor says `BLE adapters are not supported yet`. | There is no BLE transport in car-use yet. |

Buy Wi-Fi or USB. Prefer an STN-based OBDLink if you want the fast, full command set the grade A path is written for. A clone is enough to read codes. Do not buy a Bluetooth-only adapter for car-use today.

`car-use dongle-doctor` prints the grade and which AT commands did not answer. That report is about your adapter, not this table.
