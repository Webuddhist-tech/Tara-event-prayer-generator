#!/usr/bin/env python3
"""Look up every person in a day file in Auth0 and download their real profile photos.

usage: python scripts/fetch_avatars.py input/2026-09-26.json [--out avatars.json] [--dir profile_images]
env:   AUTH0_DOMAIN          e.g. we-buddhist-prod.us.auth0.com
       AUTH0_CLIENT_ID       Machine-to-Machine app authorised for the Auth0 Management API
       AUTH0_CLIENT_SECRET   with the read:users permission (and nothing more)

The token is requested fresh on every run (client-credentials grant), so nothing expires in the repo.
Result: avatars.json { email: {avatar: "photo"|"initials", file: "profile_images/x.jpg"|None, ...} }.
Generic Auth0/Gravatar initial images and Google letter avatars are skipped (initials circle instead).
If Auth0 is unreachable or not configured, it writes an empty avatars.json and exits 0 so the
PDF is still built (everyone gets initials).
"""
import argparse, base64, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('day_json')
ap.add_argument('--out', default='avatars.json')
ap.add_argument('--dir', default='profile_images')
A = ap.parse_args()

DOMAIN = os.environ.get('AUTH0_DOMAIN', 'we-buddhist-prod.us.auth0.com')
CID, SECRET = os.environ.get('AUTH0_CLIENT_ID'), os.environ.get('AUTH0_CLIENT_SECRET')


def give_up(why):
    # ::warning:: puts this on the run summary; buried log lines get missed and the
    # PDF then silently goes out with nobody's face on it.
    print(f'::warning title=No Auth0 avatars::{why} - building with initials only')
    print('WARNING: ' + why + ' -> building with initials only')
    json.dump({}, open(A.out, 'w'))
    sys.exit(0)


def token_scopes(tok):
    """Scopes are frozen into the token when it is minted."""
    try:
        p = tok.split('.')[1]
        c = json.loads(base64.urlsafe_b64decode(p + '=' * (-len(p) % 4)))
        return str(c.get('scope', '')).split()
    except Exception:
        return []


if not (CID and SECRET):
    give_up('AUTH0_CLIENT_ID / AUTH0_CLIENT_SECRET secrets are not set')


def http(url, data=None, headers=None, raw=False):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        return (body, r.headers.get('Content-Type', '')) if raw else json.loads(body)


try:
    tok = http(f'https://{DOMAIN}/oauth/token',
               data=json.dumps({'client_id': CID, 'client_secret': SECRET,
                                'audience': f'https://{DOMAIN}/api/v2/',
                                'grant_type': 'client_credentials'}).encode(),
               headers={'content-type': 'application/json'})['access_token']
except Exception as e:
    give_up(f'could not get an Auth0 token ({e})')

# A token minted before read:users was granted carries no scope, and the Management
# API answers those with 401 Invalid token - not the 403 you would expect - so catch
# it here rather than letting every lookup fail one at a time.
if 'read:users' not in token_scopes(tok):
    give_up('the Auth0 M2M app has no read:users permission on the Management API '
            '(minted token has no such scope; grant it under Applications -> the app '
            '-> APIs -> Auth0 Management API)')
H = {'Authorization': 'Bearer ' + tok}

d = json.load(open(A.day_json, encoding='utf-8'))
rows = list(d.values())[0] if isinstance(d, dict) else d
emails = sorted({r['email'].strip().lower() for r in rows if r.get('email')})
print(f'{len(emails)} people with an email')

pics = {}
for i in range(0, len(emails), 25):
    chunk = emails[i:i + 25]
    q = ' OR '.join(f'email:"{e}"' for e in chunk)
    try:
        for u in http(f'https://{DOMAIN}/api/v2/users?search_engine=v3&per_page=100&fields=email,picture&q='
                      + urllib.parse.quote(q), headers=H):
            if u.get('email') and u.get('picture'):
                pics.setdefault(u['email'].strip().lower(), u['picture'])
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            # 403 = scope refused, 401 = token not accepted at all. Retrying 25 more
            # times one by one cannot fix either, so stop now and say why.
            give_up(f'Auth0 rejected the token ({e.code} '
                    f'{e.read().decode(errors="replace")[:120]})')
        print(f'  search failed ({e.code}); trying one by one')
        for addr in chunk:
            try:
                for u in http(f'https://{DOMAIN}/api/v2/users-by-email?email=' + urllib.parse.quote(addr), headers=H):
                    if u.get('picture'):
                        pics.setdefault(addr, u['picture']); break
            except Exception as ex:
                print(f'    {addr}: {ex}')
            time.sleep(0.4)
    time.sleep(0.5)


def placeholder_url(u):
    return 'cdn.auth0.com/avatars' in u or ('gravatar.com' in u and 'cdn.auth0.com' in u)


def letter_avatar(path):
    try:
        from PIL import Image
        im = Image.open(path).convert('RGB')
        cols = im.getcolors(maxcolors=100000)
        if not cols:
            return False
        return len(cols) < 400 and max(c[0] for c in cols) / (im.width * im.height) > 0.80
    except Exception:
        return False


os.makedirs(A.dir, exist_ok=True)
out, kept = {}, 0
for addr in emails:
    pic = pics.get(addr)
    e = {'source': 'auth0', 'avatar_url': pic, 'file': None, 'avatar': 'initials'}
    if pic and not placeholder_url(pic):
        try:
            data, ctype = http(pic, raw=True)
            ext = '.png' if 'png' in ctype else '.webp' if 'webp' in ctype else '.jpg'
            fn = re.sub(r'[^a-z0-9]+', '_', addr) + ext
            path = os.path.join(A.dir, fn)
            open(path, 'wb').write(data)
            if letter_avatar(path):
                os.remove(path)
            else:
                e.update(file=f'{A.dir}/{fn}', avatar='photo'); kept += 1
        except Exception as ex:
            print(f'  {addr}: download failed ({ex})')
    out[addr] = e
json.dump(out, open(A.out, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
print(f'avatars.json: {len(out)} people, {kept} real photos')
