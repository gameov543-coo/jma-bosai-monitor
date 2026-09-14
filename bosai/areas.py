import json
import re
from pathlib import Path

RESOURCE = Path(__file__).parent / 'resources'


class Areas:
    def __init__(self, specifications, catalog=None, rivers=None):
        self.catalog = catalog or json.loads((RESOURCE / 'areas.json').read_text())
        self.rivers = rivers or json.loads((RESOURCE / 'rivers.json').read_text())
        self.nodes = {k: v for group in self.catalog.values() for k, v in group.items()}
        self.selected = set()
        cities = self.catalog['class20s']
        for spec in specifications:
            parts = re.split(r'[ /　]+', spec.strip())
            if spec in cities:
                hits = [spec]
            elif spec in self.catalog['offices']:
                hits = [k for k in cities if spec in self.ancestors(k)]
            else:
                pref = parts[0]
                # Hokkaido comprises multiple forecast offices; Okinawa also has several.
                offices = {k for k, v in self.catalog['offices'].items() if v['name'] == pref}
                if pref == '北海道':
                    offices = {k for k in self.catalog['offices'] if k.startswith('01')}
                if pref == '沖縄県':
                    offices = {k for k in self.catalog['offices'] if k.startswith('47')}
                candidates = [k for k in cities if offices.intersection(self.ancestors(k))]
                if len(parts) == 1:
                    hits = candidates
                else:
                    city = ''.join(parts[1:])
                    hits = [k for k in candidates if cities[k]['name'] == city or
                            (city.endswith(('市', '町', '村', '区')) and cities[k]['name'].startswith(city))]
            if not hits:
                raise ValueError(f'地域を解決できません: {spec}（areas コマンドで区域名・コードを確認）')
            self.selected.update(hits)
        self.offices = {x for k in self.selected for x in self.ancestors(k) if x in self.catalog['offices']}

    def ancestors(self, code):
        result = {code}
        while code in self.nodes and self.nodes[code].get('parent'):
            code = self.nodes[code]['parent']
            if code in result:
                break
            result.add(code)
        return result

    def matches(self, code):
        return code in self.selected

    def intersects(self, code):
        return any(code in self.ancestors(k) or (len(code) == 7 and code.endswith('00') and k[:5] == code[:5])
                   for k in self.selected)

    def name(self, code):
        name = self.nodes.get(code, {}).get('name', code)
        offices = [self.nodes[x]['name'] for x in self.ancestors(code) if x in self.catalog['offices']]
        return ' '.join(offices + [name])

    def river_codes(self):
        return {code for code, v in self.rivers.items() if any(self.intersects(c) for c in v['cities'])}
