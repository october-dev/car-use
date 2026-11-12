"""The fixed list of root causes an agent picks from. Fixed so grading is exact."""

ROOT_CAUSES: dict[str, str] = {
    "catalytic_converter": "Catalytic converter worn out or damaged",
    "o2_sensor_upstream": "Upstream (front, pre-catalyst) oxygen sensor faulty or slow",
    "o2_sensor_downstream": "Downstream (rear, post-catalyst) oxygen sensor faulty",
    "exhaust_leak": "Exhaust leak",
    "vacuum_leak": "Vacuum or unmetered air leak",
    "maf_sensor": "Mass air flow sensor dirty or faulty",
    "fuel_delivery": "Fuel pump, filter or pressure regulator problem",
    "fuel_injector": "Leaking, stuck or clogged fuel injector",
    "ignition_coil": "Ignition coil fault",
    "spark_plug": "Worn or fouled spark plugs",
    "low_compression": "Low compression (mechanical engine problem)",
    "thermostat_stuck_open": "Thermostat stuck open (engine runs too cold)",
    "coolant_temp_sensor": "Coolant temperature sensor faulty",
    "overheating": "Cooling system failure, engine overheating",
    "evap_gas_cap": "Fuel cap loose, damaged or missing",
    "evap_system_leak": "EVAP system leak other than the fuel cap (hoses, purge valve, canister)",
    "alternator_charging": "Alternator, its belt or wiring not charging",
    "battery_weak": "Battery weak or failing",
    "wiring_or_connector": "Wiring or connector fault",
    "transmission": "Transmission problem",
    "codes_recently_cleared": "Trouble codes were cleared recently; the car's self-checks have not finished",
    "ignition_off_or_no_power": "Ignition is off or the ECU has no power, so the car does not answer",
    "adapter_problem": "The OBD adapter itself is faulty or incompatible",
    "no_fault_found": "Nothing wrong found in the data",
    "need_more_data": "Cannot tell from this data; a physical test is needed first",
}


def prompt_list() -> str:
    return "\n".join(f"  {k}: {v}" for k, v in ROOT_CAUSES.items())
