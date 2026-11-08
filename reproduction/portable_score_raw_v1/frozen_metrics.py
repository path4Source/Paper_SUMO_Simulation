from pathlib import Path
from typing import Dict
import math
import numpy as np
import xml.etree.ElementTree as ET

def parse_summary(path: Path) -> Dict[str, float]:
    root = ET.parse(path).getroot()
    halting = []
    arrived = 0
    running = []
    for step in root.findall("step"):
        halting.append(float(step.get("halting", "0")))
        running.append(float(step.get("running", "0")))
        arrived = max(arrived, int(float(step.get("arrived", "0"))))
    return {
        "mean_halting": float(np.mean(halting)) if halting else 0.0,
        "mean_running": float(np.mean(running)) if running else 0.0,
        "arrived_vehicles": float(arrived),
    }

def parse_tripinfo(path: Path) -> Dict[str, float]:
    root = ET.parse(path).getroot()
    duration = []
    waiting = []
    time_loss = []
    route_length = []
    for trip in root.findall("tripinfo"):
        duration.append(float(trip.get("duration", "0")))
        waiting.append(float(trip.get("waitingTime", "0")))
        time_loss.append(float(trip.get("timeLoss", "0")))
        route_length.append(float(trip.get("routeLength", "0")))
    if not duration:
        return {
            "mean_duration": math.nan,
            "mean_waiting_time": math.nan,
            "mean_time_loss": math.nan,
            "mean_route_length": math.nan,
        }
    return {
        "mean_duration": float(np.mean(duration)),
        "mean_waiting_time": float(np.mean(waiting)),
        "mean_time_loss": float(np.mean(time_loss)),
        "mean_route_length": float(np.mean(route_length)),
    }

def parse_emissions(path: Path) -> Dict[str, float]:
    root = ET.parse(path).getroot()
    co2_mg = 0.0
    fuel_ml = 0.0
    for interval in root.findall("interval"):
        for edge in interval.findall("edge"):
            co2_mg += float(edge.get("CO2_abs", "0"))
            fuel_ml += float(edge.get("fuel_abs", "0"))
    return {"total_co2_kg": co2_mg / 1_000_000.0, "total_fuel_l": fuel_ml / 1000.0}
