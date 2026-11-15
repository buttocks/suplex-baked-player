import re, urllib.request, json, pathlib, urllib.parse
base='https://ring-channel-tv.emergent.host/'
out=pathlib.Path('slamvision-inspect.json')
def get(u):
 req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
 with urllib.request.urlopen(req,timeout=25) as r:return r.read().decode('utf-8','replace')
html=get(base)
scripts=[urllib.parse.urljoin(base,x) for x in re.findall(r'<script[^>]+src=["\\\']([^"\\\']+)',html)]
data={'html_start':html[:9000], 'scripts':scripts,'interesting':[]}
for u in scripts[:8]:
 try:
  js=get(u)
  for term in ['njpw','hideLogo','hide-logo','logoVisible','archive.org','/api/','channels','localStorage','schedule']:
   pos=js.lower().find(term.lower())
   if pos>=0:data['interesting'].append({'script':u,'term':term,'snippet':js[max(0,pos-450):pos+1000]})
  data['interesting'].append({'script':u,'length':len(js),'prefix':js[:600]})
 except Exception as e:data['interesting'].append({'script':u,'error':str(e)})
out.write_text(json.dumps(data,indent=2))
