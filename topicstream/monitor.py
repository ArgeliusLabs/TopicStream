"""Evaluate every closed interval; persisted identities suppress duplicate alerts."""
from collections import defaultdict
from datetime import timedelta
from statistics import mean
from .sources import parse_time, iso
from .identity import account_key


def count_alerts(rows, now, threshold=200, ratio=10, min_uses=10):
    by=defaultdict(list)
    for row in rows:
        if parse_time(row['start_utc'])+timedelta(hours=1)<=now:
            by[row['tag']].append(row)
    out=[]
    for label,series in by.items():
        history=[]
        for row in sorted(series,key=lambda r:r['start_utc']):
            baseline=mean(history[-168:]) if history else None
            reasons=[]
            if row['uses']>=threshold: reasons.append(f'{row["uses"]} API-reported matches exceeds {threshold}')
            if len(history)>=6 and baseline and row['uses']>=max(min_uses,ratio*baseline): reasons.append(f'{row["uses"]/baseline:.1f}x preceding observed hours')
            if reasons: out.append(dict(tag=label,start=row['start_utc'],uses=row['uses'],accounts=None,baseline=baseline,reasons=reasons))
            history.append(row['uses'])
    return out


def post_alerts(posts, now, minutes=30, threshold=200, ratio=10, concentration=5, min_uses=10):
    if minutes<1: raise ValueError('Alert interval must be positive')
    buckets=defaultdict(list)
    for p in posts:
        seconds=int(parse_time(p['created_utc']).timestamp()); start=parse_time(p['created_utc'])-timedelta(seconds=seconds%(minutes*60))
        if start+timedelta(minutes=minutes)>now: continue
        for tag in p['matched']: buckets[(p['source'],tag,iso(start))].append(p)
    histories=defaultdict(list); out=[]
    for (source,tag,start),rows in sorted(buckets.items()):
        history=histories[(source,tag)]; baseline=mean(history[-168:]) if history else None
        n=len(rows); accounts=len({account_key(p) for p in rows}); reasons=[]
        if n>=threshold: reasons.append(f'{n} observed posts exceeds {threshold}')
        if len(history)>=6 and baseline and n>=max(min_uses,ratio*baseline): reasons.append(f'{n/baseline:.1f}x preceding observed nonempty intervals')
        if n>=2*min_uses and accounts and n/accounts>=concentration: reasons.append(f'{n/accounts:.1f} observed posts per account')
        if reasons: out.append(dict(source=source,tag=tag,start=start,uses=n,accounts=accounts,baseline=baseline,reasons=reasons))
        history.append(n)
    return out
