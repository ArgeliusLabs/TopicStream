"""Stable identities and conservative URL normalization shared by every detector."""
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit


def account_key(post):
    source = post.get('source') or 'import'
    if source == 'mastodon':
        actor = post.get('author_uri')
        if actor:
            return 'mastodon:' + actor
        handle = post.get('author', '').lstrip('@')
        if '@' not in handle:
            handle += '@' + (post.get('instance') or 'unknown')
        # Old Mastodon numeric IDs are local to the observing server.
        return 'mastodon:handle:' + handle.lower()
    stable = post.get('author_id')
    return f'{source}:id:{stable}' if stable else f'{source}:handle:{post.get("author", "").lstrip("@").lower()}'


def post_key(post):
    return post.get('key') or f'{post.get("source", "import")}:{post.get("post_id") or digest([post.get("author"), post.get("created_utc"), post.get("text")])}'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def normalized_url(value):
    """Normalize scheme/host only. Paths, queries, and token case are meaningful."""
    try:
        u = urlsplit(value.strip())
        if u.scheme.lower() not in ('http', 'https') or not u.hostname or u.username or u.password:
            return ''
        host = u.hostname.lower()
        if ':' in host:
            host = '[' + host + ']'
        port = u.port
        if port and (u.scheme.lower(), port) not in (('http', 80), ('https', 443)):
            host += ':' + str(port)
        return urlunsplit((u.scheme.lower(), host, u.path or '/', u.query, ''))
    except (ValueError, AttributeError):
        return ''


def safe_url(value):
    return normalized_url(value or '')
