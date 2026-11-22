"""Resource-bounded file structure inspection. Run only as a child process."""
import io
import posixpath
import resource
import struct
import sys
import warnings
import zipfile
from xml.etree import ElementTree


def word_binary(data):
    if len(data)<512 or data[:8]!=b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':raise ValueError()
    order,shift,mini=struct.unpack_from('<HHH',data,28)
    if order!=0xfffe or shift not in (9,12) or mini!=6:raise ValueError()
    sector=1<<shift;count=len(data)//sector-1
    if count<1 or len(data)%sector:raise ValueError()
    def block(index):
        if not 0<=index<count:raise ValueError()
        return data[(index+1)*sector:(index+2)*sector]
    fat_count=struct.unpack_from('<I',data,44)[0]
    refs=list(struct.unpack_from('<109I',data,76));next_difat,difat_count=struct.unpack_from('<II',data,68)
    seen=set()
    for _ in range(difat_count):
        if next_difat in seen:raise ValueError()
        seen.add(next_difat);part=struct.unpack('<'+'I'*(sector//4),block(next_difat))
        refs.extend(part[:-1]);next_difat=part[-1]
    refs=[x for x in refs if x<0xfffffffa]
    if len(refs)!=fat_count or fat_count>count:raise ValueError()
    fat=[]
    for index in refs:fat.extend(struct.unpack('<'+'I'*(sector//4),block(index)))
    def chain(index,table,reader,maximum):
        out=bytearray();seen=set()
        while index!=0xfffffffe:
            if index in seen or index>=len(table):raise ValueError()
            seen.add(index);out.extend(reader(index));index=table[index]
            if len(out)>maximum:raise ValueError()
        return bytes(out)
    directory=chain(struct.unpack_from('<I',data,48)[0],fat,block,2_000_000)
    entries={};root=None
    for offset in range(0,len(directory),128):
        entry=directory[offset:offset+128];kind=entry[66]
        if not kind:continue
        length=struct.unpack_from('<H',entry,64)[0]
        if not 2<=length<=64 or length%2:raise ValueError()
        name=entry[:length-2].decode('utf-16le')
        if any(x in name.casefold() for x in ('vba','macro','objectpool','encrypted','package')):raise ValueError()
        if kind==5:root=entry
        if kind==2:entries[name]=entry
    if root is None or 'WordDocument' not in entries:raise ValueError()
    def location(e):return struct.unpack_from('<I',e,116)[0],struct.unpack_from('<Q',e,120)[0]
    first,size=location(entries['WordDocument'])
    if size<32 or size>len(data):raise ValueError()
    if size>=4096:word=chain(first,fat,block,len(data))[:size]
    else:
        root_first,root_size=location(root)
        pool=chain(root_first,fat,block,len(data))[:root_size]
        mini_first=struct.unpack_from('<I',data,60)[0]
        mini_bytes=chain(mini_first,fat,block,len(data));mini_fat=struct.unpack('<'+'I'*(len(mini_bytes)//4),mini_bytes)
        def small(i):
            part=pool[i*64:(i+1)*64]
            if len(part)!=64:raise ValueError()
            return part
        word=chain(first,mini_fat,small,len(pool))[:size]
    if len(word)!=size or word[:2]!=b'\xec\xa5':raise ValueError()
    if struct.unpack_from('<H',word,10)[0] & 0x8100:raise ValueError()


def inspect(extension,data):
    if extension=='pdf':
        from pypdf import PdfReader
        if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-4096:]:raise ValueError()
        reader=PdfReader(io.BytesIO(data),strict=True)
        if reader.is_encrypted or not 1<=len(reader.pages)<=2000:raise ValueError()
        root=reader.trailer['/Root']
        from pypdf.generic import IndirectObject
        pending=[root];objects=set();references=set();examined=0
        forbidden={'/AA','/JS','/JavaScript','/EmbeddedFiles','/EF','/RichMediaContent','/XFA'}
        actions={'/JavaScript','/Launch','/GoToR','/GoToE','/SubmitForm','/ImportData','/Rendition'}
        while pending:
            node=pending.pop();examined+=1
            if examined>50000:raise ValueError()
            if isinstance(node,IndirectObject):
                identity=(node.idnum,node.generation)
                if identity in references:continue
                references.add(identity);node=node.get_object()
            if isinstance(node,(dict,list)):
                if id(node) in objects:continue
                objects.add(id(node))
                if isinstance(node,dict):
                    if forbidden.intersection(node) or node.get('/S') in actions:raise ValueError()
                    pending.extend(node.values())
                else:pending.extend(node)
    elif extension=='docx':
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            rows=archive.infolist();names=[r.filename for r in rows]
            if len(rows)>2000 or len(set(names))!=len(names) or sum(r.file_size for r in rows)>100_000_000:raise ValueError()
            for row in rows:
                name=row.filename.lower()
                if (row.flag_bits&1 or name.startswith('/') or '..' in name.split('/') or '\\' in name
                    or any(x in name for x in ('vbaproject','/embeddings/','activex','encryption'))
                    or row.file_size>25_000_000 or row.file_size>max(row.compress_size*200,1_000_000)):raise ValueError()
            for name in ('[Content_Types].xml','word/document.xml'):
                if name not in names or archive.getinfo(name).file_size>2_000_000:raise ValueError()
                xml=archive.read(name)
                if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():raise ValueError()
                parsed=ElementTree.fromstring(xml)
                if name=='word/document.xml' and parsed.tag!='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document':raise ValueError()
            for row in rows:
                if row.filename.endswith('.rels'):
                    if row.file_size>2_000_000:raise ValueError()
                    xml=archive.read(row)
                    if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():raise ValueError()
                    for relation in ElementTree.fromstring(xml):
                        if relation.get('TargetMode')=='External' and not (
                            relation.get('Type','').endswith('/hyperlink') and
                            relation.get('Target','').startswith(('http://','https://','mailto:'))):raise ValueError()
    elif extension=='doc':word_binary(data)
    else:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS=25_000_000
        formats={'png':'PNG','jpg':'JPEG','jpeg':'JPEG','gif':'GIF','webp':'WEBP','bmp':'BMP','tif':'TIFF','tiff':'TIFF'}
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            with Image.open(io.BytesIO(data)) as image:
                if image.format!=formats[extension] or image.width*image.height>25_000_000 or getattr(image,'n_frames',1)>100:raise ValueError()
                image.verify()


def main():
    resource.setrlimit(resource.RLIMIT_CPU,(4,4))
    resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE,(0,0))
    data=sys.stdin.buffer.read(25_000_001)
    if not data or len(data)>25_000_000:raise ValueError()
    inspect(sys.argv[1],data)
    sys.stdout.write('VALID')


if __name__=='__main__':
    try:main()
    except Exception:sys.exit(1)
