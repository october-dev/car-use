# Onboarding (for the agent)

Walk the person through this, one step at a time. Wait for them where a step needs their hands.

1. **Check the install.** Run `car-use --version` and `car-use skill`. Read the skill fully before continuing.
2. **Show the simulator first.** Run one scenario end to end (`car-use --sim p0420`). Read codes, the freeze frame and readiness, watch both O2 sensors, and explain the finding in plain words. This shows the person what car-use does before any hardware is involved.
3. **Ask what they have:**
   - An OBD-II adapter? Which kind: Wi-Fi, USB, or Bluetooth (BLE isn't supported yet).
   - Which car (make, model, year, country)?
   - Is the car nearby, with the ignition able to be turned on?
4. **Connect.** The person does these steps. The longer notes are in `setup/` (Wi-Fi, USB, Windows, Bluetooth, and the doctor troubleshooting table).
   - Plug the adapter into the OBD-II port, usually under the dashboard on the driver's side.
   - Turn the ignition on. Engine running is best, in a ventilated place, never in a closed garage.
   - Wi-Fi adapter: join its network, then run `car-use config set device tcp://192.168.0.10:35000`. If that address fails, try `192.168.1.10`.
   - USB adapter: find the port with `ls /dev/cu.*` on macOS or `/dev/ttyUSB*` on Linux, then run `car-use config set device "serial:///dev/cu.XXX?baud=38400"`. Install the `car-use[serial]` extra.
5. **Run `car-use doctor`.** If it fails, relay its one-line fix and retry once after the person says it's done. Don't loop.
6. **Run `car-use dongle-doctor`.** Tell the person the grade and what it means. If it's a clone, remind them not to leave it plugged in overnight.
7. **First look.** Run `car().describe()`, `vin_info()`, `dtcs()` and `readiness()`, then summarise in 3-5 lines. Ask what they'd like to do next.
