"""Pruebas del formato de los códigos de departamento y ciudad en Centros de Costos (Etapa 1).

Qué se protege:
  * SINCO compara el código como TEXTO TAL CUAL: el departamento de 2 dígitos y la ciudad de 3, como en su hoja CIUDADES-DEPARTAMENTOS.
    Al migrar, rechazó el departamento «8» (debe ser «08») y, como consecuencia, tampoco encontró la ciudad «433» en él.
    La validación rellenaba con ceros antes de comparar y por eso no lo detectaba.
  * Lo que ya estaba bien sigue estando bien: pares válidos pasan, un par inexistente (con formato correcto) sigue marcándose,
    y los campos vacíos o a medias siguen su regla de siempre.
  * El asistente de Centros de Costos escribe los códigos con el formato de SINCO.

Cómo correrlas (desde la raíz del repositorio):  pip install pytest   y luego   pytest pruebas
Los datos son inventados: no se deben agregar archivos de clientes a este repositorio.
"""
import io
import os
import re

import pytest

from _cargador import ejecutar

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FORMATO_DEPTO = "Departamento con formato inválido"
FORMATO_CIUDAD = "Ciudad con formato inválido"
PAR_NO_REGISTRADO = "Combinación ciudad+departamento no registrada"
CLAVES_DE_UBICACION = (FORMATO_DEPTO, FORMATO_CIUDAD, PAR_NO_REGISTRADO)


def _errores_de_ubicacion(depto, ciudad, tipo="A"):
    """Errores de ubicación que da validar_centros_costos para una fila con ese departamento y esa ciudad."""
    import pandas as pd

    def correr(ns):
        _, _, ciudades, _ = ns["cargar_catalogos"]()
        df = pd.DataFrame([{"Código": "01010801", "Descripción": "X", "Tipo": tipo, "Codigo Departamento": depto,
                            "Codigo Ciudad": ciudad, "Mandante": "", "Sucursal Administrativa": "0" if tipo == "A" else ""}])
        return [e for e in ns["validar_centros_costos"](df, ciudades) if e[4] in CLAVES_DE_UBICACION]

    return ejecutar(["validar_centros_costos", "cargar_catalogos", "normalizar_depto", "normalizar_ciudad"], correr)


# ───────────────────────── El caso reportado por SINCO ─────────────────────────
def test_el_departamento_sin_cero_inicial_se_marca():
    """Regresión: «8» / «433» pasaba sin aviso y SINCO lo rechazó al migrar."""
    errores = _errores_de_ubicacion("8", "433")
    assert [e[4] for e in errores] == [FORMATO_DEPTO]
    assert errores[0][1] == "Codigo Departamento"
    assert '"8"' in errores[0][3] and "por ejemplo: 08" in errores[0][3]


def test_con_el_formato_mal_no_se_da_ademas_el_aviso_de_par_no_registrado():
    """Un solo aviso claro, no dos: el par se busca solo cuando el formato es correcto."""
    assert PAR_NO_REGISTRADO not in [e[4] for e in _errores_de_ubicacion("8", "433")]


@pytest.mark.parametrize("depto,ciudad,esperado", [
    ("008", "433", [FORMATO_DEPTO]),                       # ceros de más
    ("1", "001", [FORMATO_DEPTO]),                         # departamento de 1 dígito
    ("123", "001", [FORMATO_DEPTO]),                       # de 3 dígitos
    ("08", "0433", [FORMATO_CIUDAD]),                      # ciudad de 4 dígitos
    ("08", "33", [FORMATO_CIUDAD]),                        # ciudad de 2 dígitos
    ("08", "3333", [FORMATO_CIUDAD]),
    ("8", "33", [FORMATO_DEPTO, FORMATO_CIUDAD]),          # los dos mal
    (" 8 ", "433", [FORMATO_DEPTO]),                       # con espacios alrededor: se mira el valor
])
def test_codigos_con_formato_invalido_se_marcan(depto, ciudad, esperado):
    assert [e[4] for e in _errores_de_ubicacion(depto, ciudad)] == esperado


def test_el_ejemplo_del_aviso_es_el_codigo_bien_escrito():
    assert "por ejemplo: 08" in _errores_de_ubicacion("8", "433")[0][3]
    assert "por ejemplo: 033" in _errores_de_ubicacion("08", "33")[0][3]
    assert "por ejemplo: 001" in _errores_de_ubicacion("08", "0001")[0][3]       # 0001 -> 001
    assert "por ejemplo: 001" in _errores_de_ubicacion("08", "01")[0][3]         # 01 -> 001


# ───────────────────────── Lo que ya estaba bien sigue igual ─────────────────────────
@pytest.mark.parametrize("depto,ciudad", [("08", "433"), ("76", "892"), ("11", "001"), ("91", "407"), ("05", "001"), ("94", "888")])
def test_pares_validos_con_el_formato_de_sinco_no_se_marcan(depto, ciudad):
    assert _errores_de_ubicacion(depto, ciudad) == []


def test_un_par_inexistente_con_formato_correcto_sigue_marcandose():
    assert [e[4] for e in _errores_de_ubicacion("08", "132")] == [PAR_NO_REGISTRADO]       # 132 no es un municipio de Atlántico


def test_los_campos_vacios_o_a_medias_siguen_su_regla():
    assert _errores_de_ubicacion("", "") == []                                              # ambos vacíos en un auxiliar: lo marca CC-16, no esta regla
    assert _errores_de_ubicacion("", "", tipo="M") == []                                    # un maestro puede no tenerlos
    assert _errores_de_ubicacion("8", "") == []                                             # a medias: lo marca CC-06, no esta regla
    assert _errores_de_ubicacion("", "433") == []


# ───────────────────────── Con un Excel de verdad ─────────────────────────
def _excel_cc(filas):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MIGRACION"
    ws.append(["Código", "Descripción", "Tipo", "Codigo Departamento", "Codigo Ciudad", "Mandante", "Sucursal Administrativa"])
    for f in filas:
        ws.append(f)
    return wb


def test_un_numero_8_en_la_celda_se_marca_y_el_texto_08_no():
    """Excel guarda 8 como número aunque la celda se vea «08» con formato: lo que se compara es lo guardado."""
    wb = _excel_cc([["01010801", "NUMERO", "A", 8, 433, None, "0"],
                    ["01010802", "TEXTO CORRECTO", "A", "08", "433", None, "0"],
                    ["01010803", "TEXTO SIN CERO", "A", "8", "433", None, "0"]])
    b = io.BytesIO()
    wb.save(b)

    def correr(ns):
        _, _, ciudades, _ = ns["cargar_catalogos"]()
        df, err = ns["leer_migracion"](io.BytesIO(b.getvalue()))
        if err and "is not defined" in str(err):      # leer_migracion atrapa sus propios errores: se lo pasa al cargador para que agregue la dependencia
            raise NameError(str(err))
        assert not err, err
        return [(e[0], e[4]) for e in ns["validar_centros_costos"](df, ciudades) if e[4] in CLAVES_DE_UBICACION]

    r = ejecutar(["validar_centros_costos", "cargar_catalogos", "normalizar_depto", "normalizar_ciudad", "leer_migracion"], correr)
    assert sorted(r) == [(2, FORMATO_DEPTO), (4, FORMATO_DEPTO)]                            # filas 2 y 4 de Excel; la 3 ('08') pasa


# ───────────────────────── El asistente escribe el formato de SINCO ─────────────────────────
def test_el_asistente_escribe_los_codigos_con_el_formato_de_sinco():
    assert ejecutar(["resolver_codigo_ciudad"], lambda ns: ns["resolver_codigo_ciudad"]("Atlántico", "Malambo")) == ("08", "433")


def test_todos_los_codigos_del_catalogo_de_los_asistentes_tienen_2_y_3_digitos():
    def codigos(ns):
        _, _, por_depto = ns["_cargar_deptos_ciudades"]()
        return [(d, c) for d, municipios in por_depto.items() for c in municipios.values()]
    pares = ejecutar(["_cargar_deptos_ciudades"], codigos)
    assert pares and all(re.fullmatch(r"\d{2}", d) and re.fullmatch(r"\d{3}", c) for d, c in pares)


# ───────────────────────── En pantalla ─────────────────────────
def test_la_pantalla_explica_el_error_de_un_departamento_sin_cero():
    pytest.importorskip("openpyxl")
    from streamlit.testing.v1 import AppTest
    wb = _excel_cc([["010108", "MAESTRO", "M", None, None, None, None], ["01010801", "AUXILIAR", "A", "8", "433", None, "0"]])
    b = io.BytesIO()
    wb.save(b)
    app = AppTest.from_file(os.path.join(RAIZ, "validador_sinco_ayf.py"), default_timeout=180)
    app.run()
    next(x for x in app.button if x.label == "➡️ Iniciar validación").click().run()
    radio = app.radio[0]
    radio.set_value([o for o in radio.options if "Ya tengo mis plantillas" in o][0]).run()
    next(f for f in app.file_uploader if f.key == "cc_e1" or f.key.startswith("cc_e1_")).set_value([("cc.xlsx", b.getvalue(), XLSX)]).run()
    assert not app.exception, [str(e.value) for e in app.exception]
    texto = re.sub(r"<[^>]+>", " ", " ".join(m.value for m in app.markdown))
    assert "Código de departamento mal escrito" in texto
    assert "SINCO rechaza, por ejemplo, 8 en lugar de 08" in texto
