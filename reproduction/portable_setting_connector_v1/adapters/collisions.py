def collisions(path):
    return [e.attrib for e in ET.parse(path).getroot().findall('collision')]
