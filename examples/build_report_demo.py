"""Build an entirely synthetic case for report screenshots, without network calls.

Run from the checkout: python examples/build_report_demo.py --data-dir ./demo-cases
Then: python -m topicstream serve --data-dir ./demo-cases
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from topicstream.cases import Cases, save_json
from topicstream.sources import Post, X, iso
from topicstream.store import Store


def build(data_dir):
    start=datetime(2026,10,29,tzinfo=timezone.utc); end=start+timedelta(days=7)
    cases=Cases(data_dir)
    try:
        detail=cases.create({'topic':'Synthetic harbor water investigation','terms':['harbor water'],'tags':[],
                             'sources':['x'],'start_utc':iso(start),'end_utc':iso(end),'budget_usd':0})
        case_id=detail['case']['id']; cfg=cases.config(case_id)
        cfg['sources']['x']['archive']=False
        cfg['alert']['uses']=20
        save_json(cases.folder(case_id)/'config.json',cfg)
        fingerprint=X(None).query_hash('harbor water','term'); posts=[]
        for day in (1,3,5):
            for episode in (9,13):
                for actor in range(21):
                    t=start+timedelta(days=day,hours=episode,seconds=actor*15)
                    posts.append(Post('x','synthetic',f'demo-{day}-{episode}-{actor}',iso(t),f'example_actor_{actor:02d}',
                                      f'Harbor water briefing {day}/{episode}: read the complete assessment and evidence at our public demonstration link.',
                                      author_id=f'example-{actor}',author_created_utc=iso(start-timedelta(days=10)),
                                      author_posts=30,author_followers=12,likes=0,matched=['harbor water'],
                                      links=[f'https://example.org/briefing/{day}/{episode}'],collected_utc=iso(end)))
            for hour in range(24):
                t=start+timedelta(days=day,hours=hour,minutes=35)
                for i in range(3):
                    posts.append(Post('x','synthetic',f'background-{day}-{hour}-{i}',iso(t),f'public_example_{hour}_{i}',
                                      f'Independent local observation {day} at hour {hour} from observer {i}.',
                                      author_id=f'background-{hour}-{i}',matched=['harbor water'] if i==0 else [],collected_utc=iso(end)))
        with Store(cfg['db']) as store:
            store.add_posts(posts)
            store.record_coverage('x',fingerprint,'harbor water',iso(start),iso(end),'partial','invented data; no API calls',len(posts),'synthetic',iso(end))
            counts=[]
            for h in range(168):
                a=start+timedelta(hours=h); b=a+timedelta(hours=1)
                counts.append(('harbor water',iso(a),80 if a.day in (30,1,3) and a.hour in (9,13) else 2,iso(b)))
            store.add_counts('x',counts,iso(end),fingerprint)
            a=start+timedelta(days=1,hours=9)
            store.add_window('x','harbor water',iso(a),iso(a+timedelta(hours=1)),80,24,iso(end),'partial','synthetic example of capped coverage',query_hash=fingerprint)
        meta=detail['case']; meta['synthetic']=True; save_json(cases.folder(case_id)/'case.json',meta)
        result=cases._analyze(case_id)
        return {'case_id':case_id,'report':cfg['report'],'posts':len(posts),'groups':len(result['groups']),
                'edges':result['recurring_edges'],'url_path':f'/api/cases/{case_id}/report'}
    finally: cases.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',default='demo-cases')
    print(json.dumps(build(parser.parse_args().data_dir),indent=2))
