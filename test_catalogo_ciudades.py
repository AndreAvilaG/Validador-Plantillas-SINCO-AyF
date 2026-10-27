"""Pruebas de los códigos de ciudades y departamentos (Terceros y Centros de Costos).

Qué se protege:
  * La lista de validación ES el catálogo de SINCO (hoja CIUDADES-DEPARTAMENTOS de la plantilla de Terceros): 1.123 pares. Antes
    tenía 99 pares que SINCO no tiene (aceptaba datos que SINCO rechaza) y le faltaban 6 áreas no municipalizadas.
  * El reporte (PDF) y la pantalla muestran el PAR «departamento / ciudad». Antes el PDF aplanaba todos los códigos en una sola lista
    rotulada «TerCiudad» y sin repetidos, y códigos válidos (ej. 001 o 63) parecían marcados como error.

Cómo correrlas (desde la raíz del repositorio):  pip install pytest pypdf   y luego   pytest pruebas
Los datos son inventados: no se deben agregar archivos de clientes a este repositorio.
"""
import io
import os
import re

import pytest

from _cargador import cargar, ejecutar, llenar_empresa

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Pares que la lista anterior aceptaba y que el catálogo de SINCO NO tiene (SINCO los rechazaría al importar).
PARES_QUE_SINCO_NO_TIENE = [
    ('05', '288'), ('05', '290'), ('05', '911'), ('05', '921'), ('05', '938'), ('05', '947'), ('05', '966'),
    ('08', '879'), ('08', '905'), ('13', '898'), ('15', '524'), ('15', '527'), ('15', '539'), ('15', '553'),
    ('15', '558'), ('15', '562'), ('15', '564'), ('15', '812'), ('15', '864'), ('15', '866'), ('15', '873'),
    ('15', '902'), ('17', '533'), ('17', '543'), ('17', '547'), ('19', '155'), ('19', '853'), ('19', '893'),
    ('19', '907'), ('20', '800'), ('23', '370'), ('23', '374'), ('23', '381'), ('23', '861'), ('23', '874'),
    ('23', '877'), ('23', '897'), ('25', '130'), ('25', '819'), ('25', '822'), ('25', '824'), ('47', '339'),
    ('50', '790'), ('50', '800'), ('50', '840'), ('52', '294'), ('52', '324'), ('52', '325'), ('52', '436'),
    ('52', '790'), ('52', '905'), ('54', '674'), ('54', '905'), ('66', '616'), ('66', '653'), ('66', '736'),
    ('66', '838'), ('68', '873'), ('70', '243'), ('70', '247'), ('70', '250'), ('70', '258'), ('70', '828'),
    ('70', '835'), ('70', '845'), ('73', '354'), ('73', '357'), ('73', '359'), ('73', '361'), ('73', '363'),
    ('73', '365'), ('73', '367'), ('73', '371'), ('73', '377'), ('73', '381'), ('73', '383'), ('73', '385'),
    ('73', '387'), ('73', '389'), ('73', '391'), ('73', '393'), ('73', '395'), ('73', '397'), ('76', '155'),
    ('76', '200'), ('76', '257'), ('76', '263'), ('76', '871'), ('76', '873'), ('76', '877'), ('85', '025'),
    ('85', '030'), ('85', '031'), ('85', '036'), ('86', '318'), ('86', '758'), ('88', '194'), ('88', '211'),
    ('88', '217'),
]
# Áreas no municipalizadas (Amazonas, Guainía y Vaupés): están en SINCO; seis de ellas faltaban en la lista anterior.
AREAS_NO_MUNICIPALIZADAS = [
    ('91', '263'), ('91', '405'), ('91', '407'), ('91', '430'), ('91', '460'), ('91', '530'), ('91', '536'),
    ('91', '669'), ('91', '798'), ('94', '343'), ('94', '663'), ('94', '883'), ('94', '884'), ('94', '885'),
    ('94', '886'), ('94', '887'), ('94', '888'), ('97', '511'), ('97', '777'), ('97', '889'),
]


def _catalogo():
    """La lista de ciudades y departamentos que usa la validación (resuelve las dependencias que haga falta al ejecutarla)."""
    return ejecutar(["cargar_catalogos"], lambda ns: ns["cargar_catalogos"]()[2])


# ───────────────────────── La lista de validación es el catálogo de SINCO ─────────────────────────
def test_el_catalogo_tiene_los_1123_pares_de_sinco():
    catalogo = _catalogo()
    assert len(catalogo) == 1123
    assert len({d for d, _ in catalogo}) == 33


def test_los_codigos_tienen_el_formato_de_sinco():
    """Departamento de 2 dígitos y ciudad de 3, como texto: así están en la hoja CIUDADES-DEPARTAMENTOS."""
    assert all(re.fullmatch(r"\d{2}", d) and re.fullmatch(r"\d{3}", c) for d, c in _catalogo())


def test_el_catalogo_trae_las_areas_no_municipalizadas():
    catalogo = _catalogo()
    assert [p for p in AREAS_NO_MUNICIPALIZADAS if p not in catalogo] == []


def test_el_catalogo_ya_no_acepta_pares_que_sinco_rechaza():
    """Regresión: la lista anterior tenía 99 pares inexistentes (ej. 18 códigos seguidos inventados en el Tolima)."""
    aceptados = [p for p in PARES_QUE_SINCO_NO_TIENE if p in _catalogo()]
    assert aceptados == []


@pytest.mark.parametrize("par", [("76", "892"), ("11", "001"), ("05", "001"), ("63", "001"), ("91", "407"), ("94", "888")])
def test_pares_validos_de_sinco_se_aceptan(par):
    assert par in _catalogo()


@pytest.mark.parametrize("par", [("63", "520"), ("63", "170"), ("11", "401"), ("76", "155"), ("73", "354"), ("99", "999")])
def test_pares_que_no_existen_se_rechazan(par):
    """63/520 es el caso típico de los datos: 520 es Palmira (76), no un municipio del Quindío (63)."""
    assert par not in _catalogo()


# ───────────────────────── El par se muestra completo ─────────────────────────
def _valores(clave, mensaje):
    ns, *_ = cargar(["_valores_de_mensaje", "_CLAVES_DE_PAR_DEPARTAMENTO_CIUDAD"])
    return ns["_valores_de_mensaje"](clave, mensaje)


def test_el_error_de_terceros_muestra_el_par_completo():
    msg = '🔵 La combinación Departamento "63" / Ciudad "401" no existe en el catálogo. Consulta la hoja CIUDADES-DEPARTAMENTOS.'
    assert _valores("Ciudad o departamento no válidos.", msg) == ["63 / 401"]


def test_el_error_de_centros_de_costos_muestra_el_par_completo():
    msg = 'La combinación de departamento "76" y ciudad "892" no corresponde a ningún municipio registrado.'
    assert _valores("Combinación ciudad+departamento no registrada", msg) == ["76 / 892"]


def test_los_demas_errores_siguen_mostrando_cada_valor_citado():
    assert _valores("Cualquier otra clave.", 'El NIT "123" no coincide con "456"') == ["123", "456"]
    assert _valores("Ciudad o departamento no válidos.", 'Solo un valor "63"') == ["63"]      # sin par completo: no se inventa
    assert _valores("Cualquier otra clave.", "sin comillas") == []


def _errores_de_ciudad():
    pares = [("63", "170"), ("76", "401"), ("11", "295"), ("63", "122"), ("20", "170"), ("63", "520"), ("05", "473"), ("63", "001x")]
    return [(5 + i, "TerCiudad", "logica", f'🔵 La combinación Departamento "{d}" / Ciudad "{c}" no existe en el catálogo.',
             "Ciudad o departamento no válidos.") for i, (d, c) in enumerate(pares)], pares


def test_el_pdf_muestra_el_par_departamento_ciudad():
    """Regresión: el PDF listaba todos los códigos mezclados, sin repetidos y bajo el rótulo «TerCiudad»."""
    pypdf = pytest.importorskip("pypdf")
    errores, pares = _errores_de_ciudad()
    reemplazo = {"generar_pdf_inconsistencias": [("except Exception:\n        return None", "except Exception:\n        raise")]}
    pdf = ejecutar(["generar_pdf_inconsistencias"], lambda ns: ns["generar_pdf_inconsistencias"](
        "Reporte de Inconsistencias — Plantillas Maestras", [("Terceros", errores)], "Cliente de prueba", "999000001"), reemplazos=reemplazo)
    assert pdf and pdf[:4] == b"%PDF"
    texto = " ".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    texto = re.sub(r"\s+", " ", texto)
    assert "Departamento / Ciudad" in texto
    assert f"{len(pares)} valores encontrados" in texto
    for d, c in pares:
        assert f"{d} / {c}" in texto, (d, c)
    assert "valores encontrados — TerCiudad" not in texto


# ───────────────────────── En pantalla ─────────────────────────
COLUMNAS_TERCEROS = ["Tipo identificación", "Número de identificación", "Dígito de verificación", "Naturaleza Jurídica",
                     "Razon social - personas juridicas", "Nombre 1", "Nombre 2", "Apellido 1", "Apellido 2", "Tipo tercero", "Subtipo",
                     "TerEstado", "Actividad Económica Principal", "Vencimiento facturas", "Dirección", "Telefono", "Celular",
                     "TerDepartamento", "TerCiudad", "Nombre contacto principal", "Email contacto principal", "Cargo contacto principal",
                     "Representante legal", "Número identificación representante legal", "TerExpedicionRL", "Email representante legal",
                     "Banco", "Tipo Cuenta", "Número cuenta", "Email Tesorería", "Gran contribuyente", "Responsable de IVA",
                     "Regimen especial", "Obligado a facturar", "Auto retenedor", "Auto retenedor ICA", "Exento Retención",
                     "Declarante de renta", "Profesional independiente", "Agente retenedor IVA", "Gran contribuyente de ICA Bogotá",
                     "Email certificados", "Agente retenedor de ICA", "Regimen simple de tributacion"]


def _terceros_con(pares):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MIGRACION"
    ws.append(COLUMNAS_TERCEROS)
    for i, (dep, ciu) in enumerate(pares):
        fila = {c: None for c in COLUMNAS_TERCEROS}
        fila.update({"Tipo identificación": "NIT", "Número de identificación": str(900100200 + i), "Dígito de verificación": "0",
                     "Naturaleza Jurídica": "J", "Razon social - personas juridicas": f"EMPRESA DE PRUEBA {i}", "Tipo tercero": "P",
                     "Subtipo": "4", "TerEstado": "0", "Dirección": "CALLE 1 # 2-3", "TerDepartamento": dep, "TerCiudad": ciu})
        ws.append([fila[c] for c in COLUMNAS_TERCEROS])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_la_pantalla_muestra_el_par_y_el_rotulo_departamento_ciudad():
    pytest.importorskip("openpyxl")
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(os.path.join(RAIZ, "validador_sinco_ayf.py"), default_timeout=180)
    app.run()
    next(b for b in app.button if b.label == "➡️ Iniciar validación").click().run()
    radio = app.radio[0]
    radio.set_value([o for o in radio.options if "Ya tengo mis plantillas" in o][0]).run()
    llenar_empresa(app)                                       # en la Etapa 1 el nombre y el NIT son obligatorios para validar
    cargador = next(f for f in app.file_uploader if f.key == "terceros_e1" or f.key.startswith("terceros_e1_"))
    cargador.set_value([("t.xlsx", _terceros_con([("63", "520"), ("63", "001"), ("15", "999")]), XLSX)]).run()
    assert not app.exception, [str(e.value) for e in app.exception]
    html = " ".join(m.value for m in app.markdown)
    assert "63 / 520" in html and "15 / 999" in html          # los pares inexistentes, completos
    assert "Departamento / Ciudad" in html                   # el rótulo correcto
    assert "63 / 001" not in html                            # 63/001 (Armenia) existe en SINCO: no es un error
