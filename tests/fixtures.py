"""Small disposable OOXML fixtures. Never touches real inventory or BOM workbooks."""
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED
from xml.sax.saxutils import escape, quoteattr


def workbook(path, sheets, media=None):
    # sheets: [(original name, {row_number: {column: value}})]
    path = Path(path)
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relations = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with ZipFile(path, "w", ZIP_STORED) as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>')
        z.writestr("_rels/.rels", f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{relations}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="{relations}"><sheets>'+''.join(f'<sheet name={quoteattr(name)} sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(sheets,1))+'</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="{relations}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))+'</Relationships>')
        for i,(_,rows) in enumerate(sheets,1):
            data=[]
            for row_no,cols in sorted(rows.items()):
                cells=[]
                for column,value in cols.items():
                    address=f"{column}{row_no}"
                    if value is None:continue
                    if isinstance(value,tuple):  # formula/error/boolean with cached/raw value
                        typ, value = value
                        if typ=='f':cells.append(f'<c r="{address}"><f>{escape(value)}</f><v>9</v></c>')
                        else:cells.append(f'<c r="{address}" t="{typ}"><v>{escape(str(value))}</v></c>')
                    elif isinstance(value,(int,float)) and not isinstance(value,bool):
                        cells.append(f'<c r="{address}"><v>{value}</v></c>')
                    else:cells.append(f'<c r="{address}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>')
                data.append(f'<row r="{row_no}">'+''.join(cells)+'</row>')
            z.writestr(f"xl/worksheets/sheet{i}.xml", f'<worksheet xmlns="{ns}"><sheetData>'+''.join(data)+'</sheetData></worksheet>')
        if media is not None:z.writestr('xl/media/image1.bin',media)
    return path


def stock_rows(entries, header=13):
    rows={header:{'E':'PART NO','F':'DESCRIPTION','K':'RACKING','L':'LEVEL','O':'LIVE STOCK'}}
    for n,(code,qty) in enumerate(entries,header+2):rows[n]={'E':code,'F':'Fixture material','K':1,'L':2,'O':qty}
    return rows


def bom_rows(entries, header=21):
    rows={header-2:{'B':'Assy Name:','E':'Assy-V1 / MIR (unconfirmed)'},header:{'D':'PART NO','E':'DESCRIPTION','L':'QTY'}}
    for n,(code,qty) in enumerate(entries,header+1):rows[n]={'B':n-header,'D':code,'E':'Fixture material','L':qty}
    return rows
