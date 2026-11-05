"""topicstream: a small, honest version of the "topic stream" dashboards that commercial social-listening tools sell.

Tracks a set of hashtags and terms across platforms, stores every post it sees in SQLite, and renders a report with
the numbers that matter for coordinated-behaviour work: uses per day, originating accounts per day, velocity alerts,
uses-per-account ratio, co-occurring tags, shared links, and same-text bursts.

Standard library only. Mastodon needs no credentials. Bluesky needs a free app password. X is pay-per-use.
"""
__version__ = '0.3.3'
