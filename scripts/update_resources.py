"""Refresh official area/river tables. Run from repository root; review changes."""
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bosai.http import Http

AREA_URL = 'https://www.jma.go.jp/bosai/common/const/area.json'
RIVER_URL = 'https://www.jma.go.jp/jma/kishou/know/bosai/keiho-update2026/tech-info/zip/20260527_river-areainfo.zip'


def main():
    http = Http()
    area = json.loads(http.request('GET', AREA_URL, attempts=3).body)
    if not all(key in area for key in ('offices', 'class10s', 'class15s', 'class20s')) or len(area['class20s']) < 1000:
        raise ValueError('Unexpected area schema')
    archive = zipfile.ZipFile(io.BytesIO(http.request('GET', RIVER_URL, attempts=3).body))
    rivers = {}
    for n in archive.namelist():
        if not n.endswith('.csv'):
            continue
        b = archive.read(n)
        try:
            content = b.decode('utf-8-sig')
        except UnicodeDecodeError:
            content = b.decode('cp932')
        for row in csv.reader(io.StringIO(content)):
            if len(row) > 3 and row[1].isdigit():
                rivers[row[1]] = {'name': row[0], 'cities': [c for c in row[3::2] if c.isdigit()]}
    if len(rivers) < 300:
        raise ValueError('Unexpected river table')
    root = Path(__file__).resolve().parents[1] / 'bosai/resources'
    for name, data in [('areas', area), ('rivers', rivers)]:
        target = root / (name + '.json')
        tmp = target.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        tmp.replace(target)
    print('Official tables updated. Review the diff and resolved monitoring areas.')


if __name__ == '__main__':
    main()
