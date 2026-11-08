def main():
    template = OUT / 'sumo_124_option_template.xml'
    tau_source = OUT / 'SUMO_v1_24_0_MSCFModel.cpp'
    if 'getCFParam(SUMO_ATTR_TAU, 1.0)' not in tau_source.read_text(encoding='utf-8'):
        raise RuntimeError('Version-specific desired-headway default not verified')
    defaults = values(template)
    source_rows = read(ROOT / 'frozen/data/sumo_multiseed_results.csv')
    if len(source_rows) != 81:
        raise RuntimeError('Unexpected original OAT scope')
    setting_rows, vehicle_rows, flow_rows, manifests = ([], [], [], [])
    per_scenario = defaultdict(list)
    for source in source_rows:
        scenario, seed = (source['scenario'], int(source['seed']))
        name = scenario if seed == 42 else source['scenario_run']
        directory = ROOT.parent / 'road_capacity_sci/outputs/sumo_runs' / name
        cfg = embedded_config(directory / 'summary.xml')
        root = ET.parse(directory / 'routes.rou.xml').getroot()
        if any(('actionStepLength' in v.attrib for v in root.findall('vType'))):
            raise RuntimeError('Vehicle action override needs explicit reporting')
        setting_rows.append({'series': 'original_OAT', 'run': name, 'seed': seed, 'begin_s': cfg['begin'], 'end_s': cfg['end'], **resolve(cfg, defaults)})
        types = {v.attrib['id']: dict(v.attrib) for v in root.findall('vType')}
        per_scenario[scenario].append(types)
        for type_id, attrs in types.items():
            vehicle_rows.append({'scenario': scenario, 'seed': seed, 'vehicle_type': type_id, 'resolved_tau_s': resolved_vehicle(attrs)['tau'], 'tau_source': 'explicit' if 'tau' in attrs else 'SUMO 1.24.0 default', **{k: attrs.get(k, 'not explicitly assigned') for k in VEHICLE_KEYS}})
        for flow in root.findall('flow'):
            a = flow.attrib
            flow_rows.append({'scenario': scenario, 'seed': seed, 'flow': a['id'], 'type': a['type'], 'planned': int(a['number']), 'begin': a['begin'], 'end': a['end'], 'departLane': a.get('departLane', 'not explicitly assigned'), 'departSpeed': a.get('departSpeed', 'not explicitly assigned')})
        manifests.append({'run': name, 'routes_sha256': sha256(directory / 'routes.rou.xml'), 'summary_sha256': sha256(directory / 'summary.xml')})
    explicit_default_differences = [scenario for scenario, versions in per_scenario.items() if check_vehicle_versions(scenario, versions)]
    signatures = {tuple((r[k] for k in OPTIONS)) for r in setting_rows}
    if len(signatures) != 1:
        raise RuntimeError('Original OAT global settings not uniform')
    if {r['departLane'] for r in flow_rows} != {'free'} or {r['departSpeed'] for r in flow_rows} != {'max'}:
        raise RuntimeError('Departure settings not uniform')
    examples = {'compatible_headway_0.1': ROOT / 'stage3_settings/runs/tau0.8_dt0.1_action0.1_seed42_junctions0/run.sumocfg', 'intervention_reference_0.1': ROOT / 'connector_audit_v1/runs/fine_joint_seed11/run.sumocfg', 'morris_0.1': ROOT / 'morris_screening_v1/runs/control_seed11/run.sumocfg'}
    for series, path in examples.items():
        cfg = values(path)
        setting_rows.append({'series': series, 'run': path.parent.name, 'seed': int(cfg['seed']), 'begin_s': cfg['begin'], 'end_s': cfg['end'], **resolve(cfg, defaults)})
        manifests.append({'run': path.parent.name, 'config_sha256': sha256(path)})
    write_csv(OUT / 'global_settings.csv', setting_rows)
    write_csv(OUT / 'original_vehicle_definitions.csv', vehicle_rows)
    write_csv(OUT / 'original_departure_settings.csv', flow_rows)
