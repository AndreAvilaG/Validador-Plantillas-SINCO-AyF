"""Pruebas de las reglas del PUC (Etapa 1) sobre obligaciones financieras y jurisdicción de ReteICA.

Qué se protege:
  * La regla de «obligaciones financieras sin información suficiente» solo aplica a cuentas de PASIVO (clase 2). Una cuenta de
    ingreso (42102001 «Obligaciones financieras e instrumentos derivados») no es una deuda: no se le pide entidad ni número.
  * Una obligación de pasivo SIN entidad o SIN número sigue marcándose (ej.: 210510 «PAGARES» como auxiliar).
  * La jurisdicción de ReteICA se reconoce con el catálogo DIVIPOLA (Palmar de Varela, Tolú…), con palabras completas, sin
    importar tildes, mayúsculas ni separadores; y SIGUE marcándose cuando la descripción no nombra ningún municipio.

Cómo correrlas (desde la raíz del repositorio):  pip install pytest   y luego   pytest pruebas
Los datos son inventados: no se deben agregar archivos de clientes a este repositorio.
"""
import pytest

from test_puc_bancos import _validar


def _avisos(codigo, descripcion, categoria, tipo="A"):
    return [e for e in _validar([(codigo, descripcion)] if tipo == "A" else [], extra_maestros=[(codigo, descripcion)] if tipo == "M" else [])
            if categoria in str(e[4]).lower() and codigo in str(e[3])]


# ───────────────────────── Problema 2: obligaciones financieras ─────────────────────────
OBLIGACION = "obligación financiera"


def test_una_cuenta_de_ingreso_con_nombre_de_obligaciones_financieras_no_se_marca():
    """Regresión: 42102001 (clase 4, ingresos) se marcaba solo porque su nombre dice «obligaciones financieras»."""
    assert _avisos("42102001", "OBLIGACIONES FINANCIERAS E INSTRUMENTOS DERIVADOS", OBLIGACION) == []


@pytest.mark.parametrize("codigo,descripcion", [
    ("53050501", "INTERESES OBLIGACIONES FINANCIERAS"),            # gasto (clase 5)
    ("61350101", "COSTO DE OBLIGACIONES FINANCIERAS"),             # costo (clase 6)
    ("15200501", "LEASING FINANCIERO MAQUINARIA"),                 # activo (clase 1): propiedad, planta y equipo
    ("31050101", "PAGARE DE SOCIOS CAPITAL"),                      # patrimonio (clase 3)
])
def test_cuentas_que_no_son_de_pasivo_no_se_marcan_como_obligaciones(codigo, descripcion):
    assert _avisos(codigo, descripcion, OBLIGACION) == []


def test_pagares_de_pasivo_sin_entidad_ni_numero_sigue_marcandose():
    """210510 «PAGARES» es un auxiliar de pasivo sin entidad ni número: el aviso es correcto y no se elimina."""
    avisos = _avisos("210510", "PAGARES", OBLIGACION)
    assert len(avisos) == 1
    assert "el nombre del banco o entidad financiera" in avisos[0][3] and "el número de la obligación/crédito" in avisos[0][3]


@pytest.mark.parametrize("descripcion,falta,no_falta", [
    ("PAGARE BANCOLOMBIA", "el número de la obligación/crédito", "el nombre del banco"),
    ("PAGARE 456789123", "el nombre del banco o entidad financiera", "el número de la obligación"),
    ("LEASING FINANCIERO", "el nombre del banco o entidad financiera", None),
    ("SOBREGIRO BANCARIO", "el número de la obligación/crédito", None),
])
def test_obligaciones_de_pasivo_a_las_que_realmente_les_falta_informacion_siguen_marcandose(descripcion, falta, no_falta):
    avisos = _avisos("21051001", descripcion, OBLIGACION)
    assert len(avisos) == 1 and falta in avisos[0][3], avisos
    if no_falta:
        assert no_falta not in avisos[0][3]


@pytest.mark.parametrize("descripcion", [
    "PAGARE BANCOLOMBIA 456789123",
    "PAGARE BANCOLOMBIA 456-789-123",
    "LEASING FINANCIERO BANCOLOMBIA OBL 456 789 12",
    "OBLIGACION FINANCIERA DAVIVIENDA 00012345",
])
def test_obligaciones_de_pasivo_completas_no_se_marcan(descripcion):
    assert _avisos("21051001", descripcion, OBLIGACION) == []


# ───────────────────────── Problema 3: jurisdicción de ReteICA ─────────────────────────
RETEICA = "reteica sin detalle"


@pytest.mark.parametrize("codigo,descripcion", [
    ("236831", "RETEICA - PALMAR DE VARELA - ATLANTICO"),           # reportado: municipio compuesto
    ("236832", "RETEICA - TOLU - SUCRE"),                           # reportado: sin tilde
])
def test_las_cuentas_reportadas_de_reteica_ya_no_dan_alerta(codigo, descripcion):
    assert _avisos(codigo, descripcion, RETEICA, tipo="M") == []


@pytest.mark.parametrize("descripcion", [
    "reteica - palmar de varela - atlantico",                       # minúsculas
    "ReteICA – Tolú – Sucre",                                       # raya y tilde
    "RETEICA — TOLÚ",                                               # raya larga
    "RETEICA/BARRANQUILLA",                                         # barra
    "RETEICA (PUERTO COLOMBIA)",                                    # paréntesis y nombre compuesto
    "RETEICA LA ESTRELLA",                                          # compuesto de dos palabras
    "RETEICA SAN JUAN DE PASTO",                                    # compuesto con «DE»
    "RETEICA CARMEN DE VIBORAL",
    "RETEICA YONDO",                                                # el catálogo lo trae como «YONDO (CASABE)»
    "ICA RETENIDO MEDELLÍN",
    "RETEICA BOGOTA",
    "RETEICA BTA",                                                  # sigla de uso común
    "RETEICA CALI",
])
def test_reteica_con_municipio_en_la_descripcion_no_da_alerta(descripcion):
    assert _avisos("236831", descripcion, RETEICA, tipo="M") == []


@pytest.mark.parametrize("descripcion", [
    "RETEICA",
    "RETEICA GENERAL",
    "RETEICA SERVICIOS",
    "RETEICA ATLANTICO",                                            # solo el departamento: no es ciudad ni municipio
    "ICA RETENIDO LOCAL",                                           # antes pasaba por contener «CAL» dentro de «LOCAL»
    "RETEICA MANUAL",                                               # antes pasaba por contener «MAN»
    "RETEICA FISCALIA",                                             # antes pasaba por contener «CALI»
    "RETEICA MEDICOS",                                              # antes pasaba por contener «MED»
])
def test_reteica_sin_municipio_sigue_marcandose(descripcion):
    """Se compara por palabras completas: antes bastaba que apareciera una sigla o nombre DENTRO de otra palabra."""
    avisos = _avisos("236831", descripcion, RETEICA, tipo="M")
    assert len(avisos) == 1, descripcion


def test_el_grupo_de_reteica_se_satisface_con_un_auxiliar_que_nombra_el_municipio():
    sin = [e for e in _validar([("23683101", "RETEICA TOLU")], extra_maestros=[("236831", "RETEICA")]) if RETEICA in str(e[4]).lower()]
    con = [e for e in _validar([("23683101", "RETEICA GENERAL")], extra_maestros=[("236831", "RETEICA")]) if RETEICA in str(e[4]).lower()]
    assert sin == [] and len(con) == 1
