r"""
Build avatars.json for the daily prayer list.

Auth0 is the single source of avatars: every person in the input who has an email is
looked up by email in the Management API and their `picture` is downloaded. The
users.avatar_url / S3 key in the export is deliberately ignored.

Usage (in the prayerlist folder):
    python fetch_avatars.py "input_file\26th sept.json"   one or more day files
    python fetch_avatars.py                               newest file in input_file\
    python fetch_avatars.py --all                         every file in input_file\

Credentials, in the order the script tries them:
  1. AUTH0_CLIENT_ID + AUTH0_CLIENT_SECRET   -> mints a fresh token on every run.
     Read from the environment (GitHub Actions secrets) or from KEY=VALUE lines in
     env.txt. This is the path that needs no maintenance.
  2. AUTH0_TOKEN environment variable        -> a token you pasted yourself.
  3. A `Bearer ...` line in env.txt          -> same, from the curl snippet.
Management API tokens last 24 h, so 2 and 3 have to be replaced daily; 1 does not.

The credentials need audience https://we-buddhist-prod.us.auth0.com/api/v2/ AND the
read:users scope (Dashboard -> Applications -> the M2M app -> APIs -> Auth0
Management API -> Permissions -> read:users). Scopes are frozen into a token when it
is issued, so after granting a permission an existing token must be re-issued - it
never picks the permission up. A token without the scope carries no "scope" claim
and the API answers 401 Invalid token.

Merges into avatars.json (people from earlier days are kept): one entry per email,
with avatar_url, the local file, and avatar = "photo" or "initials". Photos land in
profile_images/ and are re-downloaded every run, so a changed profile picture is
picked up automatically. Generic Auth0/Gravatar initial placeholders are recorded but
not downloaded, so those people keep the drawn initials circle.
"""
import base64, glob, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

DOMAIN = "we-buddhist-prod.us.auth0.com"
ENV_FILE = "env.txt"
CHUNK = 25          # emails per bulk search query


# ---------------------------------------------------------------- token handling
def env_value(name):
    """Look a setting up in the environment, then in KEY=VALUE lines of env.txt."""
    v = os.environ.get(name)
    if v:
        return v.strip()
    if os.path.exists(ENV_FILE):
        src = open(ENV_FILE, encoding="utf-8", errors="replace").read()
        m = re.search(r"^\s*%s\s*=\s*(\S+)\s*$" % re.escape(name), src, re.M)
        if m:
            return m.group(1).strip().strip("\"'")
    return None


def mint_token(client_id, client_secret):
    """Exchange the M2M client credentials for a fresh 24 h Management API token."""
    body = json.dumps({
        "client_id": client_id,
        "client_secret": client_secret,
        "audience": "https://%s/api/v2/" % DOMAIN,
        "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request("https://%s/oauth/token" % DOMAIN, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["access_token"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        sys.exit("Could not mint a token from the client credentials:\n"
                 "  HTTP %s: %s\n\n"
                 "  access_denied  -> the M2M app is not authorised for the Management\n"
                 "                    API, or has no read:users permission on it\n"
                 "  unauthorized_client / invalid_client -> wrong client id or secret"
                 % (e.code, detail))


def load_token():
    cid, secret = env_value("AUTH0_CLIENT_ID"), env_value("AUTH0_CLIENT_SECRET")
    if cid and secret:
        return mint_token(cid, secret), "client credentials (freshly minted)"
    tok = os.environ.get("AUTH0_TOKEN")
    if tok:
        return tok.strip(), "AUTH0_TOKEN"
    if os.path.exists(ENV_FILE):
        src = open(ENV_FILE, encoding="utf-8", errors="replace").read()
        m = re.search(r"[Bb]earer\s+([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)", src)
        if m:
            return m.group(1), "env.txt (pasted token, expires 24 h after it was issued)"
    sys.exit(
        "No credentials found. Best option, never needs updating - put these in\n"
        "env.txt (or set them as environment variables / GitHub Actions secrets):\n"
        "    AUTH0_CLIENT_ID=...\n"
        "    AUTH0_CLIENT_SECRET=...\n"
        "from Dashboard -> Applications -> the M2M app -> Settings.\n"
        "Otherwise paste a 24 h token as AUTH0_TOKEN or a `Bearer ...` line in env.txt."
    )


def claims(tok):
    try:
        p = tok.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    except Exception:
        return {}


def check_token(tok):
    """Catch the two failures that otherwise cost a whole run, before any request."""
    c = claims(tok)
    if not c:
        sys.exit("Token is not a readable JWT - it was probably truncated when copied.")
    if c.get("exp", 0) < time.time():
        sys.exit("Token expired. Get a fresh one from the Management API Test tab.")
    if not str(c.get("aud", "")).rstrip("/").endswith("/api/v2"):
        sys.exit("Token audience is %r, not https://%s/api/v2/" % (c.get("aud"), DOMAIN))
    if not c.get("scope") and not c.get("permissions"):
        sys.exit(
            "This token carries no scopes, so the Management API will answer\n"
            '  401 {"error":"Unauthorized","message":"Invalid token"}\n\n'
            "Fix it in the Auth0 Dashboard, then re-issue the token:\n"
            "  Applications -> Applications -> the M2M app (client %s)\n"
            "    -> APIs tab -> Auth0 Management API -> expand -> tick read:users\n"
            "  (or: APIs -> Auth0 Management API -> Machine to Machine Applications)\n"
            "Then copy a new token from APIs -> Auth0 Management API -> Test.\n"
            'A correct token has a "scope": "read:users" claim.' % c.get("azp")
        )


# ------------------------------------------------------------------- http helpers
def api(path, tok):
    req = urllib.request.Request("https://%s/api/v2/%s" % (DOMAIN, path),
                                 headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s: %s" % (e.code, e.read().decode(errors="replace")[:300]))


def get_bytes(url):
    with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as r:
        return r.read(), r.headers.get("Content-Type", "")


def is_placeholder(url):
    """Auth0 generated initial avatars, and Gravatar falling back to one."""
    return ("cdn.auth0.com/avatars" in url) or \
           ("gravatar.com" in url and "cdn.auth0.com" in url)


def is_letter_avatar(path):
    """
    Google serves auto-generated letter avatars from the same /a/ACg8oc... urls as
    real photos, so the url cannot tell them apart - the pixels can. A letter avatar
    is a flat colour block with one glyph: very few distinct colours, one of which
    covers most of the image. Real photos here start around 1600 colours; the
    letter avatars top out near 170, so the gap is wide and the cut is safe.
    """
    try:
        from PIL import Image
    except ImportError:
        return False            # no Pillow: keep the file, better than dropping a face
    try:
        im = Image.open(path).convert("RGB")
        cols = im.getcolors(maxcolors=100000)
        if not cols:            # more than 100k colours = definitely a photo
            return False
        top = max(c[0] for c in cols) / float(im.width * im.height)
        return len(cols) < 400 and top > 0.80
    except Exception:
        return False


# ------------------------------------------------------------------------ the work
def load_rows(path):
    d = json.load(open(path, encoding="utf-8"))
    return list(d.values())[0] if isinstance(d, dict) else d

args = sys.argv[1:]
day_files = sorted(glob.glob(os.path.join("input_file", "*.json")), key=os.path.getmtime)
if "--all" in args:
    inputs = day_files or sys.exit("No day files in input_file/")
elif args:
    inputs = args
else:
    inputs = [day_files[-1]] if day_files else ["2.json"]
rows = []
for f in inputs:
    rows += load_rows(f)
    print("input: " + f)
os.makedirs("profile_images", exist_ok=True)

# merge with what earlier days already fetched; entries for today's people are refreshed
avatars = {}
if os.path.exists("avatars.json"):
    try:
        avatars = json.load(open("avatars.json", encoding="utf-8"))
    except Exception:
        avatars = {}
before = len(avatars)


def save(key, entry):
    avatars[key] = entry
    json.dump(avatars, open("avatars.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)


# 1. Everyone with an email goes to Auth0. The S3 avatar_url in 2.json is ignored
#    on purpose - Auth0 is the single source for photos.
people = {}
no_email = []
for r in rows:
    if r.get("email"):
        people.setdefault(r["email"].strip().lower(), r)
    elif r["id"] not in [x["id"] for x in no_email]:
        no_email.append(r)
need_auth0 = people
print("%d distinct people with an email -> Auth0 lookup" % len(people))
print("%d without an email -> initials circle" % len(no_email))

# 2. Auth0 lookups
token, where = load_token()
print("using token from " + where)
check_token(token)
try:
    api("users?per_page=1&fields=user_id", token)
except RuntimeError as e:
    sys.exit("Auth0 rejected the token:\n  %s" % e)

emails = sorted(need_auth0)
pics = {}
for i in range(0, len(emails), CHUNK):
    chunk = emails[i:i + CHUNK]
    q = " OR ".join('email:"%s"' % e for e in chunk)
    try:
        for u in api("users?search_engine=v3&per_page=100&fields=email,picture&q="
                     + urllib.parse.quote(q), token):
            if u.get("email") and u.get("picture"):
                pics.setdefault(u["email"].strip().lower(), u["picture"])
        print("  searched %d/%d" % (i + len(chunk), len(emails)))
    except RuntimeError as e:
        print("  bulk search failed (%s); falling back to one-by-one" % e)
        for addr in chunk:
            try:
                for u in api("users-by-email?email=" + urllib.parse.quote(addr), token):
                    if u.get("picture"):
                        pics.setdefault(addr, u["picture"])
                        break
            except RuntimeError as ex:
                print("    %s: %s" % (addr, ex))
            time.sleep(0.4)
    time.sleep(0.5)          # stay under Auth0 rate limits

# 3. One entry per person with an email, photo downloaded where there is a real one
kept = skipped = missing = failed = 0
for addr, r in sorted(people.items()):
    pic = pics.get(addr)
    entry = {
        "source": "auth0",
        "avatar_url": pic,
        "file": None,
        "downloaded": False,
        "name": r.get("posted_by"),
        "user_id": r["id"],
    }
    if not pic:
        entry["avatar"] = "initials"          # no Auth0 user or no picture field
        missing += 1
    elif is_placeholder(pic):
        entry["avatar"] = "initials"          # Auth0/Gravatar generated initials
        entry["placeholder"] = True
        skipped += 1
    else:
        try:
            data, ctype = get_bytes(pic)
            ext = ".png" if "png" in ctype else ".webp" if "webp" in ctype else ".jpg"
            fn = re.sub(r"[^a-z0-9]+", "_", addr) + ext
            path = os.path.join("profile_images", fn)
            open(path, "wb").write(data)
            if is_letter_avatar(path):
                os.remove(path)               # keep the house-style initials instead
                entry["avatar"] = "initials"
                entry["placeholder"] = True
                entry["placeholder_source"] = "google-letter-avatar"
                skipped += 1
            else:
                entry["file"] = "profile_images/" + fn
                entry["downloaded"] = True
                entry["avatar"] = "photo"
                kept += 1
        except Exception as ex:
            print("  %s: download failed (%s)" % (addr, ex))
            entry["avatar"] = "initials"
            failed += 1
    save(addr, entry)

print("\navatars.json updated: %d entries (%d before), %d new real photos this run"
      % (len(avatars), before, kept))
print("  %d generic Auth0/Gravatar placeholders -> initials circle" % skipped)
print("  %d with no Auth0 picture at all      -> initials circle" % missing)
if failed:
    print("  %d downloads failed (url recorded, initials circle for now)" % failed)
if no_email:
    print("  %d people have no email, so no Auth0 entry:" % len(no_email))
    for r in no_email:
        print("    %s (user %s)" % (r.get("posted_by"), r["id"]))
