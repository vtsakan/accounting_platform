"""Local PDF/CSV serialization of already-authorised immutable report data."""
import csv
import io
from pathlib import Path
import threading
import unicodedata
from xml.sax.saxutils import escape
from core.locale import ATHENS,format_euro,greek_date
from .export_schema import ExportError

MAX_OUTPUT_BYTES=16*1024*1024
PDF_LOCK=threading.Lock()
FONT_ROOT=Path(__file__).resolve().parent/'static/accounting/reports'


def csv_text(value,*,identifier=False):
    text=str(value)
    if not text:return ''
    # NFKC also identifies full-width formula prefixes; preserve original text.
    significant=unicodedata.normalize('NFKC',text).lstrip()
    while significant and unicodedata.category(significant[0]).startswith('C'):significant=significant[1:].lstrip()
    dangerous=significant.startswith(('=','+','-','@')) or (text and unicodedata.category(text[0]).startswith('C'))
    # The tab remains literal CSV data; the apostrophe also makes identifiers
    # explicit text (notably leading-zero AFMs). No formula is emitted.
    return "\t'"+text if dangerous else "'"+text if identifier else text


def display(column,value,*,csv_mode=False):
    if value is None:return 'Άγνωστο'
    if column.kind=='money':return format_euro(value,symbol=not csv_mode)
    if column.kind=='date':return greek_date(value)
    if column.kind=='month':return value.strftime('%m/%Y')
    return csv_text(value,identifier=column.kind=='identifier') if csv_mode else str(value)


def provenance_rows(document):
    p=document.provenance
    rows=[('Βάση στοιχείων',p.label),('Ημερομηνίες πηγών',', '.join(greek_date(d) for d in p.source_dates)),
        ('Παραγωγή',document.generated_at.astimezone(ATHENS).strftime('%d/%m/%Y %H:%M')+' · ώρα Αθήνας')]
    if p.kind=='estimate':rows.append(('Έκδοση κανόνων εκτίμησης',p.rule_version))
    return rows


def bounded(data):
    if len(data)>MAX_OUTPUT_BYTES:raise ExportError('Το αρχείο υπερβαίνει το όριο μεγέθους εξαγωγής. Περιορίστε τα φίλτρα.',status=422)
    return data


def render_csv(document):
    # One rectangular CSV: section identifies each table, with the union of
    # explicitly typed columns. Empty cells belong to a different section.
    columns={}
    for part in document.sections:
        for col in part.columns:
            if col.key in columns and columns[col.key]!=col:raise ValueError('Conflicting CSV column')
            columns[col.key]=col
    output=io.StringIO(newline='');writer=csv.writer(output,delimiter=';',quoting=csv.QUOTE_ALL,lineterminator='\r\n')
    writer.writerow(['Ενότητα','Γραμμή',*(c.label for c in columns.values())])
    for part in document.sections:
        for index,row in enumerate(part.rows,1):
            values={col.key:display(col,value,csv_mode=True) for col,value in zip(part.columns,row)}
            writer.writerow([csv_text(part.title),index,*(values.get(key,'') for key in columns)])
    # Metadata uses the same ordinary columns and never a formula cell.
    for index,(label,value) in enumerate(provenance_rows(document),1):
        writer.writerow(['Προέλευση',index,*(csv_text(label) if key=='label' else csv_text(value) if key=='value' else '' for key in columns)])
    return bounded(output.getvalue().encode('utf-8-sig'))


def render_pdf(document):
    # ReportLab/font subsetting is serialised per process. No HTML layout,
    # macros, URLs, remote fonts, images or caller-selected filesystem paths.
    if not PDF_LOCK.acquire(timeout=5):raise ExportError('Η εξαγωγή PDF είναι απασχολημένη. Δοκιμάστε ξανά σε λίγο.',status=503)
    try:
        from reportlab import rl_config
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4,landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,LongTable,TableStyle
        from reportlab.platypus.doctemplate import LayoutError
        rl_config.trustedHosts=[];rl_config.trustedSchemes=[]
        for name,filename in [('AccountingGreek','DejaVuSans.ttf'),('AccountingGreek-Bold','DejaVuSans-Bold.ttf')]:
            if name not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont(name,str(FONT_ROOT/filename)))
        body=ParagraphStyle('ExportBody',fontName='AccountingGreek',fontSize=7.5,leading=10,alignment=TA_LEFT,splitLongWords=True)
        heading=ParagraphStyle('ExportHeading',parent=body,fontName='AccountingGreek-Bold',fontSize=11,leading=15,spaceAfter=7,keepWithNext=True)
        header=ParagraphStyle('ExportCellHeading',parent=body,fontName='AccountingGreek-Bold')
        def para(text,style=body):
            # Only escaped plain text enters Paragraph's markup parser.
            clean=''.join(c if c in '\n\t' or not unicodedata.category(c).startswith('C') else ' ' for c in str(text))
            return Paragraph(escape(clean).replace('\n','<br/>'),style)
        output=io.BytesIO();width,height=landscape(A4)
        pdf=SimpleDocTemplate(output,pagesize=(width,height),leftMargin=28,rightMargin=28,topMargin=32,bottomMargin=32,
            title=document.title,author=document.office_name,subject=document.provenance.label,pageCompression=1)
        story=[para(document.title,heading),para(document.office_name+' · Υπόλοιπα έως '+greek_date(document.as_of)),Spacer(1,8)]
        for label,value in provenance_rows(document):story.append(para(label+': '+value))
        story.append(Spacer(1,10))
        for part in document.sections:
            story.append(para(part.title,heading))
            if not part.rows:
                story.extend([para('Δεν υπάρχουν εγγραφές στο επιλεγμένο εύρος.'),Spacer(1,10)]);continue
            rows=[[para(col.label,header) for col in part.columns]]
            rows.extend([para(display(col,value)) for col,value in zip(part.columns,row)] for row in part.rows)
            weights=sum(c.weight for c in part.columns)
            table=LongTable(rows,colWidths=[(width-56)*c.weight/weights for c in part.columns],repeatRows=1,splitByRow=1,splitInRow=1)
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e9edf3')),('VALIGN',(0,0),(-1,-1),'TOP'),
                ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#c5cbd3')),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
                ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
            story.extend([table,Spacer(1,12)])
        def footer(canvas,doc):
            canvas.saveState();canvas.setFont('AccountingGreek',7)
            canvas.drawString(28,17,'Ιδιωτική οικονομική αναφορά · '+document.provenance.label)
            canvas.drawRightString(width-28,17,'Σελίδα '+str(doc.page));canvas.restoreState()
        try:pdf.build(story,onFirstPage=footer,onLaterPages=footer)
        except LayoutError as error:
            raise ExportError('Το περιεχόμενο δεν χωρά σε PDF. Περιορίστε το εύρος ή επιλέξτε CSV.',status=422) from error
        return bounded(output.getvalue())
    finally:PDF_LOCK.release()
