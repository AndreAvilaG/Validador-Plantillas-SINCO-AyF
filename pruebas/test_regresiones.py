"""Pruebas de regresión: errores que ya ocurrieron y no deben reaparecer.

Cómo correrlas (desde la raíz del repositorio):
    pip install pytest pyflakes
    pytest pruebas

Los datos son inventados: no se deben agregar archivos de clientes a este repositorio.
"""
import ast
import os
import sys

import pytest

from _cargador import cargar as _cargar_validador, llenar_empresa

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVOS = ["validador_sinco_ayf.py", "conciliacion.py", "seguimiento.py"]


@pytest.mark.parametrize("archivo", ARCHIVOS)
def test_ningun_archivo_usa_nombres_sin_definir(archivo):
    """Un nombre sin definir solo falla cuando el usuario llega a ese punto (así pasó con nit_label en la
    Etapa 4). Compilar no lo detecta; este análisis estático sí."""
    pyflakes_api = pytest.importorskip("pyflakes.api")
    reportero = pytest.importorskip("pyflakes.reporter")
    import io
    salida, errores = io.StringIO(), io.StringIO()
    ruta = os.path.join(RAIZ, archivo)
    pyflakes_api.check(open(ruta, encoding="utf-8").read(), ruta, reportero.Reporter(salida, errores))
    sin_definir = [l for l in salida.getvalue().splitlines() if "undefined name" in l]
    assert not sin_definir, "\n".join(sin_definir)


def test_conciliacion_con_sugerencia_de_revisar_tercero_no_falla():
    """Regresión: render_conciliacion usaba 'nit_label' (no existe en esa función) y la pantalla de la
    Etapa 4 fallaba con NameError cada vez que el sistema sugería revisar un tercero."""
    pytest.importorskip("reportlab")
    pytest.importorskip("PIL")
    from streamlit.testing.v1 import AppTest
    guion = f'''
import sys
sys.path.insert(0, {RAIZ!r})
import pandas as pd
import conciliacion as c
fila = {{'NIT_key': '900111222', 'Tercero': 'TERCERO UNO', 'Cuenta_key': '13050501', 'CC_key': '01',
        'Documentos': 'ANT1', 'Saldo_Modulo': 1000.0, 'Valor_Cont': 0.0, 'Diferencia': 1000.0,
        'Tipo_Diferencia': '💡 Sugerencia — Revisar tercero', 'Accion': 'Verifique el NIT del tercero.',
        'Explicacion': 'Texto de ejemplo', 'NIT_Plantilla': '900333444', 'CC_Plantilla': '01',
        'Nombre_CC': '', 'Nombre_Cuenta': ''}}
c.render_conciliacion(pd.DataFrame([fila]), 'cxc', 'Cuentas por Cobrar',
                      info_cliente={{'nombre': 'CLIENTE DE PRUEBA', 'nit': '999000001-1', 'nit_label': 'NIT',
                                    'fecha_corte': '2026-05-31'}})
'''
    app = AppTest.from_string(guion)
    app.run(timeout=120)
    assert not app.exception, [str(e.value) for e in app.exception]
    html = " ".join(m.value for m in app.markdown)
    assert "NIT en plantilla: <b>900333444</b>" in html


def test_conciliacion_usa_rnc_cuando_el_cliente_es_de_republica_dominicana():
    """Mismo caso con la etiqueta RNC: el texto debe usar la etiqueta del cliente, no 'NIT' fijo."""
    pytest.importorskip("reportlab")
    pytest.importorskip("PIL")
    from streamlit.testing.v1 import AppTest
    guion = f'''
import sys
sys.path.insert(0, {RAIZ!r})
import pandas as pd
import conciliacion as c
fila = {{'NIT_key': '131234567', 'Tercero': 'TERCERO UNO', 'Cuenta_key': '13050501', 'CC_key': '01',
        'Documentos': 'ANT1', 'Saldo_Modulo': 1000.0, 'Valor_Cont': 0.0, 'Diferencia': 1000.0,
        'Tipo_Diferencia': '💡 Sugerencia — Revisar tercero', 'Accion': 'Verifique el RNC del tercero.',
        'Explicacion': 'Texto de ejemplo', 'NIT_Plantilla': '131999999', 'CC_Plantilla': '01',
        'Nombre_CC': '', 'Nombre_Cuenta': ''}}
c.render_conciliacion(pd.DataFrame([fila]), 'cxc', 'Cuentas por Cobrar',
                      info_cliente={{'nombre': 'CLIENTE RD', 'nit': '131234567', 'nit_label': 'RNC',
                                    'fecha_corte': '2026-05-31'}})
'''
    app = AppTest.from_string(guion)
    app.run(timeout=120)
    assert not app.exception, [str(e.value) for e in app.exception]
    assert "RNC en plantilla: <b>131999999</b>" in " ".join(m.value for m in app.markdown)


# ═════════════════ Alerta estándar de "plantilla incorrecta" (se había perdido en el validador) ═════════════════
PUNTOS_DE_LA_ALERTA = ["PUC Principal", "PUC Fiscal", "Terceros", "Centros de Costos",   # Etapa 1
                       "Saldos CxC", "Saldos CxP",                                         # Etapa 2
                       "Saldos Iniciales", "Movimientos"]                                  # Etapa 3
FRASES_ESTANDAR = ["Revisa la plantilla", "El archivo no cumple con la estructura requerida para realizar la carga.",
                   "Verifica que la plantilla tenga las columnas y el formato definidos, realiza los ajustes necesarios y vuelve a cargar el archivo."]


def _leer(archivo):
    return open(os.path.join(RAIZ, archivo), encoding="utf-8").read()


def _alerta_de(archivo, nombre):
    """HTML que produce _alerta_plantilla_incorrecta de ese archivo para ese nombre (con un streamlit falso)."""
    src = _leer(archivo)
    nodo = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_alerta_plantilla_incorrecta")
    capturado = []
    class St:
        @staticmethod
        def markdown(html, **kw):
            capturado.append(html)
    ns = {"st": St}
    exec(ast.get_source_segment(src, nodo), ns)
    ns["_alerta_plantilla_incorrecta"](nombre)
    return " ".join(capturado)


@pytest.mark.parametrize("nombre", PUNTOS_DE_LA_ALERTA)
def test_el_validador_usa_la_alerta_estandar_en_cada_punto(nombre):
    assert f"_alerta_plantilla_incorrecta('{nombre}')" in _leer("validador_sinco_ayf.py")


def test_el_validador_ya_no_usa_los_mensajes_sueltos_de_lectura():
    """Estos mensajes distintos en cada etapa eran justo lo que la alerta estándar vino a reemplazar."""
    src = _leer("validador_sinco_ayf.py")
    assert "❌ No se pudo leer el archivo: {err}" not in src
    assert "❌ No se pudo leer el archivo: {err_cxc}" not in src and "❌ No se pudo leer el archivo: {err_cxp}" not in src
    assert "❌ No se pudo leer el archivo: <b>{error_lectura}</b>" not in src


def test_el_archivo_de_un_tipo_equivocado_tambien_usa_la_alerta_estandar():
    src = _leer("validador_sinco_ayf.py")
    nodo = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_validar_archivo_correcto")
    assert "_alerta_plantilla_incorrecta(etiqueta_esperada)" in ast.get_source_segment(src, nodo)


@pytest.mark.parametrize("nombre", ["Saldos CxC", "el PUC Principal", "una plantilla de Movimientos", "el informe de Terceros", "la hoja"])
def test_el_texto_de_la_alerta_es_el_estandar_e_igual_en_ambos_archivos(nombre):
    en_validador, en_conciliacion = _alerta_de("validador_sinco_ayf.py", nombre), _alerta_de("conciliacion.py", nombre)
    for frase in FRASES_ESTANDAR:
        assert frase in en_validador and frase in en_conciliacion
    assert en_validador == en_conciliacion            # el mismo mensaje en todas las etapas


@pytest.mark.parametrize("entrada,mostrado", [("el PUC Principal", "PUC Principal"), ("una plantilla de Movimientos", "Movimientos"),
                                              ("el informe de Terceros", "Terceros"), ("Saldos CxC", "Saldos CxC")])
def test_la_alerta_quita_el_articulo_del_nombre(entrada, mostrado):
    assert f"Revisa la plantilla {mostrado}</b>" in _alerta_de("validador_sinco_ayf.py", entrada)


def _libro_xlsx(filas, hoja="Hoja de prueba"):
    import io
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = hoja
    for f in filas:
        ws.append(f)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _cargador(app, base):
    """El cargador de archivos cuyo nombre base es `base`. Su llave lleva el contador de reinicios (puc_principal_0,
    puc_principal_1…), así que se busca por el nombre y no por la llave completa."""
    return next(f for f in app.file_uploader if f.key == base or f.key.startswith(base + "_"))


def _alertas_en_pantalla(app):
    import re
    return re.findall(r"Revisa la plantilla ([^<]+)</b>", " ".join(m.value for m in app.markdown))


def test_etapa1_muestra_la_alerta_con_un_archivo_que_no_es_plantilla():
    pytest.importorskip("openpyxl")
    from streamlit.testing.v1 import AppTest
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    app = AppTest.from_file(os.path.join(RAIZ, "validador_sinco_ayf.py"), default_timeout=180)
    app.run()
    [b for b in app.button if b.label == "➡️ Iniciar validación"][0].click().run()
    radio = app.radio[0]
    radio.set_value([o for o in radio.options if "Ya tengo mis plantillas" in o][0]).run()
    llenar_empresa(app)                                       # en la Etapa 1 el nombre y el NIT son obligatorios para validar
    for clave in ("puc_principal", "puc_fiscal", "terceros_e1", "cc_e1"):
        _cargador(app, clave).set_value([("a.xlsx", _libro_xlsx([["esto", "no", "es"]]), xlsx)]).run()
    assert not app.exception, [str(e.value) for e in app.exception]
    assert _alertas_en_pantalla(app) == ["PUC Principal", "PUC Fiscal", "Terceros", "Centros de Costos"]


def test_etapa2_muestra_la_alerta_con_un_archivo_que_no_es_plantilla():
    pytest.importorskip("openpyxl")
    from streamlit.testing.v1 import AppTest
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    app = AppTest.from_file(os.path.join(RAIZ, "validador_sinco_ayf.py"), default_timeout=180)
    app.run()
    [t for t in app.text_input if t.key == "codigo_e2"][0].set_value("SINCO2").run()
    [b for b in app.button if b.label == "➡️ Validar CxC / CxP"][0].click().run()
    cruce = _libro_xlsx([["Naturaleza", "Cuenta contable", "Cuenta contable nombre"],
                         ["Cuentas por Cobrar", "130505", "NACIONALES"], ["Cuentas por Pagar", "220505", "PROVEEDORES"]])
    for clave, datos in (("saldos_cxc", _libro_xlsx([["x"]])), ("saldos_cxp", _libro_xlsx([["x"]])), ("e2_cuentas_cruce", cruce)):
        _cargador(app, clave).set_value([("a.xlsx", datos, xlsx)]).run()
    [b for b in app.button if b.label == "🔍 Validar plantillas"][0].click().run()
    assert not app.exception, [str(e.value) for e in app.exception]
    assert _alertas_en_pantalla(app) == ["Saldos CxC", "Saldos CxP"]


# ═════════════════ Etapa 4: ya no se exige la factura del proveedor en documentos tipo CP ═════════════════
def _mov_etapa4(encabezado_factura, con_factura):
    import io
    import openpyxl
    src = _leer("conciliacion.py")
    nombres = {"leer_mov", "validar_mov", "detectar_columna", "_detectar_col_tolerante", "limpiar_nit", "limpiar_cuenta", "limpiar_cc"}
    segs = [ast.get_source_segment(src, n) for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name in nombres]
    ns = {}
    exec("import pandas as pd\nimport re\nfrom io import BytesIO\n\n" + "\n\n".join(segs), ns)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MIGRACION"
    ws.append(["Fecha del documento", "Tipo documento", "Consecutivo", encabezado_factura, "Concepto", "Cuenta Contable", "Centro Costos",
               "NIT", "Débito", "Crédito", "Base", "Sucursal", "No Importación", "Tasa de cambio", "Libro"])
    for cuenta, deb, cre in (("11050501", 100, 0), ("22050101", 0, 100)):
        ws.append(["2026-05-01", "CP", 1001, "F-100" if con_factura else None, "x", cuenta, "01", "900123456", deb, cre, None, 0, None, None, None])
    b = io.BytesIO()
    wb.save(b)
    b.seek(0)
    return ns["validar_mov"](ns["leer_mov"](b))


@pytest.mark.parametrize("encabezado", ["Factura del proveedor", "Factura del Proveedor", "Factura del suplidor"])
@pytest.mark.parametrize("con_factura", [True, False])
def test_etapa4_no_marca_documentos_cp_por_la_factura(encabezado, con_factura):
    pytest.importorskip("openpyxl")
    errores = _mov_etapa4(encabezado, con_factura)
    assert not [e for e in errores if "actura" in e], errores


# ═════════════ HTML con líneas vacías: se dibujaba como código ("</div></div>" visible en la Etapa 4) ═════════════
def _plantilla_de(nodo):
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    if isinstance(nodo, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "§" for v in nodo.values)   # § = una {expresión}
    return None


def _bloques_html_con_riesgo(archivo):
    """Llamadas a st.markdown cuyo HTML (varias líneas, empieza por <div, <table...) puede quedar con una línea
    vacía: una línea que es solo una {expresión} (si da vacío, la línea queda vacía) o una línea vacía fija."""
    import re
    tipo6 = re.compile(r"^\s*<(div|table|p|ul|ol|section|details|h[1-6]|blockquote|pre)\b", re.I)
    src = _leer(archivo)
    riesgos = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("markdown", "write", "html") and n.args:
            txt = _plantilla_de(n.args[0])
            if not txt or "\n" not in txt or not tipo6.match(txt):
                continue
            lineas = txt.split("\n")
            fijas = [i for i, l in enumerate(lineas) if l.strip() == "" and 0 < i < len(lineas) - 1]
            solo_expr = [i for i, l in enumerate(lineas) if re.fullmatch(r"\s*(§\s*)+", l)]
            if fijas or solo_expr:
                riesgos.append((n.lineno, fijas, solo_expr))
    return riesgos


@pytest.mark.parametrize("archivo", ["validador_sinco_ayf.py", "conciliacion.py"])
def test_ningun_bloque_html_puede_quedar_con_lineas_vacias(archivo):
    """Regresión: en el encabezado del cliente de la Etapa 4, la línea de la insignia de TRM quedaba vacía cuando el
    cliente no maneja TRM; Markdown cerraba el bloque HTML y los </div> se veían como código. Si hace falta un
    pedazo opcional, debe ir en la misma línea que otro texto o pasar por _sin_lineas_vacias()."""
    assert _bloques_html_con_riesgo(archivo) == []


@pytest.mark.parametrize("html,esperado", [
    ("<div>\n  <b>a</b>\n        \n  </div>", "<div>\n  <b>a</b>\n  </div>"),     # línea solo con espacios
    ("<div>\n\n\n</div>", "<div>\n</div>"),                                        # varias líneas vacías seguidas
    ("<div>\n  x\n</div>", "<div>\n  x\n</div>"),                                  # sin líneas vacías: igual
    ("", ""),
])
def test_sin_lineas_vacias(html, esperado):
    src = _leer("conciliacion.py")
    nodo = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_sin_lineas_vacias")
    ns = {"re": __import__("re")}
    exec(ast.get_source_segment(src, nodo), ns)
    assert ns["_sin_lineas_vacias"](html) == esperado


def test_tarjeta_de_diferencias_sin_terceros_no_se_muestra_como_codigo():
    """Regresión: en la tarjeta de cada grupo de diferencias, si no había nombres de terceros la línea quedaba vacía
    y el mensaje y la acción se dibujaban como código."""
    pytest.importorskip("reportlab")
    pytest.importorskip("PIL")
    from streamlit.testing.v1 import AppTest
    guion = f'''
import sys
sys.path.insert(0, {RAIZ!r})
import pandas as pd
import conciliacion as c
fila = {{'NIT_key': '900111222', 'Tercero': '—', 'Cuenta_key': '13050501', 'CC_key': '01', 'Documentos': 'ANT1',
        'Saldo_Modulo': 1000.0, 'Valor_Cont': 0.0, 'Diferencia': 1000.0, 'Tipo_Diferencia': '🟠 Diferencia de valor',
        'Accion': 'Revise el valor.', 'Explicacion': 'Texto de ejemplo', 'NIT_Plantilla': '', 'CC_Plantilla': '01',
        'Nombre_CC': '', 'Nombre_Cuenta': ''}}
c.render_conciliacion(pd.DataFrame([fila]), 'cxc', 'Cuentas por Cobrar',
                      info_cliente={{'nombre': 'CLIENTE DE PRUEBA', 'nit': '999000001-1', 'nit_label': 'NIT', 'fecha_corte': '2026-05-31'}})
'''
    import re
    app = AppTest.from_string(guion)
    app.run(timeout=120)
    assert not app.exception, [str(e.value) for e in app.exception]
    tarjetas = [m.value for m in app.markdown if "Acción:" in m.value and m.value.lstrip().startswith("<div")]
    assert tarjetas, "no se dibujó la tarjeta de diferencias"
    for t in tarjetas:
        assert not re.search(r"\n[ \t]*\n", t), repr(t)


# ═════════ Municipios: Yumbo (76-892) y otros daban «no corresponde a ningún municipio registrado» ═════════
CODIGOS_EQUIVOCADOS_DE_DIVIPOLA = [("08", "132"), ("15", "532"), ("18", "765"), ("25", "888"),
                                   ("47", "441"), ("52", "695"), ("68", "306"), ("76", "677")]


def _funciones_del_validador(nombres):
    """Namespace con esas funciones y constantes del validador (ver _cargador.py, que resuelve las dependencias que falten)."""
    return _cargar_validador(list(nombres))[0]

def _catalogo_de_validacion():
    return _funciones_del_validador({"_CATALOGO_SINCO_CIUDADES", "_pares_del_catalogo_sinco", "cargar_catalogos"})["cargar_catalogos"]()[2]


def _catalogo_de_los_asistentes():
    ns = _funciones_del_validador({"_CODIGOS_CIUDAD_CORREGIDOS", "_DEPTOS_CIUDADES_B64", "_quitar_tildes", "_normalizar_nombre_lugar",
                                   "_cargar_deptos_ciudades", "_ALIAS_CIUDAD", "_ALIAS_DEPTO"})
    return ns["_cargar_deptos_ciudades"]()[2]


@pytest.mark.parametrize("depto,ciudad,nombre", [("76", "892", "Yumbo"), ("76", "895", "Zarzal"), ("76", "890", "Yotoco"),
                                                 ("76", "041", "Ansermanuevo"), ("25", "899", "Zipaquirá"), ("73", "268", "Espinal"),
                                                 ("63", "130", "Calarcá"), ("13", "468", "Mompós"), ("44", "847", "Uribia"),
                                                 ("27", "086", "Belén de Bajirá")])
def test_el_catalogo_de_validacion_incluye_municipios_que_faltaban(depto, ciudad, nombre):
    """Regresión: estos municipios válidos daban una alerta falsa en Terceros y Centros de Costos."""
    assert (depto, ciudad) in _catalogo_de_validacion(), nombre


def test_el_catalogo_de_validacion_no_tiene_entradas_mal_formadas():
    """Regresión: la lista traía ('76', 'Details'), una entrada basura de la fuente."""
    import re
    mal = [k for k in _catalogo_de_validacion() if not (re.fullmatch(r"\d{2}", k[0]) and re.fullmatch(r"\d{3}", k[1]))]
    assert mal == []


def test_los_codigos_equivocados_de_divipola_no_se_aceptan():
    assert not [p for p in CODIGOS_EQUIVOCADOS_DE_DIVIPOLA if p in _catalogo_de_validacion()]


@pytest.mark.parametrize("depto,nombre,esperado", [("68", "GIRON", "307"), ("08", "JUAN DE ACOSTA", "372"), ("15", "PAYA", "533"),
                                                   ("18", "SOLANO", "756"), ("25", "ZIPACON", "898"), ("47", "PEDRAZA", "541"),
                                                   ("76", "LA CUMBRE", "377"), ("76", "YUMBO", "892")])
def test_el_asistente_escribe_los_codigos_correctos(depto, nombre, esperado):
    """Regresión: el asistente escribiría, por ejemplo, 306 para Girón (el correcto es 307)."""
    assert _catalogo_de_los_asistentes()[depto][nombre] == esperado


def test_todo_codigo_que_escribe_el_asistente_lo_acepta_el_validador():
    """Si el asistente escribe un código, el validador no puede rechazarlo después."""
    validacion = _catalogo_de_validacion()
    escritos = {(d, c) for d, municipios in _catalogo_de_los_asistentes().items() for c in municipios.values()}
    assert escritos - validacion == set()


def test_centros_de_costos_ya_no_marca_a_yumbo():
    import pandas as pd
    ns = _funciones_del_validador({"validar_centros_costos", "vacia", "es_entero", "normalizar_depto", "normalizar_ciudad"})
    def errores_para(depto, ciudad):
        df = pd.DataFrame([{"Código": "01", "Descripción": "ADMIN", "Tipo": "A", "Codigo Departamento": depto,
                            "Codigo Ciudad": ciudad, "Mandante": "", "Sucursal Administrativa": "0"}])
        return [e for e in ns["validar_centros_costos"](df, _catalogo_de_validacion()) if "no corresponde a ningún municipio" in e[3]]
    assert errores_para("76", "892") == []              # Yumbo: es válido
    assert errores_para("76", "001") == []              # Cali
    assert errores_para("08", "132") != []              # el código equivocado de Juan de Acosta sí debe marcarse


# ═════════ Centros de costos: el auxiliar debe tener Código Departamento y Código Ciudad (regla CC-16) ═════════
def _errores_centros_de_costos(filas, **opciones):
    import pandas as pd
    ns = _funciones_del_validador({"validar_centros_costos", "vacia", "es_entero", "normalizar_depto", "normalizar_ciudad"})
    base = {"Código": "01010801", "Descripción": "ITS-INTEMPO", "Tipo": "A", "Codigo Departamento": "", "Codigo Ciudad": "",
            "Mandante": "", "Sucursal Administrativa": "0"}
    df = pd.DataFrame([{**base, **f} for f in filas])
    return ns["validar_centros_costos"](df, _catalogo_de_validacion(), **opciones)


def _claves(errores):
    return sorted({e[4] for e in errores if e[4] in ("Auxiliar sin Departamento", "Auxiliar sin Ciudad")})


def test_auxiliar_sin_departamento_ni_ciudad_se_marca():
    """Regresión: un auxiliar con ambos campos vacíos pasaba sin ninguna observación."""
    errores = [e for e in _errores_centros_de_costos([{}]) if e[4] in ("Auxiliar sin Departamento", "Auxiliar sin Ciudad")]
    assert sorted((e[1], e[4]) for e in errores) == [("Codigo Ciudad", "Auxiliar sin Ciudad"),
                                                     ("Codigo Departamento", "Auxiliar sin Departamento")]
    assert {e[0] for e in errores} == {2}                                   # la fila 2 de Excel (primera fila de datos)
    assert all('"01010801"' in e[3] for e in errores)


def test_maestro_sin_departamento_ni_ciudad_no_se_marca():
    assert _claves(_errores_centros_de_costos([{"Código": "010108", "Tipo": "M", "Sucursal Administrativa": ""}])) == []


def test_auxiliar_con_departamento_y_ciudad_no_se_marca():
    assert _claves(_errores_centros_de_costos([{"Codigo Departamento": "76", "Codigo Ciudad": "892"}])) == []


def test_auxiliar_con_solo_el_departamento_lo_marca_la_regla_existente_sin_duplicar():
    errores = _errores_centros_de_costos([{"Codigo Departamento": "76"}])
    assert _claves(errores) == []
    assert [e for e in errores if e[4] == "Ciudad sin departamento o viceversa"]


def test_cada_fila_de_auxiliar_vacia_se_marca_por_separado():
    errores = _errores_centros_de_costos([{"Código": "01010801"}, {"Código": "01010802"},
                                          {"Código": "01010803", "Codigo Departamento": "76", "Codigo Ciudad": "892"}])
    assert sorted({e[0] for e in errores if e[4] in ("Auxiliar sin Departamento", "Auxiliar sin Ciudad")}) == [2, 3]


def test_el_asistente_no_exige_ubicacion_en_sus_auxiliares_por_ahora():
    """El asistente genera auxiliares sin departamento ni ciudad (Administración, 'otros centros'). Hasta que se decida cómo
    diligenciarlos, su validación interna conserva el comportamiento anterior."""
    assert _claves(_errores_centros_de_costos([{}], exigir_ubicacion_auxiliares=False)) == []
    assert "validar_centros_costos(df_cc, CIUDADES_DEPTO, exigir_ubicacion_auxiliares=False)" in _leer("validador_sinco_ayf.py")


def test_la_validacion_de_plantillas_cargadas_si_exige_la_ubicacion():
    """_validar_cc_cacheado (plantilla que sube el usuario) no debe pasar el parámetro: usa el valor por defecto (exigir)."""
    src = _leer("validador_sinco_ayf.py")
    nodo = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_validar_cc_cacheado")
    assert "exigir_ubicacion_auxiliares" not in ast.get_source_segment(src, nodo)
