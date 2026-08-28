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
comprobante_vacaciones.py — Genera el PDF de notificación de autorización de vacaciones.
Se llama desde app.py cuando RRHH autoriza una solicitud de vacaciones.
"""
from datetime import datetime
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)


# Datos de la empresa (ajustables)
EMPRESA_NOMBRE = "ERLAN - Telecomunicaciones S.A"
EMPRESA_DETALLE = "Entre Ríos, Argentina"


def _fmt_fecha(f):
    """Convierte 'YYYY-MM-DD' a 'DD/MM/YYYY'. Devuelve el original si no puede."""
    if not f:
        return '—'
    try:
        return datetime.strptime(str(f)[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        return str(f)


def generar_comprobante_vacaciones(datos):
    """
    Genera el PDF y devuelve los bytes.

    datos esperados (dict):
        empleado_nombre, empleado_dni, empleado_legajo, empleado_puesto, empleado_area
        fecha_desde, fecha_hasta, dias
        autorizada_por, fecha_autorizacion
        motivo (opcional)
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=2*cm, bottomMargin=2*cm,
                            leftMargin=2.2*cm, rightMargin=2.2*cm)
    styles = getSampleStyleSheet()

    # Estilos propios
    st_empresa = ParagraphStyle('empresa', parent=styles['Normal'],
                                fontSize=16, leading=20, alignment=TA_CENTER,
                                textColor=colors.HexColor('#1a3d6b'), spaceAfter=2)
    st_subempresa = ParagraphStyle('subempresa', parent=styles['Normal'],
                                   fontSize=9, alignment=TA_CENTER,
                                   textColor=colors.grey, spaceAfter=4)
    st_titulo = ParagraphStyle('titulo', parent=styles['Normal'],
                               fontSize=13, leading=16, alignment=TA_CENTER,
                               spaceBefore=10, spaceAfter=14, fontName='Helvetica-Bold')
    st_normal = ParagraphStyle('cuerpo', parent=styles['Normal'],
                              fontSize=10.5, leading=16, alignment=TA_JUSTIFY,
                              spaceAfter=8)
    st_label = ParagraphStyle('label', parent=styles['Normal'],
                             fontSize=9, textColor=colors.grey)
    st_val = ParagraphStyle('val', parent=styles['Normal'],
                           fontSize=11, fontName='Helvetica-Bold')

    story = []

    # ── Encabezado ──
    story.append(Paragraph(EMPRESA_NOMBRE, st_empresa))
    story.append(Paragraph(EMPRESA_DETALLE, st_subempresa))
    story.append(HRFlowable(width="100%", thickness=1.2,
                            color=colors.HexColor('#1a3d6b'), spaceAfter=6))
    story.append(Paragraph("NOTIFICACIÓN DE AUTORIZACIÓN DE VACACIONES", st_titulo))

    # ── Datos del empleado (tabla) ──
    def fila(label, val):
        return [Paragraph(label, st_label), Paragraph(val or '—', st_val)]

    tabla_emp = Table([
        fila("Empleado", datos.get('empleado_nombre')),
        fila("DNI", datos.get('empleado_dni')),
        fila("Legajo", str(datos.get('empleado_legajo') or '—')),
        fila("Puesto", datos.get('empleado_puesto')),
        fila("Área", datos.get('empleado_area')),
    ], colWidths=[4*cm, 12*cm])
    tabla_emp.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -2), 0.4, colors.HexColor('#e0e0e0')),
    ]))
    story.append(tabla_emp)
    story.append(Spacer(1, 14))

    # ── Texto de notificación ──
    dias = datos.get('dias') or 0
    desde = _fmt_fecha(datos.get('fecha_desde'))
    hasta = _fmt_fecha(datos.get('fecha_hasta'))
    cuerpo = (
        f"Por la presente se notifica que se ha <b>AUTORIZADO</b> el período de "
        f"vacaciones solicitado por el/la empleado/a, conforme al siguiente detalle:"
    )
    story.append(Paragraph(cuerpo, st_normal))

    # ── Período (destacado) ──
    tabla_periodo = Table([
        [Paragraph("Desde", st_label), Paragraph("Hasta", st_label), Paragraph("Días", st_label)],
        [Paragraph(desde, st_val), Paragraph(hasta, st_val),
         Paragraph(f"{dias} día(s)", st_val)],
    ], colWidths=[5.3*cm, 5.3*cm, 5.3*cm])
    tabla_periodo.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#1a3d6b')),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#c5d4e8')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef3fa')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(tabla_periodo)
    story.append(Spacer(1, 12))

    if datos.get('motivo'):
        story.append(Paragraph(f"<b>Observaciones:</b> {datos.get('motivo')}", st_normal))

    # ── Autorización ──
    autoriz = datos.get('autorizada_por') or '—'
    fecha_aut = _fmt_fecha(datos.get('fecha_autorizacion'))
    story.append(Paragraph(
        f"Autorizado por <b>{autoriz}</b> en representación de la empresa, "
        f"con fecha {fecha_aut}.", st_normal))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "El/la empleado/a declara estar notificado/a del período de vacaciones "
        "autorizado, dejando constancia con su firma al pie del presente documento.",
        st_normal))

    story.append(Spacer(1, 50))

    # ── Firmas ──
    linea = "_" * 32
    tabla_firmas = Table([
        [linea, linea],
        [Paragraph("Firma del Empleado/a", ParagraphStyle('f', parent=st_normal, alignment=TA_CENTER, fontSize=9)),
         Paragraph("Firma y sello del Empleador", ParagraphStyle('f', parent=st_normal, alignment=TA_CENTER, fontSize=9))],
        [Paragraph(f"Aclaración: {datos.get('empleado_nombre','')}", ParagraphStyle('a', parent=st_label, alignment=TA_CENTER)),
         Paragraph(f"Aclaración: {EMPRESA_NOMBRE}", ParagraphStyle('a', parent=st_label, alignment=TA_CENTER))],
    ], colWidths=[8*cm, 8*cm])
    tabla_firmas.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 1), (-1, 1), 4),
        ('TOPPADDING', (0, 2), (-1, 2), 2),
    ]))
    story.append(tabla_firmas)

    # ── Pie ──
    story.append(Spacer(1, 30))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#cccccc')))
    pie = ParagraphStyle('pie', parent=styles['Normal'], fontSize=7.5,
                         textColor=colors.grey, alignment=TA_CENTER)
    story.append(Paragraph(
        f"Documento generado por Pucara el {datetime.now().strftime('%d/%m/%Y %H:%M')} hs. "
        f"— {EMPRESA_NOMBRE}", pie))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


if __name__ == '__main__':
    # Prueba
    datos = {
        'empleado_nombre': 'JUAN PÉREZ', 'empleado_dni': '30.123.456',
        'empleado_legajo': '042', 'empleado_puesto': 'Técnico de campo',
        'empleado_area': 'Operaciones',
        'fecha_desde': '2026-07-15', 'fecha_hasta': '2026-07-29', 'dias': 14,
        'autorizada_por': 'María Gómez (RRHH)',
        'fecha_autorizacion': '2026-06-30',
        'motivo': 'Vacaciones anuales',
    }
    pdf = generar_comprobante_vacaciones(datos)
    with open('/tmp/comprobante_test.pdf', 'wb') as f:
        f.write(pdf)
    print(f"✓ PDF generado: {len(pdf)} bytes")
