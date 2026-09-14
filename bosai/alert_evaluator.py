from .models import Alert


def changed(old: Alert | None, new: Alert):
    if old is None:
        return new.level > 0
    return old.signature() != new.signature() or (new.correction and old.summary != new.summary)


def should_notify(old, new, minimum):
    return changed(old, new) and max(old.level if old else 0, new.level) >= minimum


def message(old, new):
    labels = {0: '解除・取消', 1: '状況確認', 2: '警戒', 3: '非常に危険'}
    before = old.kind if old and old.level else '記録なし／未発表'
    level = f'通知重要度 LEVEL {new.level}: {labels[new.level]}' if new.level else labels[0]
    official = f'気象庁の警戒レベル: {new.official_level}' if new.official_level else '気象庁の警戒レベル: 数値の記載なし'
    return (f'【防災情報】{level}\n地域: {new.area}\n情報種別: {new.kind}\n発表時刻: {new.issued_at}\n'
            f'{official}\n変化: {before} → {new.kind}' + ('（訂正・取消）' if new.correction else '') +
            f'\n要約: {new.summary}\n公式情報: {new.url}\n' +
            (new.forecast + '\n' if new.forecast else '') +
            '気象庁防災情報: https://www.jma.go.jp/bosai/\n'
            '※通知重要度は本システム独自の3段階です。自治体の避難情報も確認してください。')
