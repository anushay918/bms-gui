SIGNAL_HELP = {
    "BMS_Pack_Voltage": "Total pack voltage.",
    "BMS_Pack_Current": "Pack current (sign depends on your system).",
    "_IC_Voltage": "Segment/module voltage (sum of cells in segment).",
    "_IC_Temp": "Segment temperature sensor.",
    "_isFaultDetected": "Fault flag (true = fault).",
    "_isCommsError": "Comms error flag (true = comms issue).",
    "_Voltage": "Cell voltage.",
    "_VoltageDiff": "Cell imbalance / deviation (mV).",
    "_Temp": "Cell temperature sensor.",
    "_isDischarging": "Discharging/balancing indicator (system-dependent).",
}

def describe_signal(signal_name: str) -> str:
    # exact match
    if signal_name in SIGNAL_HELP:
        return SIGNAL_HELP[signal_name]
    # suffix match
    for k, v in SIGNAL_HELP.items():
        if k.startswith("_") and signal_name.endswith(k):
            return v
    return "No description added yet."
