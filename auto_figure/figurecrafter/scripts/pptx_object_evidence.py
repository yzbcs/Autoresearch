"""Read geometry, z-order, math/media/line storage and overlap evidence.

Does not infer scientific roles, choose layouts, or score figures.
"""
import argparse,json
from pathlib import Path
from collections import Counter
from pptx import Presentation

def extract(path):
    prs=Presentation(path); slides=[]
    for si,slide in enumerate(prs.slides):
        objects=[]
        def walk(shapes,affine=(1,1,0,0),parent=None,zprefix=()):
            sx,sy,tx,ty=affine
            for zi,sh in enumerate(shapes):
                box=[tx+sx*sh.left,ty+sy*sh.top,sx*sh.width,sy*sh.height]
                rect=[round(box[0]/prs.slide_width,5),round(box[1]/prs.slide_height,5),round(box[2]/prs.slide_width,5),round(box[3]/prs.slide_height,5)]
                ident='s'+str(si+1)+':'+'.'.join(map(str,zprefix+(zi,)))
                xml=sh._element;kind=xml.tag.rsplit('}',1)[-1]
                text=sh.text if sh.has_text_frame else ''
                obj={'id':ident,'name':sh.name,'z':list(zprefix+(zi,)),'parent':parent,'storage_tag':kind,'shape_type':str(sh.shape_type),'bounds_fraction':rect,'text':text,'has_text':sh.has_text_frame,'office_math_count':len(xml.xpath('.//m:oMath')),'native_chart':bool(getattr(sh,'has_chart',False)),'native_table':bool(getattr(sh,'has_table',False)),'preset_geometry':[v.get('prst') for v in xml.xpath('.//a:prstGeom')],'custom_path_count':len(xml.xpath('.//a:path')),'arrow_ends':[dict(v.attrib) for v in xml.xpath('.//a:headEnd | .//a:tailEnd')],'colors':[v.get('val') for v in xml.xpath('.//a:srgbClr')]}
                if hasattr(sh,'image'):
                    obj['image']={'pixel_size':list(sh.image.size),'content_type':sh.image.content_type,'sha1':sh.image.sha1,'crop':[sh.crop_left,sh.crop_top,sh.crop_right,sh.crop_bottom]}
                objects.append(obj)
                if hasattr(sh,'shapes'):
                    t=sh._element.grpSpPr.xfrm
                    ax=t.ext.cx/t.chExt.cx if t.chExt.cx else 1;ay=t.ext.cy/t.chExt.cy if t.chExt.cy else 1
                    walk(sh.shapes,(sx*ax,sy*ay,tx+sx*(t.off.x-t.chOff.x*ax),ty+sy*(t.off.y-t.chOff.y*ay)),ident,zprefix+(zi,))
        walk(slide.shapes)
        pairs=[]
        for i,a in enumerate(objects):
            ax,ay,aw,ah=a['bounds_fraction'];aa=aw*ah
            if aa<=0:continue
            for b in objects[i+1:]:
                bx,by,bw,bh=b['bounds_fraction'];ba=bw*bh
                if ba<=0:continue
                inter=max(0,min(ax+aw,bx+bw)-max(ax,bx))*max(0,min(ay+ah,by+bh)-max(ay,by))
                fraction=inter/min(aa,ba)
                if fraction>=.6:pairs.append({'back':a['id'],'front':b['id'],'overlap_of_smaller_bbox':round(fraction,4)})
        slides.append({'slide':si+1,'objects':objects,'bbox_overlap_pairs':pairs,'storage_summary':dict(Counter(o['storage_tag'] for o in objects))})
    return {'source':str(Path(path).resolve()),'canvas_mm':[prs.slide_width/360000,prs.slide_height/360000],'slides':slides,'interpretation':'Geometry/storage evidence only. Bbox overlap is not scientific containment or occlusion. Model must inspect rendered pixels and assign semantic roles/compositions.'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('output');a=p.parse_args();Path(a.output).write_text(json.dumps(extract(a.input),ensure_ascii=False,indent=2))
