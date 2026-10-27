"""Pruebas del nombre y el NIT obligatorios para validar plantillas en la Etapa 1.

Qué se protege (decisión de Andrea):
  * Etapa 1, opción «Ya tengo mis plantillas — solo validarlas»: sin nombre de la empresa y sin un NIT válido NO se muestra la
    validación; se explica qué falta. Así el reporte y el seguimiento (el director) saben a qué empresa corresponde.
  * NO cambian: los dos asistentes de la Etapa 1 (PUC y Centros de Costos) y las Etapas 2, 3 y 4 (que toman el nombre y el NIT del informe).
  * La regla del NIT es la misma que usa el seguimiento (seguimiento.normalizar_nit): si no, la app podría dejar pasar un NIT que luego
    se guardaría como SIN-IDENTIFICAR.

Cómo correrlas (desde la raíz del repositorio):  pip install pytest   y luego   pytest pruebas
Los datos son inventados: no se deben agregar archivos de clientes a este repositorio.
"""
import io
import os
import re
import sys

import pytest

from _cargador import ejecutar, llenar_empresa

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
AVISO = "Antes de validar, identifica la empresa"
ETAPA_2 = "Etapa 2 — Saldos CxC / CxP"
ETAPA_3 = "Etapa 3 — SI y Movimientos"
ETAPA_4 = "Etapa 4 — Conciliación"


def _nit_valido(texto):
    return ejecutar(["_nit_valido_e1"], lambda ns: ns["_nit_valido_e1"](texto))


def _pendientes(nombre, nit):
    return ejecutar(["_identificacion_pendiente_e1"], lambda ns: ns["_identificacion_pendiente_e1"](nombre, nit))


# ───────────────────────── La regla del NIT ─────────────────────────
@pytest.mark.parametrize("nit", ["901652178", "901.652.178-8", "901652178-8", "901.652.178 - 8", "9016521788", " 830123456 ", "NIT 901652178",
                                 "12345", "123456789012", "901,652,178-8"])
def test_nits_validos(nit):
    assert _nit_valido(nit) is True


@pytest.mark.parametrize("nit", ["", "   ", "1234", "1234567890123", "abc", "12-34", "-", "NIT", "123-456789", None])
def test_nits_no_validos(nit):
    assert _nit_valido(nit) is False


def test_la_regla_del_nit_es_la_misma_del_seguimiento():
    """Si estas dos reglas se separan, la app podría dar por bueno un NIT que el seguimiento guarda como SIN-IDENTIFICAR."""
    sys.path.insert(0, RAIZ)
    from seguimiento import normalizar_nit
    muestras = ["901652178", "901.652.178-8", "9016521788", "830123456", "12345", "1234", "123456789012", "1234567890123", "abc", "", "  ", "-",
                "12-34", "123-456789", "901,652,178 -8", "NIT 901652178", "0", "00000", "8001234567", "9999999999"]
    assert [_nit_valido(m) for m in muestras] == [bool(normalizar_nit(m)) for m in muestras]


# ───────────────────────── Qué le falta al usuario ─────────────────────────
def test_sin_nada_pide_el_nombre_y_el_nit():
    p = _pendientes("", "")
    assert len(p) == 2 and "nombre de la empresa" in p[0] and "NIT" in p[1]


def test_con_nombre_solo_pide_el_nit():
    p = _pendientes("Empresa XYZ S.A.S.", "")
    assert len(p) == 1 and "NIT" in p[0] and "nombre" not in p[0]


def test_con_nit_solo_pide_el_nombre():
    p = _pendientes("   ", "901652178")
    assert len(p) == 1 and "nombre de la empresa" in p[0]


def test_con_un_nit_no_valido_lo_muestra_y_explica():
    p = _pendientes("Empresa XYZ S.A.S.", "123")
    assert len(p) == 1 and "«123»" in p[0] and "entre 5 y 12 dígitos" in p[0]


def test_con_todo_bien_no_pide_nada():
    assert _pendientes("Empresa XYZ S.A.S.", "901.652.178-8") == []


def test_el_nit_escrito_se_muestra_sin_poder_inyectar_html():
    p = _pendientes("Empresa", '<img src=x onerror=alert(1)>')
    assert "<img" not in p[0] and "&lt;img" in p[0]


# ───────────────────────── En pantalla ─────────────────────────
def _excel_cc():
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MIGRACION"
    ws.append(["Código", "Descripción", "Tipo", "Codigo Departamento", "Codigo Ciudad", "Mandante", "Sucursal Administrativa"])
    ws.append(["010108", "MAESTRO", "M", None, None, None, None])
    ws.append(["01010801", "AUXILIAR", "A", "8", "433", None, "0"])                # con un error: el departamento sin cero inicial
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _app():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(os.path.join(RAIZ, "validador_sinco_ayf.py"), default_timeout=180)
    app.run()
    return app


def _caja(app, base):
    return next(c for c in app.text_input if (c.key or "").startswith(base))


def _texto(app):
    """Todo el texto de la página sin etiquetas HTML y con los espacios normalizados."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", " ".join(m.value for m in app.markdown)))


def _e1_validar_con_plantilla():
    """Etapa 1, «Ya tengo mis plantillas», con una plantilla cargada y SIN nombre ni NIT."""
    pytest.importorskip("openpyxl")
    app = _app()
    next(b for b in app.button if b.label == "➡️ Iniciar validación").click().run()
    radio = app.radio[0]
    radio.set_value([o for o in radio.options if "Ya tengo mis plantillas" in o][0]).run()
    next(f for f in app.file_uploader if f.key == "cc_e1" or f.key.startswith("cc_e1_")).set_value([("cc.xlsx", _excel_cc(), XLSX)]).run()
    assert not app.exception, [str(e.value) for e in app.exception]
    return app


def test_sin_nombre_ni_nit_no_se_valida_y_se_explica_que_falta():
    app = _e1_validar_con_plantilla()
    t = _texto(app)
    assert AVISO in t and "nombre de la empresa" in t and "NIT" in t
    assert "Código de departamento mal escrito" not in t                      # la validación no se muestra


def test_al_escribir_el_nombre_y_el_nit_se_valida_automaticamente():
    app = _e1_validar_con_plantilla()
    llenar_empresa(app)
    t = _texto(app)
    assert AVISO not in t
    assert "Código de departamento mal escrito" in t                          # ahora sí aparece la validación (de la plantilla ya cargada)


def test_con_solo_el_nombre_el_aviso_pide_unicamente_el_nit():
    app = _e1_validar_con_plantilla()
    _caja(app, "nombre_empresa").set_value("Empresa XYZ S.A.S.").run()
    t = _texto(app)
    assert AVISO in t and "Escribe el NIT" in t and "Escribe el nombre de la empresa" not in t


def test_con_un_nit_no_valido_sigue_sin_validar_y_lo_muestra():
    app = _e1_validar_con_plantilla()
    _caja(app, "nombre_empresa").set_value("Empresa XYZ S.A.S.").run()
    _caja(app, "nit_empresa").set_value("123").run()
    t = _texto(app)
    assert AVISO in t and "«123» no es válido" in t
    assert "Código de departamento mal escrito" not in t


# ───────────────────────── Lo que NO cambia ─────────────────────────
@pytest.mark.parametrize("opcion", ["Crear mi PUC con el asistente", "Crear mi Centro de Costos con el asistente"])
def test_los_asistentes_no_piden_nombre_ni_nit(opcion):
    app = _app()
    next(b for b in app.button if b.label == "➡️ Iniciar validación").click().run()
    radio = app.radio[0]
    radio.set_value([o for o in radio.options if opcion in o][0]).run()
    assert not app.exception, [str(e.value) for e in app.exception]
    assert AVISO not in _texto(app)                                           # el asistente se muestra como siempre
    assert _caja(app, "nombre_empresa").value == "" and _caja(app, "nit_empresa").value == ""


@pytest.mark.parametrize("etapa,codigo,secreto,boton", [(ETAPA_2, "codigo_e2", "SINCO2", "➡️ Validar CxC / CxP"),
                                                         (ETAPA_3, "codigo_e3", "SINCO3", "➡️ Validar Saldos"),
                                                         (ETAPA_4, "codigo_e4", "SINCO4", "➡️ Iniciar Conciliación")])
def test_las_etapas_2_3_y_4_no_piden_nombre_ni_nit(etapa, codigo, secreto, boton):
    app = _app()
    next(c for c in app.text_input if (c.key or "").startswith(codigo)).set_value(secreto).run()
    next(b for b in app.button if b.label == boton).click().run()
    assert not app.exception, [str(e.value) for e in app.exception]
    assert AVISO not in _texto(app)
    assert not [c for c in app.text_input if (c.key or "").startswith(("nombre_empresa", "nit_empresa"))]   # ni siquiera se muestran las cajas
