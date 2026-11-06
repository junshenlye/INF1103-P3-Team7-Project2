"""Generate an offline evidence inspector from a proposed-pipeline run."""

import argparse
import json
from pathlib import Path


def render(directory):
    directory = Path(directory)
    result = json.loads((directory / "result.json").read_text())
    sources = {}
    for folder in sorted(directory.glob("source-*")):
        doc = json.loads((folder / "document.json").read_text())
        originals = list(folder.glob("original.*"))
        if originals:
            sources[doc["document_sha256"]] = {
                "original": str(originals[0].relative_to(directory)),
                "pages": {
                    number: str((folder / name).relative_to(directory))
                    for number, name in doc.get("page_images", {}).items()
                },
            }
    data = json.dumps(
        {"review": result["evidence_review"], "sources": sources}, ensure_ascii=False
    ).replace("<", "\\u003c")
    page = r"""<!doctype html><meta charset="utf-8"><title>StackPlan evidence review</title>
<style>body{margin:0;font:16px system-ui;color:#18332d;background:#f2f5f1}header{padding:18px 24px;background:#fff;border-bottom:1px solid #ccc}main{display:grid;grid-template-columns:350px 1fr;height:calc(100vh - 95px)}aside{overflow:auto;padding:16px}button{display:block;width:100%;text-align:left;margin:0 0 8px;padding:12px;border:1px solid #bdc9bf;background:white;border-radius:6px;cursor:pointer}button:focus,button.selected{outline:2px solid #28785d}article{overflow:auto;padding:20px}.page{position:relative;display:inline-block;max-width:100%}.page img{display:block;max-width:100%}.box{position:absolute;border:2px solid #d94d00;background:#ffba0033;box-sizing:border-box;pointer-events:none}#text{white-space:pre-wrap;background:white;padding:16px}small{color:#53635b}@media(max-width:700px){main{grid-template-columns:1fr;height:auto}aside{max-height:35vh}article{padding:10px}}</style>
<header><b>Document evidence review</b><br><small>Select a field to inspect its cited region. Reference integrity passed; semantic support still needs review.</small></header>
<main><aside id="facts"></aside><article><div id="pages"></div><div id="text">Select an extracted field.</div></article></main>
<script type="application/json" id="data">DATA</script><script>
const data=JSON.parse(document.getElementById('data').textContent);
const facts=document.getElementById('facts'),pages=document.getElementById('pages'),text=document.getElementById('text');
for(const fact of data.review){const b=document.createElement('button');b.textContent=`Assessment ${fact.assessment+1} · ${fact.field}: ${JSON.stringify(fact.value)}`;facts.append(b);b.onclick=()=>{for(const x of facts.children)x.classList.remove('selected');b.classList.add('selected');pages.replaceChildren();const groups=new Map();for(const ev of fact.evidence)for(const region of ev.regions){const key=ev.document_sha256+':'+region.page;if(!groups.has(key))groups.set(key,{src:data.sources[ev.document_sha256]?.pages?.[region.page] || data.sources[ev.document_sha256]?.original,page:region.page,regions:[]});groups.get(key).regions.push(region);}for(const group of groups.values()){if(!group.src||group.src.endsWith('.pdf')){const p=document.createElement('p');p.textContent='PDF source: page '+group.page+'; inspect original PDF using the recorded coordinates.';pages.append(p);continue;}const wrap=document.createElement('div');wrap.className='page';const img=document.createElement('img');img.src=group.src;img.alt='Original source';wrap.append(img);for(const r of group.regions){const box=document.createElement('div');box.className='box';const [l,t,right,bottom]=r.bbox;Object.assign(box.style,{left:l*100+'%',top:t*100+'%',width:(right-l)*100+'%',height:(bottom-t)*100+'%'});wrap.append(box);}pages.append(wrap);}text.textContent=fact.evidence.map(e=>e.id+'\n'+e.text).join('\n\n');};}
</script>""".replace("DATA", data)
    (directory / "review.html").write_text(page)
    return directory / "review.html"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    args = parser.parse_args()
    print(render(args.directory))


if __name__ == "__main__":
    main()
