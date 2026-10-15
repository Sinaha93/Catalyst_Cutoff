"""Local OCR of UCK month-end stock; closing stock is not the supply column."""
import asyncio
import re
import tempfile
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageFont
from backend.adapters.carryover_pdf import render_page, recognize, parse_quantity, group_centres

PARSER_VERSION = 'umicore-carryover-ocr-1'


def read_umicore_carryover(content, period):
    image = render_page(content)
    try:
        with tempfile.TemporaryDirectory(prefix='uck-stock-') as tmp:
            path = Path(tmp)/'page.png'; image.save(path)
            lines = asyncio.run(recognize(path))
        words = [w for line in lines for w in line['words']]
        def candidate(text):
            text = re.sub(r'\s','',text).upper().replace('•','-')
            if re.fullmatch(r'[A-Z0-9]{10}',text): text=text[:5]+'-'+text[5:]
            return text
        parts = [(candidate(w['text']),w) for w in words
                 if re.fullmatch(r'[A-Z0-9]{5}-[A-Z0-9]{5}',candidate(w['text']))]
        if not parts: raise ValueError('part rows')
        top = int(min(w['y'] for p,w in parts)); bottom = int(max(w['y']+w['height'] for p,w in parts))
        pixels = image.convert('L'); pix = pixels.load()
        xs = group_centres([x for x in range(image.width) if sum(pix[x,y]<190 for y in range(top,bottom)) > (bottom-top)*.82])
        if len(xs) != 7: raise ValueError('six column table')
        parts.sort(key=lambda v:v[1]['y'])
        columns = []
        with tempfile.TemporaryDirectory(prefix='uck-columns-') as tmp:
            for c in range(1,5):
                strip=Image.new('RGB',(650,len(parts)*70),'white')
                for i,(part,w) in enumerate(parts):
                    cy=w['y']+w['height']/2
                    cell=image.crop((xs[c]+4,int(cy-17),xs[c+1]-4,int(cy+17)))
                    box=ImageChops.invert(cell.convert('L')).point(lambda x:255 if x>100 else 0).getbbox()
                    if box:cell=cell.crop(box)
                    factor=min(450/cell.width,45/cell.height)
                    cell=cell.resize((max(1,round(cell.width*factor)),max(1,round(cell.height*factor))))
                    ImageDraw.Draw(strip).text((10,i*70+12),'QTY',font=ImageFont.truetype('arial.ttf',32),fill='black')
                    strip.paste(cell,(150,i*70+10))
                path=Path(tmp)/f'{c}.png';strip.save(path)
                texts=['']*len(parts)
                for line in asyncio.run(recognize(path)):
                    for word in line['words']:
                        index=int((word['y']+word['height']/2)//70)
                        if 0<=index<len(parts) and word['x']>120:texts[index]+=' '+word['text']
                columns.append(texts)
        records = []; sums = [0,0,0,0]
        for i,(part,w) in enumerate(sorted(parts,key=lambda v:v[1]['y'])):
            cy = w['y']+w['height']/2
            cells = [' '.join(t['text'] for t in sorted(words,key=lambda t:t['x']) if abs(t['y']+t['height']/2-cy)<w['height']*.65 and xs[c]<t['x']+t['width']/2<xs[c+1]) for c in range(1,5)]
            cells=[column[i] if parse_quantity(column[i]) is not None else cells[c] for c,column in enumerate(columns)]
            values = [parse_quantity(t) for t in cells]
            peer = str(int(values[0])+int(values[1])-int(values[2])) if all(v is not None for v in values[:3]) else None
            for c,v in enumerate(values):
                if v is not None: sums[c] += int(v)
            records.append({'part':part,'quantity':values[3],'sheet':'PDF 1페이지','row_number':i+1,
                'evidence':{'pdf':{'page':1,'box':[xs[0]/image.width,max(0,w['y']-5)/image.height,xs[-1]/image.width,min(image.height,w['y']+w['height']+5)/image.height],
                    'peer_quantity':peer,'reviewed':False,'ocr_columns':cells,'prior':values[0],'supply':values[1],'closing':values[2],'ending':values[3]}}})
        sumword = next((w for w in words if w['text'].upper() in ('SUM','SIJM') and w['y']>bottom), None)
        totals = []
        if sumword:
            cy = sumword['y']+sumword['height']/2
            totals = [parse_quantity(' '.join(t['text'] for t in words if abs(t['y']+t['height']/2-cy)<sumword['height'] and xs[c]<t['x']+t['width']/2<xs[c+1])) for c in range(1,5)]
        return {'status':'needs_review','records':records,'issues':[{'code':'PDF_REVIEW_REQUIRED','location':'PDF 전체','message':'전월 말 적송 열과 전월 적송 + 공급 − 사급 마감 검산을 확인해 주세요.'}],
                'summary':{'row_count':len(records),'part_count':len({r['part'] for r in records}),'registered_period':period,'period_confirmed':False,'printed_total':totals[3] if len(totals)==4 else None,
                           'column_totals':totals,'calculated_totals':[str(v) for v in sums], 'quantity_total':str(sums[3]),
                           'quantity_label':'PDF 전월 말 적송재고 OCR 후보','title_ocr':' '.join(l['text'] for l in lines if any(w['y']<top for w in l['words']))}}
    except Exception as exc:
        return {'status':'needs_review','records':[],'summary':{},'issues':[{'code':'PDF_FORMAT_REVIEW','location':'PDF 전체','message':'유미코아 적송 표의 품번·4개 수량 열을 읽지 못했습니다. '+type(exc).__name__}]}
    finally: image.close()
