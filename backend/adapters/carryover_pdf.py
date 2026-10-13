"""Local Windows OCR for the bordered Heesung carryover form.

OCR is a proposal. Every row must be visually confirmed before adoption.
No document is sent to a remote model.
"""
import asyncio
import re
import tempfile
import threading
from contextlib import closing
from pathlib import Path

from PIL import Image, ImageChops
import pypdfium2 as pdfium

from backend.domain.errors import WorkflowError

PARSER_VERSION = 'heesung-carryover-ocr-1'
_PDF_LOCK = threading.Lock()


async def recognize(path):
    from winrt.windows.storage import StorageFile, FileAccessMode
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    source = await StorageFile.get_file_from_path_async(str(path.resolve()))
    stream = await source.open_async(FileAccessMode.READ)
    bitmap = None
    try:
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None: raise RuntimeError('OCR language unavailable')
        result = await engine.recognize_async(bitmap)
        return [{'text':line.text,'words':[{'text':w.text,'x':w.bounding_rect.x,'y':w.bounding_rect.y,'width':w.bounding_rect.width,'height':w.bounding_rect.height} for w in line.words]} for line in result.lines]
    finally:
        if bitmap is not None: bitmap.close()
        stream.close()


def group_centres(points):
    groups=[]
    for p in points:
        if not groups or p>groups[-1][-1]+2: groups.append([p])
        else: groups[-1].append(p)
    return [round(sum(g)/len(g)) for g in groups]


def render_page(content):
    # PDFium is not thread safe; API previews and registration can overlap.
    with _PDF_LOCK:
        return _render_page(content)


def _render_page(content):
    try:
        with closing(pdfium.PdfDocument(content)) as document:
            if len(document)!=1: raise WorkflowError('PDF_PAGE_COUNT','현재 희성 적송재고 양식은 1페이지 자료를 지원합니다. 원본 페이지 구성을 확인해 주세요.')
            page=document[0]
            scale=min(3,2400/max(page.get_size()))
            bitmap=page.render(scale=scale)
            try: return bitmap.to_pil().convert('RGB')
            finally: bitmap.close();page.close()
    except WorkflowError: raise
    except Exception: raise WorkflowError('INVALID_PDF','PDF를 열지 못했습니다. 암호 또는 파일 손상 여부를 확인해 주세요.') from None


def grid(image):
    grey=image.convert('L');w,h=grey.size;pixels=grey.load()
    horizontal=group_centres([y for y in range(h) if sum(pixels[x,y]<190 for x in range(w))>w*.50])
    if len(horizontal)<8: raise ValueError('table grid unavailable')
    top,bottom=horizontal[2],horizontal[-1]
    vertical=group_centres([x for x in range(w) if sum(pixels[x,y]<170 for y in range(top,bottom))>(bottom-top)*.75])
    if len(vertical)!=7: raise ValueError('table columns changed')
    return horizontal,vertical


def parse_quantity(text):
    value=re.sub(r'\s','',text)
    if re.fullmatch(r'-?\d+',value): return str(int(value))
    if re.fullmatch(r'-?\d{1,3}(?:[,\.]\d{3})+',value): return str(int(value.replace(',','').replace('.','')))
    return None


def read_carryover(content, period):
    image=render_page(content)
    fallback={'status':'needs_review','records':[],'summary':{'quantity_label':'전월 말 적송재고 OCR 후보'},'issues':[]}
    try:
        ys,xs=grid(image)
        height=60;count=len(ys)-1
        if count>40: raise ValueError('too many rows for this form')
        with tempfile.TemporaryDirectory(prefix='catalyst-ocr-') as temp:
            folder=Path(temp);columns=[]
            for col in range(6):
                strip=Image.new('RGB',(950,count*height),'white')
                for i in range(count):
                    cell=image.crop((xs[col]+3,ys[i]+3,xs[col+1]-3,ys[i+1]-3))
                    bbox=ImageChops.invert(cell.convert('L')).point(lambda x: 255 if x>100 else 0).getbbox()
                    if bbox: cell=cell.crop(bbox)
                    factor=min(900/cell.width,40/cell.height)
                    cell=cell.resize((max(1,round(cell.width*factor)),max(1,round(cell.height*factor))))
                    strip.paste(cell,(10,i*height+7))
                path=folder/f'column-{col}.png';strip.save(path)
                lines=asyncio.run(recognize(path));texts=['']*count
                for line in lines:
                    for word in line['words']:
                        index=int((word['y']+word['height']/2)//height)
                        if 0<=index<count: texts[index]+=(' ' if texts[index] else '')+word['text']
                columns.append(texts)
            header=image.crop((0,0,image.width,ys[0]));header_path=folder/'header.png';header.save(header_path)
            title=' '.join(line['text'] for line in asyncio.run(recognize(header_path)))
        matches=re.findall(r'(20\d{2})\s*년\s*(\d{1,2})\s*월',title)
        detected=sorted({f'{y}-{int(m):02d}' for y,m in matches})
        records=[];printed_total=None;expected_sequence=1
        for i in range(count):
            index=parse_quantity(columns[0][i])
            if not records and not re.match(r'\s*\d{5}',columns[1][i]):
                if not records:
                    possible=parse_quantity(columns[2][i])
                    if possible is not None: printed_total=possible
                continue
            index=str(expected_sequence)
            expected_sequence+=1
            rawpart=columns[1][i]
            part=re.sub(r'\s','',rawpart).upper().replace('•','-').replace('–','-')
            q=parse_quantity(columns[2][i]);peer=parse_quantity(columns[3][i])
            records.append({'sheet':'PDF 1페이지','row_number':int(index),'part':part,'quantity':q,
                'evidence':{'pdf':{'page':1,'box':[xs[0]/image.width,ys[i]/image.height,xs[-1]/image.width,ys[i+1]/image.height],
                    'raw_part':rawpart,'raw_quantity':columns[2][i],'peer_quantity':peer,'raw_peer_quantity':columns[3][i],
                    'raw_difference':columns[4][i],'reason':columns[5][i],'reviewed':False,
                    'ocr_part':part,'ocr_quantity':q,'engine':'Windows.Media.Ocr'}}})
        if not records: raise ValueError('no item rows')
        total=sum(int(r['quantity']) for r in records if r['quantity'] is not None)
        return {'status':'needs_review','records':records,'issues':[{'code':'OCR_REVIEW_REQUIRED','location':'PDF 1페이지','message':'인식 후보입니다. 원본 이미지와 품번·양쪽 수량을 대조하고 각 행을 확인해 주세요.'}],
            'summary':{'row_count':len(records),'part_count':len({r['part'] for r in records}),'quantity_total':str(total),
                       'printed_total':printed_total,'detected_periods':detected,'registered_period':period,'title_ocr':title,'period_confirmed':False,
                       'quantity_label':'전월 말 적송재고 OCR 후보'}}
    except (ImportError,OSError,RuntimeError,ValueError,AttributeError) as exc:
        fallback['issues']=[{'code':'PDF_OCR_UNAVAILABLE','location':'PDF 원본','message':'현재 PDF의 표를 자동으로 읽지 못했습니다. 원본은 보관합니다. Windows OCR 언어 설치와 표 양식을 확인해 주세요.'}]
        return fallback
    finally: image.close()
