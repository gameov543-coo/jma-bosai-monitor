import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from .alert_parser import xml, ParseError, txt
from .models import timestamp

BASE = 'https://www.data.jma.go.jp/developer/xml/'
PRODUCTS = {'VPWW53', 'VPWW55', 'VPWW56', 'VPWW57', 'VPWW58', 'VPWW59', 'VPWW60', 'VPWW61',
            'VXWW50', 'VPBS50', 'VPOA50', 'VPHW50', 'VPHW51'}


@dataclass(frozen=True)
class Entry:
    url: str
    product: str
    updated: float
    region: str


class JmaProvider:
    def __init__(self, http, store, areas):
        self.http, self.store, self.areas = http, store, areas

    def entries(self, long=False):
        name = 'extra_l.xml' if long else 'extra.xml'
        url = BASE + 'feed/' + name
        r = self.http.request('GET', url, attempts=3)
        if r.status != 200:
            raise ParseError('Feed HTTP status invalid')
        root = xml(r.body)
        if root.tag != '{http://www.w3.org/2005/Atom}feed':
            raise ParseError('Not an Atom feed')
        updated = timestamp(txt(root, 'updated'))
        if time.time() - updated > (7200 if long else 3600):
            raise ParseError('Stale JMA feed')
        result = []
        for e in root.findall('{*}entry'):
            link = e.find('{*}link')
            u = link.get('href', '') if link is not None else txt(e, 'id')
            p = urlsplit(u)
            if p.scheme != 'https' or p.netloc != 'www.data.jma.go.jp' or not p.path.startswith('/developer/xml/data/'):
                raise ParseError('Unexpected JMA document URL')
            m = re.search(r'_([A-Z]{4}\d{2})_([^/]+)\.xml$', p.path)
            if not m:
                continue
            product, region = m.groups()
            if product not in PRODUCTS and not product.startswith('VXKO'):
                continue
            # Geographic filtering uses official office codes, never substring matching in headlines.
            if not product.startswith('VXKO') and region not in self.areas.offices:
                continue
            result.append(Entry(u, product, timestamp(txt(e, 'updated')), region))
        return result

    def fetch(self, entry):
        r = self.http.request('GET', entry.url, attempts=3)
        if r.status != 200:
            raise ParseError('Document HTTP status invalid')
        return r.body

    def collect(self):
        last = float(self.store.meta('last_poll', '0'))
        now = time.time()
        long = now - float(self.store.meta('last_long', '0')) >= 3600 or now - last > 600
        entries = self.entries(long=False)
        if long:
            merged = {e.url: e for e in self.entries(long=True)}
            merged.update({e.url: e for e in entries})
            entries = list(merged.values())
        # Cold start: obtain the latest snapshot for each product/office or river forecast.
        # Feed history is not a list of currently active warnings.
        if not last:
            latest = {}
            events = []
            for e in entries:
                if e.product in ('VPBS50', 'VPOA50', 'VPHW50', 'VPHW51'):
                    if now - e.updated <= 10800:
                        events.append(e)
                else:
                    key = (e.product, e.region)
                    if key not in latest or latest[key].updated < e.updated:
                        latest[key] = e
            entries = list(latest.values()) + events
        return sorted((e for e in entries if not self.store.seen(e.url)), key=lambda e: (e.updated, e.url)), long
