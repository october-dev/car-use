# Wi-Fi adapters

A Wi-Fi OBD adapter is its own little network. Your computer talks to the adapter, not to your home router, while you are joined to it.

1. Plug the adapter into the OBD port and turn the ignition on. The engine running, in a ventilated place, is best.
2. On the computer, join the adapter's Wi-Fi. The name is often `WiFi_OBDII` or `V-LINK`. It usually has no internet. That is normal. A cloud-based agent needs another internet connection while this computer is joined to the adapter's network; use USB if that is not available.
3. Tell car-use where it is. This address is the one most of these adapters use:

```bash
car-use config set device tcp://192.168.0.10:35000
car-use doctor
```

If doctor says it cannot reach the adapter, try the other address the onboarding uses, still on port 35000:

```bash
car-use config set device tcp://192.168.1.10:35000
car-use doctor
```

Leave the adapter's Wi-Fi when you are done, or the computer will stay offline.

car-use does not scan for the adapter. If neither address answers, the doctor line is the one in [troubleshooting](troubleshooting.md) that starts with `Cannot reach adapter`.
