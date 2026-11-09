#!/usr/bin/env python3
"""Scheduled Telegram publisher. Python standard library only."""
import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
POSTS = ROOT / 'data' / 'posts.json'
STATE = ROOT / 'data' / 'sent.json'
CHANNEL = '@kvadro_biznes'
MOSCOW = dt.timezone(dt.timedelta(hours=3))
START = dt.datetime(2026, 11, 10, 0, 0, tzinfo=MOSCOW)
END = dt.datetime(2026, 12, 10, 0, 0, tzinfo=MOSCOW)


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True, text=True)


def save_state(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    git('config', 'user.name', 'tehnokovsh-publisher[bot]')
    git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    git('add', 'data/sent.json')
    git('commit', '-m', 'Record Telegram publication')
    # Concurrency group in workflow serializes runs. Push failure is a hard error.
    git('push', 'origin', 'HEAD:main')


def send(token, content):
    url = 'https://api.telegram.org/bot' + token + '/sendMessage'
    body = json.dumps({'chat_id': CHANNEL, 'text': content, 'disable_web_page_preview': True}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    # Never print the full URL or HTTP exception: URL contains the bot token.
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            payload = json.load(res)
    except urllib.error.HTTPError as exc:
        print('Telegram HTTP status:', exc.code, file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print('Telegram request failed:', type(exc).__name__, file=sys.stderr)
        sys.exit(1)
    if not payload.get('ok'):
        print('Telegram API returned unsuccessful result', file=sys.stderr)
        sys.exit(1)
    return payload['result']['message_id']


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dry-run', action='store_true', help='Show due posts, never send')
    p.add_argument('--validate', action='store_true', help='Validate 75 posts and timestamps')
    args = p.parse_args()
    posts = json.loads(POSTS.read_text(encoding='utf-8'))
    assert len(posts) == 75, 'Expected exactly 75 posts'
    assert len({p['id'] for p in posts}) == 75, 'Duplicate IDs'
    assert all(len(p['text']) <= 4096 for p in posts), 'Telegram message exceeds 4096 characters'
    for post in posts:
        stamp = dt.datetime.fromisoformat(post['at'])
        assert stamp.tzinfo is not None and stamp.utcoffset() == dt.timedelta(hours=3)
        assert START <= stamp < END
    if args.validate:
        print('VALID: 75 posts, 30 days, Moscow UTC+03, unique IDs, message lengths OK')
        return
    now = dt.datetime.now(dt.timezone.utc).astimezone(MOSCOW)
    if now < START:
        print('Publication has not started; Moscow now:', now.isoformat())
        return
    if now >= END:
        print('Campaign completed: outside 30-day publication window')
        return
    state = json.loads(STATE.read_text(encoding='utf-8'))
    sent = state['sent']
    due = [x for x in posts if x['id'] not in sent and dt.datetime.fromisoformat(x['at']) <= now]
    due.sort(key=lambda x: x['at'])
    print('Moscow time:', now.isoformat(), '| due:', len(due), '| already sent:', len(sent))
    if args.dry_run:
        for item in due[:5]:
            print('DUE:', item['id'], item['at'], item['text'].splitlines()[0])
        return
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        raise RuntimeError('Missing TELEGRAM_BOT_TOKEN secret')
    # Maximum 5 messages per run prevents a flood after a long outage.
    for item in due[:5]:
        message_id = send(token, item['text'])
        sent[item['id']] = {'message_id': message_id, 'sent_at': dt.datetime.now(MOSCOW).isoformat()}
        save_state(state)
        print('Published:', item['id'], 'message_id:', message_id)
        time.sleep(1)


if __name__ == '__main__':
    main()
