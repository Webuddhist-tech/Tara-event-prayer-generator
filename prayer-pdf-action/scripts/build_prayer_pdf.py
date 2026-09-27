#!/usr/bin/env python3
"""Build the A3 'Prayer Requests' card PDF for the Lama.

usage: python3 build_prayer_pdf.py --json 2.json [--avatars avatars.json] [--avatar-dir profile_images]
                                   --fonts FONTDIR --out Prayer_Requests_<date>_A3.pdf [--date "25 September 2026"]
The header shows "Day: n" (English + Tibetan) top right, counted from DAY_ONE below.
FONTDIR must contain GARA.TTF, GARABD.TTF, GARAIT.TTF and "Monlam Uni OuChan2.ttf".
Needs: Pillow, playwright (python) with Chromium, Noto Serif CJK SC/TC + Noto Color Emoji installed.
"""
import argparse, json, re, html, os, hashlib, datetime, shutil, tempfile
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument('--json', required=True)
ap.add_argument('--avatars')
ap.add_argument('--avatar-dir')
ap.add_argument('--fonts', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--date')
ap.add_argument('--logo', help='WeBuddhist logo+wordmark image (png, dark text) shown at the end')
ap.add_argument('--skip', default='no sound la|no video la', help='|-separated exact messages to drop (lowercase)')
A = ap.parse_args()

data = json.load(open(A.json, encoding='utf-8'))
rows = list(data.values())[0] if isinstance(data, dict) else data
SKIP = {s.strip() for s in A.skip.split('|') if s.strip()}

DAY_ONE = datetime.date(2026, 9, 25)      # Zabtik Drolchok day 1 (IST); the header badge counts from here

ts = min((r['created_at'] for r in rows), default=None)
IST_DAY = ((datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
            + datetime.timedelta(hours=5, minutes=30)).date() if ts else None)
if A.date:
    DATE = A.date
    for fmt in ('%Y-%m-%d', '%d %B %Y', '%d %b %Y'):
        try:
            IST_DAY = datetime.datetime.strptime(A.date.strip(), fmt).date()
            break
        except ValueError:
            pass
else:
    DATE = f"{IST_DAY.day} {IST_DAY:%B %Y}"

# "Day: 3" top right of the header, English + Tibetan (Tibetan digits). Hidden if the day is unknown.
BO_DIGITS = str.maketrans('0123456789', '༠༡༢༣༤༥༦༧༨༩')
DAYNO = (IST_DAY - DAY_ONE).days + 1 if IST_DAY else 0
DAYTAG = ('' if DAYNO < 1 else
          f'<div class="day"><span class="bo">ཉིན། {str(DAYNO).translate(BO_DIGITS)}</span>'
          f'<span class="en">Day: {DAYNO}</span>'
          f'<span class="zhd">第 {DAYNO} 天</span></div>')
DAYLINE = f'<div class="dayline">{DAYTAG}</div>' if DAYTAG else ''
ZHDATE = f'{IST_DAY.year}年{IST_DAY.month}月{IST_DAY.day}日' if IST_DAY else ''

HAN = re.compile(r'^[\u3400-\u9fff]+$')
EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27bf\ufe0f\U0001F3FB-\U0001F3FF\u200d]')
BO = r'([\u0f00-\u0fff][\u0f00-\u0fff ]*)'
ZH = r'([\u3000-\u9fff\uff00-\uffef][\u3000-\u9fff\uff00-\uffef0-9\uff0c\u3002\uff01\uff1f\uff1a\uff1b\u3001\u201c\u201d\uff08\uff09]*)'

def name(n):
    n = re.sub(r'\s+', ' ', n or '').strip()
    if n.lower().startswith('webuddhist'): return 'WeBuddhist Member'
    n = re.sub(r'\s*_user_\d+', '', n).strip()
    parts = n.split(' ')
    if len(parts) == 2 and parts[0].lower() == parts[1].lower() and parts[0].isascii(): parts = [parts[0]]
    if len(parts) == 2 and all(HAN.match(p) for p in parts): return parts[1] + parts[0]   # surname first
    if len(parts) == 2 and parts[0] in ('～', '~'): return parts[1]
    return ' '.join(p.capitalize() if re.match(r'^[A-Za-z]+$', p) and (p.isupper() or p.islower()) else p for p in parts)

def msg(m):
    m = EMOJI.sub('', re.sub(r'\[(?:[A-Za-z]{2,15}|[\u4e00-\u9fff]{1,4})\]', '', m))   # WeChat codes like [合十] [Worship]
    lines = [re.sub(r'[ \t]+', ' ', l).strip() for l in m.strip().split('\n')]
    t = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()
    e = re.sub(BO, r'<span class="bo">\1</span>', html.escape(t))
    e = re.sub(ZH, r'<span class="zh">\1</span>', e)
    return e.replace('\n', '<br>')

def nm_html(n): return re.sub(BO, r'<span class="bo">\1</span>', html.escape(n))

PAL = ['#7a1f1f', '#9c5a1a', '#4f6b3a', '#2f5d6b', '#6b3f6b', '#8a6d1f', '#5a4636', '#a0412d']
def initials(n):
    if n == 'WeBuddhist Member': return 'WB'
    if re.match(r'^[\u0f00-\u0fff]', n): return '<span class="bo">' + n.split('\u0f0b')[0] + '</span>'
    if re.match(r'^[\u3400-\u9fff]', n): return n[0]
    w = [x for x in n.split() if x]
    return (w[0][0] + (w[1][0] if len(w) > 1 else '')).upper() if w else '?'

AV = {}
if A.avatars and os.path.exists(A.avatars):
    AV = {k.lower(): v for k, v in json.load(open(A.avatars, encoding='utf-8')).items()}
AVDIR = A.avatar_dir or (os.path.join(os.path.dirname(A.avatars), 'profile_images') if A.avatars else None)

def real_photo(p):  # Google/Auth0 letter tiles are flat 1-2 colour PNGs -> treat as no photo
    if not p.lower().endswith('.png'): return True
    im = Image.open(p).convert('RGB').resize((64, 64))
    c = sorted(im.getcolors(4096) or [], reverse=True)
    return sum(n for n, _ in c[:2]) / 4096 < 0.7

PHOTOS = 0
def avatar(n, email):
    global PHOTOS
    v = AV.get((email or '').lower())
    if v and v.get('file') and AVDIR:
        p = os.path.abspath(os.path.join(AVDIR, os.path.basename(v['file'])))
        if os.path.exists(p) and real_photo(p):
            PHOTOS += 1
            return f'<img class="av" src="file://{p}">'
    c = PAL[int(hashlib.md5(n.encode()).hexdigest(), 16) % len(PAL)]
    return f'<span class="av ini" style="background:{c}">{initials(n)}</span>'

import unicodedata, difflib
WECHAT = re.compile(r'\[(?:[A-Za-z]{2,15}|[\u4e00-\u9fff]{1,4})\]')
def norm(t):
    """Text used only for duplicate detection: no emojis/WeChat codes/punctuation/spaces, NFKC, lower-case."""
    t = unicodedata.normalize('NFKC', EMOJI.sub('', WECHAT.sub('', t))).lower()
    return ''.join(ch for ch in t if unicodedata.category(ch)[0] in 'LNM')

def elen(t): return len(t) + sum(1 for ch in t if ord(ch) > 0x2E80 or 0x0F00 <= ord(ch) <= 0x0FFF)   # CJK/Tibetan count double
NEAR = 0.90        # same person, same day, >= 90% similar -> one card
items = []; DROPPED = []; BYUSER = {}
for r in rows:
    raw = (r.get('message') or '').strip()
    if raw.lower() in SKIP: DROPPED.append(('feedback', raw)); continue
    m = msg(raw)
    if not re.sub('<[^>]+>', '', m).strip(): DROPPED.append(('emoji-only/empty', raw)); continue
    nm = name(r.get('posted_by'))
    who = r.get('id') or (r.get('email') or '').lower() or nm          # user id first: display names collide
    key = norm(raw)
    dup = None
    for j in BYUSER.get(who, []):
        k2 = items[j][3]
        if key == k2 or (min(elen(key), elen(k2)) >= 20 and difflib.SequenceMatcher(None, key, k2).ratio() >= NEAR):
            dup = j; break
    if dup is not None:
        old = items[dup]
        if len(key) > len(old[3]):       # keep the fuller version (first one wins a tie), in the first one's place
            items[dup] = (nm, m, old[2], key, raw)
            DROPPED.append(('duplicate', nm + ': ' + old[4][:40]))
        else:
            DROPPED.append(('duplicate', nm + ': ' + raw[:40]))
        continue
    BYUSER.setdefault(who, []).append(len(items))
    items.append((nm, m, avatar(nm, r.get('email')), key, raw))
items = [(n, m, a) for n, m, a, _, _ in items]

def WL(m):
    t = re.sub('<[^>]+>', '', m)
    return len(t) + sum(1 for ch in t if ord(ch) > 0x2E80 or 0x0F00 <= ord(ch) <= 0x0FFF) * 1.2
def WIDE(m):
    w = WL(m)
    return ' wide w5' if w > 2600 else ' wide w3' if w > 1300 else ' wide w2' if w > 520 else ''

entries = ''.join(
    f'<div class="e{WIDE(m)}"><div class="hd">{a}<div class="id"><span class="who">{nm_html(n)}</span>'
    f'<span class="n">No. {i:02d}</span></div></div><div class="m">{m}</div></div>'
    for i, (n, m, a) in enumerate(items, 1))

CLOSING = (
    '<div class="end"><span class="v">རྗེ་བཙུན་འཕགས་མ་སྒྲོལ་མ་ཁྱེད་མཁྱེན་ནོ།།</span>'
    '<span class="v">འཇིགས་དང་སྡུག་བསྔལ་ཀུན་ལས་སྐྱབས་དུ་གསོལ།།</span>'
    '<span class="mantra">ཨོཾ་ཏཱ་རེ་ཏུཏྟཱ་རེ་ཏུ་རེ་སྭཱ་ཧཱ།</span>'
    '<span class="tr tc" lang="zh-Hant">至尊聖度母祈以大悲攝受，<br>祈願救度我們脫離一切怖畏與苦難。<br>嗡 達咧 都達咧 都咧 梭哈</span>'
    '<span class="tr en">Noble Arya Tara, embrace us with compassion;<br>Protect us from every fear and suffering.<br>Oṃ Tāre Tuttāre Ture Svāhā</span>'
    '<span class="emo2">🙏🙏🙏</span>__BRAND__</div>')

import base64, mimetypes
BRAND = ''
if A.logo and os.path.exists(A.logo):
    mt = mimetypes.guess_type(A.logo)[0] or 'image/png'
    b64 = base64.b64encode(open(A.logo, 'rb').read()).decode()
    BRAND = f'<div class="brand"><img src="data:{mt};base64,{b64}" alt="WeBuddhist"></div>'
CLOSING = CLOSING.replace('__BRAND__', '')   # logo lives in the page footer now

CSS = '''
@font-face{font-family:G;src:url(GARA.TTF)}
@font-face{font-family:G;src:url(GARABD.TTF);font-weight:700}
@font-face{font-family:G;src:url(GARAIT.TTF);font-style:italic}
@font-face{font-family:Bo;src:url("Monlam Uni OuChan2.ttf")}
@page{size:A3;margin:16mm 15mm 18mm}
:root{--ink:#2b1d14;--maroon:#7a1f1f;--gold:#b8872b;--rule:#e2d3b5;--card:#fdf8ee}
body{margin:0;font-family:G,Bo,"Noto Serif CJK SC",serif;color:var(--ink);font-size:10.5pt;line-height:1.42;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.zh{font-size:.9em}
.bo{font-family:Bo;font-size:1.12em;line-height:1.35}
header{position:relative;text-align:center;padding:4mm 0 7mm;border-bottom:2px solid var(--gold)}
header .dayline{position:absolute;right:0;top:2.5mm}   /* page 1: top-right beside the title; pages 2+: own line */
.day{display:inline-block;text-align:center;line-height:1.2;border:1px solid var(--rule);border-top:2.5px solid var(--maroon);border-radius:2mm;padding:1.6mm 3.2mm;background:var(--card);box-sizing:border-box}
.day .en{display:block;font-size:13pt;letter-spacing:.08em;color:var(--gold);margin-top:.8mm}
.day .zhd{display:block;font-family:'Noto Serif CJK TC',serif;font-size:11pt;color:var(--gold);margin-top:.5mm}
.day .bo{display:block;font-family:Bo;font-size:14pt;line-height:1.3;color:var(--maroon)}
header .t{font-family:Bo;font-size:34pt;color:var(--maroon);line-height:1.2}
header h1{font-weight:400;font-size:32pt;letter-spacing:.16em;text-transform:uppercase;margin:1mm 0;color:var(--maroon)}
header .subbo{font-family:Bo;font-size:19pt;color:var(--maroon);line-height:1.4;margin-top:2mm}
header .sub{font-style:italic;font-size:15pt;color:#5a4636;margin-top:1mm}
header .zht{font-family:'Noto Serif CJK TC',serif;font-size:17pt;letter-spacing:.3em;color:var(--maroon);margin-top:-.5mm}
header .subzh{font-family:'Noto Serif CJK TC',serif;font-size:13pt;color:#5a4636;margin-top:1mm}
header .zhm{font-family:'Noto Serif CJK TC',serif;letter-spacing:.08em}
header .meta{margin-top:3mm;font-size:12pt;letter-spacing:.22em;text-transform:uppercase;color:var(--gold)}
.orn{color:var(--gold);font-size:14pt;letter-spacing:.6em;margin-top:2mm}
.page{position:relative;width:267mm;height:384mm;break-after:page;overflow:hidden}
.page:last-child{break-after:auto}
#pool{position:absolute;left:-9999mm;top:0;width:267mm}
.placed{position:absolute;margin:0!important}
.e{background:var(--card);border:1px solid var(--rule);border-top:2.5px solid var(--maroon);border-radius:2mm;padding:2.6mm 3mm 3mm;box-sizing:border-box}
.e.wide .m{column-gap:5mm;column-rule:.6px solid var(--rule)}
.e.w2 .m{column-count:2}.e.w3 .m{column-count:3}.e.w5 .m{column-count:5}
.hd{display:flex;align-items:center;gap:2.2mm;border-bottom:.7px solid var(--rule);padding-bottom:1.5mm;margin-bottom:1.8mm}
.n{display:block;color:var(--gold);font-size:7.5pt;letter-spacing:.12em;text-transform:uppercase}
.id{display:flex;flex-direction:column;line-height:1.25;min-width:0}
.av{flex:0 0 9.5mm;width:9.5mm;height:9.5mm;border-radius:50%;object-fit:cover;border:1.5px solid var(--gold);box-sizing:border-box}
.ini{display:flex;align-items:center;justify-content:center;color:#fdf8ee;font-weight:700;font-size:10pt;letter-spacing:.03em;font-family:G,"Noto Serif CJK SC",serif}
.ini .bo{font-size:9.5pt;line-height:1}
.who{font-weight:700;color:var(--maroon);font-size:11pt;letter-spacing:.03em}
.m{font-size:10.5pt}
.end{box-sizing:border-box;text-align:center;padding:6mm 2mm 2mm}
.end .v{display:block;font-family:Bo;color:var(--maroon);font-size:17pt;line-height:1.5}
.end .mantra{display:block;font-family:Bo;color:var(--gold);font-size:19pt;line-height:1.5;margin-top:1.5mm}
.end .tr{display:block;margin-top:3.5mm;font-size:11pt;line-height:1.55;color:#5a4636}
.end .tr.en{font-style:italic;font-size:14pt;line-height:1.45}   /* Garamond runs small: match the Chinese/Tibetan visually */
.end .tc{font-family:G,'Noto Serif CJK TC',serif;font-size:11pt}
.brand{display:flex;align-items:center;justify-content:center;gap:3mm;margin-top:7mm}
.brand img{height:11mm;width:auto}
.end .emo2{display:block;font-family:'Noto Color Emoji';font-size:13pt;margin-top:3.5mm;letter-spacing:.25em;text-indent:.25em}
'''

# Masonry packer: 5 columns per A3 page; long prayers span 2/3/5 columns; nothing splits across pages.
JS = '''
window.layout=function(){
 const N=5, MM=96/25.4, W=267*MM, H=384*MM, G=4.5*MM, CW=(W-(N-1)*G)/N;
 const pool=document.getElementById('pool'), hdr=pool.querySelector('header'), end=pool.querySelector('.end');
 const span=e=>e.classList.contains('w5')?5:e.classList.contains('w3')?3:e.classList.contains('w2')?2:1;
 const wOf=s=>s*CW+(s-1)*G;
 const items=[...pool.querySelectorAll('.e')].map(e=>{const s=span(e);e.style.width=wOf(s)+'px';return {el:e,s,w:wOf(s),h:e.getBoundingClientRect().height}});
 hdr.style.width=W+'px'; const hh=hdr.getBoundingClientRect().height+6*MM;
 const badge=hdr.querySelector('.day'); const bR=badge?badge.getBoundingClientRect():null;
 const FR=Array(N).fill(bR?bR.height+2*MM+G:0);   // fresh page: the day badge has its own line across the top
 const fresh=()=>FR.slice();
 const endH={}; for(let s=2;s<=N;s++){end.style.width=wOf(s)+'px';endH[s]=end.getBoundingClientRect().height}
 // pure simulation: returns {pages, pl:[[el,page,x,y,w]]}
 function pack(list, endAt, breakAt){
   let pages=1, cols=Array(N).fill(hh), pl=[['hdr',0,0,0,W]];
   const fit=(s,h)=>{let b=null;for(let c=0;c+s<=N;c++){const y=Math.max(...cols.slice(c,c+s));if(y+h<=H&&(!b||y<b[1]))b=[c,y]}return b};
   const place=(el,s,h,f)=>{pl.push([el,pages-1,f[0]*(CW+G),f[1],wOf(s)]);for(let c=f[0];c<f[0]+s;c++)cols[c]=f[1]+h+G};
   const q=list.slice();
   if(breakAt!=null) q.splice(breakAt,0,{brk:true});
   if(endAt!=null) q.splice(endAt,0,{el:'end',s:2,h:endH[2],end:true});
   let endDone=false;
   while(q.length){
     let ok=false;
     if(q[0].brk){q.shift();pages++;cols=fresh();continue}
     for(let k=0;k<Math.min(q.length,5);k++){const it=q[k];if(it.brk)break;
       let f=null,s=it.s,h=it.h;
       if(it.end){for(let ss=3;ss>=2&&!f;ss--){f=fit(ss,endH[ss]);if(f){s=ss;h=endH[ss]}}}
       else f=fit(s,h);
       if(f){place(it.el,s,h,f);if(it.end)endDone=true;q.splice(k,1);ok=true;break}}
     if(!ok){ if(cols.every((v,i)=>v===FR[i])){const it=q.shift();place(it.el,it.s,it.h,[0,Math.max(...FR)]);cols=Array(N).fill(H)} else {pages++;cols=fresh()} }
   }
   if(!endDone){let f=null,s;for(s=N;s>=2&&!f;s--)f=fit(s,endH[s]);
     if(f){s++;place('end',s,endH[s],f)} else {pages++;cols=fresh();place('end',N,endH[N],[0,Math.max(...FR)])}}
   return {pages,pl};
 }
 let best=pack(items,null);
 const onLast=r=>r.pl.filter(p=>p[1]===r.pages-1&&p[0]!=='end').length;
 for(let k=1;k<=Math.min(25,items.length);k++){const r=pack(items,items.length-k);if(r.pages<best.pages){best=r;break}}
 // never leave the closing alone on the last page: pull a few cards over with it
 if(onLast(best)===0&&best.pages>1){for(let k=Math.min(12,items.length-1);k>=3;k--){const r=pack(items,null,items.length-k);if(r.pages===best.pages){best=r;break}}}
 const pages=[];for(let i=0;i<best.pages;i++){const p=document.createElement('div');p.className='page';document.body.appendChild(p);pages.push(p)}
 for(const [el,pg,x,y,w] of best.pl){const e=el==='hdr'?hdr:el==='end'?end:el;e.classList.add('placed');e.style.left=x+'px';e.style.top=y+'px';e.style.width=w+'px';pages[pg].appendChild(e)}
 if(badge){for(let i=1;i<pages.length;i++){const c=badge.cloneNode(true);c.classList.add('placed');c.style.right='0';c.style.left='auto';c.style.top='0';pages[i].appendChild(c)}}
 pool.remove(); return best.pages;
};
'''

doc = f'''<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<div id="pool"><header>{DAYLINE}<div class="t">སྐྱབས་ཞུ།</div><h1>Prayer Requests</h1><div class="zht">迴 向 祈 願 名 單</div>
<div class="subbo">ཟབ་ཏིག་སྒྲོལ་ཆོག་ཐད་གཏོང་སྟེང་འབྱོར་བའི་སྐྱབས་ཞུ།</div>
<div class="sub">Prayer requests received through the live broadcast of the Zabtik Drolchok (Profound Essence Tara Puja)</div>
<div class="subzh">於甚深心要度母法會（Zabtik Drolchok）直播中所收到的迴向祈願名單</div>
<div class="meta">{html.escape(DATE)} &nbsp;·&nbsp; {len(items)} requests &nbsp;·&nbsp; <span class="zhm">{ZHDATE} &nbsp;{len(items)} 則祈願</span></div></header>
{entries}
{CLOSING}</div>
<script>{JS}</script></body></html>'''

work = tempfile.mkdtemp()
for f in ['GARA.TTF', 'GARABD.TTF', 'GARAIT.TTF', 'Monlam Uni OuChan2.ttf']:
    shutil.copy(os.path.join(A.fonts, f), work)
page_html = os.path.join(work, 'prayers.html')
open(page_html, 'w', encoding='utf-8').write(doc)

# footer on every page: WeBuddhist logo + page number
FOOT_LOGO = f'<img src="data:{mt};base64,{b64}" style="height:24px;vertical-align:middle">' if BRAND else '<span style="font-weight:700;color:#2b1d14">WeBuddhist</span>'
FOOTER = ('<div style="width:100%;margin:0 15mm;display:flex;justify-content:space-between;align-items:center;'
          'font-size:9pt;color:#b8872b;font-family:serif;-webkit-print-color-adjust:exact">'
          f'<span>{FOOT_LOGO}</span>'
          f'<span>{html.escape(DATE)} &nbsp;·&nbsp; <span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')

from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page()
    p.goto('file://' + page_html)
    p.evaluate('document.fonts.ready')
    p.wait_for_timeout(300)
    npages = p.evaluate('window.layout()')
    p.pdf(path=A.out, format='A3', prefer_css_page_size=True, print_background=True,
          display_header_footer=True, header_template='<div></div>',
          footer_template=FOOTER)
    b.close()
emails = {(r.get('email') or '').lower() for r in rows if r.get('email')}
missing = sorted(e for e in emails if e not in AV)
print('dropped:', DROPPED)
if missing: print(f'AVATARS: {len(missing)} of {len(emails)} people are not in avatars.json yet -> run fetch_avatars.py on this day file first')
print(f'{len(items)} prayers, {PHOTOS} photo avatars, {npages} pages, date {DATE} -> {A.out}')
