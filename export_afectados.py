#!/usr/bin/env python3
# Pucará — Sistema de gestión para ISP
# Copyright (C) 2026 Esteban Aguiar
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""
export_afectados.py — Genera el PDF de clientes afectados por una incidencia.
Se llama desde app.py. Enfocado en datos operativos para cuadrilla:
ubicación, teléfonos, coordenadas.
"""
from datetime import datetime
from io import BytesIO

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)

EMPRESA = "ERLAN Telecomunicaciones"


def _fmt_fecha(f):
    if not f:
        return '—'
    try:
        return datetime.strptime(str(f)[:19], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M')
    except (ValueError, TypeError):
        try:
            return datetime.strptime(str(f)[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
        except (ValueError, TypeError):
            return str(f)


def generar_pdf_afectados(incidencia, clientes):
    """Genera el PDF. incidencia: dict con datos de la incidencia.
    clientes: lista de dicts con nombre, nro_cliente, telefono, direccion,
              localidad, lat, lng."""
    buf = BytesIO()
    # Horizontal (landscape) para que entren bien las columnas de datos
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            topMargin=1.5*cm, bottomMargin=1.5*cm,
                            leftMargin=1.5*cm, rightMargin=1.5*cm)
    styles = getSampleStyleSheet()
    st_titulo = ParagraphStyle('t', parent=styles['Normal'], fontSize=15,
                               fontName='Helvetica-Bold', textColor=colors.HexColor('#1a3d6b'),
                               alignment=TA_CENTER, spaceAfter=2)
    st_sub = ParagraphStyle('s', parent=styles['Normal'], fontSize=10,
                            alignment=TA_CENTER, textColor=colors.grey, spaceAfter=8)
    st_cell = ParagraphStyle('c', parent=styles['Normal'], fontSize=8, leading=10)
    st_cell_b = ParagraphStyle('cb', parent=st_cell, fontName='Helvetica-Bold')

    story = []
    story.append(Paragraph(f"{EMPRESA} — Clientes afectados", st_titulo))
    inc_titulo = incidencia.get('titulo', 'Incidencia')
    inc_estado = incidencia.get('estado', '')
    story.append(Paragraph(
        f"Incidencia: <b>{inc_titulo}</b> · Estado: {inc_estado} · "
        f"Inicio: {_fmt_fecha(incidencia.get('fecha_inicio'))}", st_sub))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#1a3d6b'), spaceAfter=8))
    story.append(Paragraph(f"<b>{len(clientes)} cliente(s) afectado(s)</b>", st_cell_b))
    story.append(Spacer(1, 6))

    # Cabecera de la tabla
    encabezado = ['#', 'Cliente', 'N° Cli.', 'Teléfono', 'Dirección', 'Localidad', 'Coordenadas']
    filas = [[Paragraph(f"<b>{h}</b>", st_cell) for h in encabezado]]

    for i, c in enumerate(clientes, 1):
        coords = ''
        if c.get('lat') and c.get('lng'):
            coords = f"{c['lat']}, {c['lng']}"
        filas.append([
            Paragraph(str(i), st_cell),
            Paragraph(c.get('nombre', '') or '—', st_cell_b),
            Paragraph(str(c.get('nro_cliente', '') or '—'), st_cell),
            Paragraph(c.get('telefono', '') or '—', st_cell),
            Paragraph(c.get('direccion', '') or '—', st_cell),
            Paragraph(c.get('localidad', '') or '—', st_cell),
            Paragraph(coords or '—', st_cell),
        ])

    # Anchos de columna (suman ~26cm, el ancho útil de A4 landscape)
    tabla = Table(filas, colWidths=[0.8*cm, 5.5*cm, 2*cm, 3*cm, 6.5*cm, 3.5*cm, 4.5*cm],
                  repeatRows=1)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3d6b')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f7fa')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
    ]))
    # Cabecera en blanco
    for j in range(len(encabezado)):
        filas[0][j] = Paragraph(f"<b><font color='white'>{encabezado[j]}</font></b>", st_cell)
    story.append(tabla)

    story.append(Spacer(1, 12))
    pie = ParagraphStyle('p', parent=styles['Normal'], fontSize=7,
                         textColor=colors.grey, alignment=TA_CENTER)
    story.append(Paragraph(
        f"Generado por Pucara el {datetime.now().strftime('%d/%m/%Y %H:%M')} hs — {EMPRESA}", pie))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


if __name__ == '__main__':
    inc = {'titulo': 'Corte fibra troncal Oro Verde', 'estado': 'abierta',
           'fecha_inicio': '2026-07-03 08:30:00'}
    clientes = [
        {'nombre': 'PÉREZ JUAN', 'nro_cliente': '038', 'telefono': '343-1234567',
         'direccion': 'San Martín 450', 'localidad': 'ORO VERDE', 'lat': -31.8425, 'lng': -60.5312},
        {'nombre': 'GÓMEZ ANA', 'nro_cliente': '039', 'telefono': '343-7654321',
         'direccion': 'Belgrano 1200', 'localidad': 'ORO VERDE', 'lat': -31.8440, 'lng': -60.5300},
    ]
    pdf = generar_pdf_afectados(inc, clientes)
    with open('/tmp/afectados_test.pdf', 'wb') as f:
        f.write(pdf)
    print(f"✓ PDF generado: {len(pdf)} bytes")
