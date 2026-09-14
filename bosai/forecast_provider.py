"""Official VPWP50 outlook; retain its three-hour resolution, never interpolate."""
import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from .alert_parser import xml, txt, ParseError
from .models import timestamp

JST = timezone(timedelta(hours=9))
BASE = 'https://www.data.jma.go.jp/developer/xml/'
FALLBACK = '今後約2時間の見通し: 取得できませんでした。警報は有効です。公式情報をご確認ください。'


def windows(data, code, kind, now):
    root = xml(data)
    if root.tag != '{http://xml.kishou.go.jp/jmaxml1/}Report' or txt(root, 'Control/Status') != '通常' or txt(root, 'Head/InfoType') not in ('発表', '訂正'):
        raise ParseError('Invalid forecast report')
    issued = txt(root, 'Head/ReportDateTime')
    if not -900 <= now - timestamp(issued) <= 8 * 3600:
        return []
    properties = {'雨', '大雨浸水危険度', '土砂災害危険度'}
    for word, extra in [('風', {'風', '風危険度'}), ('雪', {'雪', '雪危険度'}),
                        ('波浪', {'波', '波危険度'}), ('高潮', {'高潮', '高潮危険度'})]:
        if word in kind:
            properties |= extra
    result = []
    for group in root.findall('{*}Body/{*}MeteorologicalInfos'):
        if group.get('type') != '量的予想時系列（市町村等）':
            continue
        for series in group.findall('{*}TimeSeriesInfo'):
            times = {}
            for d in series.findall('{*}TimeDefines/{*}TimeDefine'):
                if txt(d, 'Duration') != 'PT3H':
                    continue
                start = timestamp(txt(d, 'DateTime'))
                if start < now + 7200 and start + 10800 > now:
                    times[d.get('timeId')] = start
            for item in series.findall('{*}Item'):
                if txt(item, 'Area/Code') != code:
                    continue
                buckets = {start: [] for start in times.values()}
                for prop in item.findall('{*}Kind/{*}Property'):
                    label = txt(prop, 'Type')
                    if label not in properties:
                        continue
                    for element in prop.iter():
                        ref = element.get('refID')
                        if ref not in times:
                            continue
                        value = txt(element, 'Name') or element.get('description', '')
                        if value:
                            metric = element.get('type', label)
                            # Keep labels of local subdivisions (e.g. land/sea) explicit.
                            local = next((n for n in prop.findall('.//{*}Local') if element in list(n.iter())), None)
                            scope = txt(local, 'AreaName') if local is not None else ''
                            row = f'{metric}{"（" + scope + "）" if scope else ""}: {value}'
                            if row not in buckets[times[ref]]:
                                buckets[times[ref]].append(row)
                for start, rows in buckets.items():
                    if rows:
                        result.append((start, issued, rows))
    return result


class ForecastService:
    def __init__(self, http, areas):
        self.http, self.areas = http, areas
        self.cached_at = 0
        self.documents = {}

    def refresh(self, now):
        if now - self.cached_at < 300:
            return
        # Cache failures as well to avoid multiplying requests during a warning burst.
        self.cached_at = now
        self.documents = {}
        entries = {}
        for feed in ('regular_l.xml', 'regular.xml'):
            response = self.http.request('GET', BASE + 'feed/' + feed)
            if response.status != 200:
                raise ParseError('Forecast feed unavailable')
            root = xml(response.body)
            if root.tag != '{http://www.w3.org/2005/Atom}feed':
                raise ParseError('Invalid forecast feed')
            for entry in root.findall('{*}entry'):
                url = txt(entry, 'id')
                parts = urlsplit(url)
                if parts.scheme != 'https' or parts.netloc != 'www.data.jma.go.jp' or not parts.path.startswith('/developer/xml/data/'):
                    raise ParseError('Untrusted forecast URL')
                for office in self.areas.offices:
                    if parts.path.endswith('_VPWP50_' + office + '.xml'):
                        entries[url] = (timestamp(txt(entry, 'updated')), office)
        for office in self.areas.offices:
            latest = sorted(((stamp, url) for url, (stamp, region) in entries.items() if region == office), reverse=True)[:2]
            docs = []
            for _, url in latest:
                response = self.http.request('GET', url)
                if response.status != 200:
                    raise ParseError('Forecast document unavailable')
                docs.append((url, response.body))
            self.documents[office] = docs

    def outlook(self, alert, now=None):
        now = time.time() if now is None else now
        try:
            self.refresh(now)
            offices = self.areas.ancestors(alert.area_code) & self.areas.offices
            merged = {}
            for office in offices:
                for url, data in self.documents.get(office, []):
                    for start, issued, rows in windows(data, alert.area_code, alert.kind, now):
                        if start not in merged or timestamp(issued) > timestamp(merged[start][0]):
                            merged[start] = (issued, rows, url)
            if not merged:
                return FALLBACK
            lines = ['今後約2時間に重なる公式予報（3時間単位・JST）']
            for start, (issued, rows, _) in sorted(merged.items()):
                a = datetime.fromtimestamp(start, JST).strftime('%m/%d %H:%M')
                b = datetime.fromtimestamp(start + 10800, JST).strftime('%H:%M')
                lines.append(f'{a}〜{b}／予報発表 {issued}')
                lines.extend(rows[:8])
            if min(merged) > now or max(merged) + 10800 < now + 7200:
                lines.append('※今後約2時間のうち、取得できていない時間帯があります。')
            lines.append('※予報の危険度が低くても、現在の警報の解除を意味しません。')
            lines.extend('予報出典: ' + url for url in dict.fromkeys(v[2] for v in merged.values()))
            return '\n'.join(lines)[:1600]
        except Exception as e:
            logging.getLogger(__name__).warning('forecast_unavailable type=%s', type(e).__name__)
            return FALLBACK
