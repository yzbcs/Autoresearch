"""Read the exact delivered PPTX, independently of the generation inventory."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'figurecrafter'))
from harness.model_led_drawing import inventory, figure_contract
import pymupdf

if __name__=='__main__':
    pptx,pdf,output=map(Path,sys.argv[1:])
    report={'artifact':str(pptx),'pptx_sha256':hashlib.sha256(pptx.read_bytes()).hexdigest(),
            'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
            'geometry':figure_contract(pptx,{'aspect_ratio':[16,9],'slide_count':1}),
            'inspection_method':'Direct python-pptx parsing of the delivered method-overview.pptx, after copying from the frozen delivery.',
            'inventory':inventory(pptx)}
    with pymupdf.open(pdf) as doc:
        report['pdf_pages']=len(doc)
        report['pdf_text']=[p.get_text() for p in doc]
    if report['pdf_pages']!=1:
        raise ValueError('Main figure PDF must contain exactly one page')
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
