"""Collected posts as CSV, in the column layout that import-csv reads back and the co-posting explorer recognises.

The export is what the report analyses: the stored posts inside the configured interval. One row per post. Reposts are
marked as such in content_type, so a reader can leave them out (the explorer does, to begin with) or study them."""
import csv, io

COLUMNS = ['post_id', 'source', 'handle', 'account_id', 'timestamp_utc', 'content_type', 'lang', 'text', 'link', 'links',
           'referenced_post_id', 'in_reply_to', 'likes', 'reposts', 'replies', 'url', 'account_created_utc', 'followers', 'posts_total', 'matched']
PROFILE_COLUMNS = ['handle', 'account_id', 'created_utc', 'followers', 'posts_total']

def content_type(p):
    ref = p.get('reference_type')
    if p.get('is_repost') or ref == 'repost': return 'repost'
    if ref in ('reply', 'quote'): return ref
    return 'reply' if p.get('is_reply') else 'post'

def _n(v): return '' if v is None else v

def rows(posts):
    ids = {p['post_id'] for p in posts}
    for p in posts:
        kind = content_type(p); links = p.get('links') or []; ref = p.get('referenced_post_id')
        yield {'post_id': p['post_id'], 'source': p['source'], 'handle': p['author'], 'account_id': _n(p.get('author_id')), 'timestamp_utc': p['created_utc'],
               'content_type': kind, 'lang': _n(p.get('lang')), 'text': p['text'], 'link': links[0] if links else '', 'links': ' '.join(links),
               'referenced_post_id': _n(ref), 'in_reply_to': ref if kind == 'reply' and ref in ids else '',     # only when the parent is in this file: import-csv resolves it to an account
               'likes': _n(p.get('likes')), 'reposts': _n(p.get('reposts')), 'replies': _n(p.get('replies')), 'url': _n(p.get('url')),
               'account_created_utc': _n(p.get('author_created_utc')), 'followers': _n(p.get('author_followers')), 'posts_total': _n(p.get('author_posts')),
               'matched': ' '.join(p.get('matched') or [])}

def _csv(columns, records):
    out = io.StringIO(); w = csv.DictWriter(out, fieldnames=columns, lineterminator='\r\n'); w.writeheader(); w.writerows(records); return out.getvalue()

def posts_csv(posts): return _csv(COLUMNS, rows(posts))

def profiles_csv(posts):
    """One row per account that has any profile fact; posts arrive oldest first, so an account's newest record wins."""
    seen = {}
    for p in posts:
        if p.get('author_created_utc') or p.get('author_followers') is not None or p.get('author_posts') is not None:
            seen[p['author']] = {'handle': p['author'], 'account_id': _n(p.get('author_id')), 'created_utc': _n(p.get('author_created_utc')),
                                 'followers': _n(p.get('author_followers')), 'posts_total': _n(p.get('author_posts'))}
    return _csv(PROFILE_COLUMNS, [seen[h] for h in sorted(seen)])
