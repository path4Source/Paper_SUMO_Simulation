def route_source(state):
    if state == "baseline":
        return SOURCE_BASE / "fine_joint_seed11/routes.rou.xml"
    return ROOT / "core_detector_batch/inputs" / f"{state}.rou.xml"
