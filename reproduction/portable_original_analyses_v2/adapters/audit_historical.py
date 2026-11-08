def main() -> None:
    rows, failures = ([], [])
    for directory in sorted(RAW.iterdir()):
        if not directory.is_dir():
            continue
        try:
            row = audit_run(directory)
            route = ET.parse(directory / 'routes.rou.xml').getroot()
            car = next((vt for vt in route.findall('vType') if vt.get('id') == 'car'))
            row['car_tau_explicit'] = car.get('tau', '')
            row['car_action_step_explicit'] = car.get('actionStepLength', '')
            row['car_emission_class_explicit'] = car.get('emissionClass', '')
            truck = route.find("vType[@id='truck']")
            row['truck_present'] = truck is not None
            row['truck_emission_class_explicit'] = truck.get('emissionClass', '') if truck is not None else 'not applicable'
            row['planned_flow_vehicles'] = sum((int(flow.attrib['number']) for flow in route.findall('flow')))
            rows.append(row)
        except Exception as exc:
            failures.append({'run': directory.name, 'error': str(exc)})
    write_csv(ROOT / 'audit/historical_run_audit.csv', rows)
