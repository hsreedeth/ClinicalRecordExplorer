"""Regenerate an offline snapshot using exactly the live report-building contract."""
import json
import base64
from pathlib import Path
from pipeline import build_database,build_report
ROOT=Path(__file__).parent

def generate():
    db,run=build_database()
    try: report=build_report(db,run)
    finally: db.close()
    html=(ROOT/'web/index.html').read_text()
    css=(ROOT/'web/style.css').read_text()
    js=(ROOT/'web/ui.js').read_text()
    for font in ('InterVariable.woff2','InterVariable-Italic.woff2'):
        data=base64.b64encode((ROOT/'web/fonts'/font).read_bytes()).decode()
        css=css.replace('/fonts/'+font,'data:font/woff2;base64,'+data)
    html=html.replace('<link rel="preload" href="/fonts/InterVariable.woff2" as="font" type="font/woff2" crossorigin>','')
    payload=json.dumps(report,allow_nan=False).replace('<','\\u003c')
    html=html.replace('<link rel="stylesheet" href="/style.css">','<style>'+css+'</style>')
    html=html.replace('<script src="/ui.js"></script>', '<script id="snapshot-report" type="application/json">'+payload+'</script><script>'+js+'</script>')
    html=html.replace('<section class="intro" id="intro">','<p class="snapshot-note">Offline snapshot · default parameters · run app.py to recalculate</p><section class="intro" id="intro">')
    (ROOT/'Preview.html').write_text(html)
    return report

if __name__=='__main__': generate()
