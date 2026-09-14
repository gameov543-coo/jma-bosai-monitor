"""JMA XML parsing: namespace aware paths, current/legacy formats, fail closed."""
import re
import unicodedata
import xml.etree.ElementTree as ET
from .models import Alert, Bulletin, timestamp


class ParseError(ValueError):
    pass


def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper() or len(data) > 16 * 1024 * 1024:
        raise ParseError('Unsafe or oversized XML')
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise ParseError('Invalid XML') from None


def txt(e, path):
    return (e.findtext('/'.join('{*}' + x for x in path.split('/'))) or '').strip()


def severity(name):
    normalized = unicodedata.normalize('NFKC', name)
    m = re.search(r'レベル([1-5])', normalized)
    official = m.group(1) if m else ''
    if '特別警報' in name or '危険警報' in name or '氾濫危険' in name or '氾濫発生' in name or (official and int(official) >= 4):
        return 3, official
    if '警報' in name or '警戒情報' in name or '氾濫警戒' in name:
        return 2, official
    if '注意' in name:
        return 1, official
    raise ParseError('Unknown warning kind')


def family(name):
    for s in ('土砂災害', '大雨', '洪水', '高潮', '暴風雪', '暴風', '強風', '波浪', '大雪', '風雪', '雷', '融雪', '濃霧', '乾燥', 'なだれ', '低温', '霜', '着氷', '着雪'):
        if s in name:
            return {'強風': '風', '暴風': '風', '風雪': '風雪', '暴風雪': '風雪'}.get(s, s)
    raise ParseError('Unknown warning family')


class Parser:
    def __init__(self, areas):
        self.areas = areas

    def parse(self, data, url, product):
        r = xml(data)
        if r.tag != '{http://xml.kishou.go.jp/jmaxml1/}Report':
            raise ParseError('Unexpected report root')
        issued = txt(r, 'Head/ReportDateTime')
        timestamp(issued)
        if txt(r, 'Control/Status') in ('訓練', '試験'):
            return Bulletin(url, issued, [], ignored=True)
        if txt(r, 'Control/Status') != '通常':
            raise ParseError('Unknown report status')
        title = txt(r, 'Head/Title')
        summary = txt(r, 'Head/Headline/Text')
        info = txt(r, 'Head/InfoType')
        if info not in ('発表', '訂正', '取消'):
            raise ParseError('Unknown InfoType')
        if info == '取消':
            # Withdrawing a bulletin does not establish that its hazards have cleared.
            # Retain state and raise an operational incident until authoritative data is available.
            raise ParseError('Cancelled bulletin: current hazard state requires verification')
        correction = info == '訂正'
        stream = 'river' if product.startswith('VXKO') else product + ':' + txt(r, 'Control/EditorialOffice')
        alerts = []

        def add(code, kind, level, official='', suffix='', event=False, display=None):
            key = f'{stream}:{code}:{suffix}'
            alerts.append(Alert(key, display or self.areas.name(code), code, kind, level, official,
                                issued, summary[:1800], url, stream, event, correction))

        if product.startswith('VPWW') or product == 'VXWW50':
            warnings = r.findall('{*}Body/{*}Warning')
            groups = [w for w in warnings if w.get('type') == '気象警報・注意報（市町村等）' or
                      w.get('type') == '土砂災害警戒情報']
            if not groups:
                raise ParseError('Municipal warning section missing')
            for group in groups:
                for item in group.findall('{*}Item'):
                    code = txt(item, 'Area/Code')
                    if not self.areas.matches(code):
                        continue
                    kinds = item.findall('{*}Kind')
                    if not kinds:
                        raise ParseError('Warning kinds missing')
                    # Snapshot is scoped to this one municipality and product, never the whole feed.
                    active = {}
                    for k in kinds:
                        name, status = txt(k, 'Name'), txt(k, 'Status')
                        if status not in ('発表', '継続', '解除', 'なし', '発表警報・注意報はなし', '警報から注意報', '特別警報から危険警報', '特別警報から警報', '特別警報から注意報', '危険警報から警報', '危険警報から注意報'):
                            raise ParseError('Unknown warning status')
                        if product == 'VXWW50':
                            fam = '土砂災害警戒情報'
                            name = '土砂災害警戒情報' if 'レベル４' not in title else 'レベル４土砂災害危険警報（補足情報）'
                        elif txt(k, 'Code') == '00' or status in ('なし', '発表警報・注意報はなし'):
                            continue
                        else:
                            fam = family(name)
                            if product == 'VPWW53' and timestamp(issued) >= timestamp('2026-05-29T00:00:00+09:00') and fam != '洪水':
                                continue
                        if status in ('解除', 'なし', '発表警報・注意報はなし'):
                            continue
                        level, official = severity(name)
                        active[fam] = (name, level, official)
                    # A sentinel makes removed kinds explicit to the state layer, including all-clear.
                    add(code, '__snapshot__', -1)
                    for fam, (name, level, official) in active.items():
                        add(code, name, level, official, fam)
        elif product.startswith('VXKO'):
            items = r.findall('{*}Head/{*}Headline/{*}Information/{*}Item')
            forecast = [i for i in items if i.find('{*}Areas') is not None and
                        '予報区域' in i.find('{*}Areas').get('codeType', '')]
            if not forecast:
                raise ParseError('River forecast area missing')
            for item in forecast:
                river = txt(item, 'Areas/Area/Code')
                related = set(self.areas.rivers.get(river, {}).get('cities', []))
                related.update(x.text for x in r.findall('.//{*}CityCode') if x.text)
                if not related:
                    raise ParseError('Unknown river mapping')
                relevant = [c for c in related if self.areas.intersects(c)]
                if not relevant:
                    continue
                name, condition = txt(item, 'Kind/Name'), txt(item, 'Kind/Condition')
                clear = '解除' in condition or '解除' in name
                level, official = (0, '') if clear else severity(name)
                for code in sorted(relevant):
                    display = self.areas.name(code) + '（' + txt(item, 'Areas/Area/Name') + '流域）'
                    add(code, '解除' if clear else name, level, official, river, display=display)
        elif product in ('VPBS50', 'VPOA50', 'VPHW50', 'VPHW51'):
            level = 3 if any(s in title for s in ('記録的短時間', '線状降水帯発生')) else 2
            if not any(s in title for s in ('記録的短時間', '線状降水帯', '竜巻')):
                return Bulletin(url, issued, [])
            matches = {}
            for area in r.findall('{*}Head/{*}Headline/{*}Information/{*}Item/{*}Areas/{*}Area'):
                code = txt(area, 'Code')
                if self.areas.intersects(code):
                    matches[code] = txt(area, 'Name')
            if not r.findall('{*}Head/{*}Headline/{*}Information/{*}Item/{*}Areas/{*}Area'):
                raise ParseError('Event area missing')
            event_id = txt(r, 'Head/EventID') or issued
            for code, name in matches.items():
                add(code, title, level,
                    suffix=event_id + ':' + txt(r, 'Head/Serial'), event=True,
                    display=name + '（指定地域を含む発表区域）')
        else:
            raise ParseError('Unsupported product')
        return Bulletin(url, issued, alerts)
