"""Writes examples/explorer-demo.csv, a made-up sample for the co-posting explorer. Every account, post and link is invented.

What is in it, so you can check what the explorer shows you:
  demo_user_01 to 10   post the same sentence and the same link inside four minutes, on three days
  demo_user_11         same link, but spells the place differently, so its text never matches
  demo_user_12         same sentence and link, 18 to 25 minutes late
  demo_user_13         same sentence and link, more than an hour late
  demo_user_14         an ordinary account that pasted the first post, link and all, seven minutes in, once
  demo_user_15         an ordinary account that pasted the words of the first post without the link, once
  demo_user_16, 17     ordinary accounts that shared the link days later in their own words
  demo_user_18 to 24   ordinary accounts; six of them repost the second message

At ten minutes and a minimum of five, grouped by text: 3 bursts, 12 accounts (01 to 10, 14, 15).
Five minutes: 14 and 15 leave. Thirty minutes: 12 joins. Grouped by link: 11 joins and 15 leaves.
Two hours: 13 joins as well. Any link containing utm_campaign=mq7: 16 accounts (01 to 14, 16, 17).
Tick reposts in: a fourth burst appears, six ordinary accounts (18 to 23) who reposted the second message. They are not part of anything.

Run: python examples/build_explorer_demo.py"""
import csv, random
from datetime import datetime, timedelta, timezone
from pathlib import Path

R = random.Random(7)
LINK = 'https://example.org/save-the-ferry?utm_source=share&utm_campaign=mq7'
PUSHES = [(datetime(2026, 11, 2, 9, 14, tzinfo=timezone.utc), 'The Marlow Quay ferry is being cut and nobody asked us. Read this before the council votes.'),
          (datetime(2026, 11, 4, 13, 2, tzinfo=timezone.utc), 'Three villages lose their only crossing if the Marlow Quay ferry goes. Sign before Friday.'),
          (datetime(2026, 11, 6, 8, 41, tzinfo=timezone.utc), 'The council votes on the Marlow Quay ferry tomorrow. Make them say it to our faces.')]
ORDINARY = ['Anyone know if the Saturday market is still on if it rains?', 'Lost a grey glove on the quay path, shout if you see it.', 'The bakery on Mill Lane has the good rye again.',
            'Roadworks on the bridge road until Thursday, leave early.', 'Under-12s won 3 to 1 this morning. Proud of them.', 'Tide tables for the week are up at the harbour office.',
            'Looking for someone to share an allotment plot this spring.', 'Power was out on the east side for an hour last night.', 'Quiz night at the Anchor is moved to Wednesday.']
rows = []
def add(when, handle, text, link='', kind='post'): rows.append(dict(timestamp_utc=when.strftime('%Y-%m-%dT%H:%M:%SZ'), handle=handle, author_id=handle, text=text, link=link, content_type=kind))
def u(n): return 'demo_user_%02d' % n

for i, (start, text) in enumerate(PUSHES):
    for n in range(1, 11):                                                                  # the ten that move together
        add(start + timedelta(seconds=0 if n == 1 else R.randint(8, 235)), u(n), text + (' #MarlowQuay' if n % 3 else ' #SaveTheFerry'), LINK)
    add(start + timedelta(seconds=R.randint(60, 200)), u(11), text.replace('Marlow Quay', 'Marlowe Quay') + ' #MarlowQuay', LINK)     # same link, different spelling
    add(start + timedelta(minutes=R.randint(18, 24), seconds=R.randint(0, 59)), u(12), text + ' #MarlowQuay', LINK)                  # slow
    add(start + timedelta(minutes=R.randint(62, 69), seconds=R.randint(0, 59)), u(13), text + ' #MarlowQuay', LINK)                  # an hour late
    if i == 0:
        add(start + timedelta(minutes=7, seconds=12), u(14), text + ' #MarlowQuay', LINK)                                            # pasted it, link and all
        add(start + timedelta(minutes=8, seconds=3), u(15), text)                                                                    # pasted the words only
    if i == 1:
        for k, n in enumerate(range(18, 24)):                                                                                         # six ordinary accounts repost it
            add(start + timedelta(minutes=2 + k, seconds=R.randint(0, 59)), u(n), 'RT @demo_user_01: ' + text + ' #MarlowQuay', LINK, 'repost')
add(datetime(2026, 11, 3, 18, 22, 40, tzinfo=timezone.utc), u(16), 'Worth two minutes if you use the ferry. I did not know any of this.', LINK)
add(datetime(2026, 11, 5, 7, 55, 9, tzinfo=timezone.utc), u(17), 'My mum takes that ferry to her clinic. Signing.', LINK)
day0 = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)
for n in range(14, 25):                                                                     # ordinary life around it
    for k in range(4):
        add(day0 + timedelta(hours=R.randint(0, 150), minutes=R.randint(0, 59), seconds=R.randint(0, 59)), u(n), R.choice(ORDINARY))
for n, m in [(19, 21), (22, 18), (24, 20)]:
    add(day0 + timedelta(hours=R.randint(20, 140), minutes=R.randint(0, 59)), u(n), '@' + u(m) + ' I will ask at the harbour office and let you know.', kind='reply')
rows.sort(key=lambda r: (r['timestamp_utc'], r['handle']))
out = Path(__file__).with_name('explorer-demo.csv')
with open(out, 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['post_id', 'timestamp_utc', 'handle', 'author_id', 'text', 'link', 'content_type'], lineterminator='\n'); w.writeheader()
    for i, r in enumerate(rows, 1): w.writerow(dict(r, post_id='demo-%03d' % i))
print(len(rows), 'rows written to', out)
