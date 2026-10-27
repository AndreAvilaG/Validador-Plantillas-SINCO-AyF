"""Pruebas del reconocimiento de cuentas bancarias, números de cuenta y tarjetas en la validación del PUC (Etapa 1).

Qué se protege:
  * Una cuenta bancaria cuyo número viene con guiones (0540-9331-279) está bien identificada: no debe dar advertencia.
    Antes se exigían 6 dígitos SEGUIDOS y los guiones partían el número en grupos de 3 a 5 dígitos.
  * Una tarjeta (ej. débito) se identifica por sus últimos 4 dígitos (TARJETA DÉBITO BANCOLOMBIA 2251).
  * Lo que de verdad falta (sin banco, sin número, número demasiado corto) SIGUE marcándose.

Cómo correrlas (desde la raíz del repositorio):  pip install pytest   y luego   pytest pruebas
Los datos son inventados: no se deben agregar archivos de clientes a este repositorio.
"""
import os

import pytest

from _cargador import ejecutar

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CUENTAS_DE_LA_REVISION = [
    ("11100501", "Banco de Bogotá CTA: 03929-4194"),
    ("11100508", "Bancolombia CTA CTE: 0540-9331-279"),
    ("11100509", "Banco de Occidente: 223-00233-8"),
    ("11100510", "Banco Popular: 110-063-14406-7"),
    ("11200501", "Banco de Bogotá CTA AHORROS: 039-098-198"),
    ("11200523", "Banco de Occidente CTA AHORROS: 223-82345-1"),
    ("11201001", "Tarjeta débito Bancolombia: 2251"),
    ("11201002", "Tarjeta débito Bancolombia: 8963"),
]
MAESTROS = [("1", "ACTIVO"), ("11", "DISPONIBLE"), ("1110", "BANCOS"), ("111005", "BANCOS NACIONALES"),
            ("1120", "CUENTAS DE AHORRO"), ("112005", "AHORROS BANCOS"), ("112010", "TARJETAS DEBITO")]


def _validar(filas_aux, extra_maestros=()):
    """Corre validar_puc del validador real sobre un PUC mínimo con esas cuentas auxiliares [(código, descripción)]
    (y, si se pide, maestros adicionales). Las dependencias que le falten las agrega _cargador.ejecutar."""
    import pandas as pd

    def correr(ns):
        cols = ns["_COLS_PUC"]
        filas = [{**{c: "" for c in cols}, "Código": c, "Descripción": d, "Tipo": "M"} for c, d in list(MAESTROS) + list(extra_maestros)]
        filas += [{**{c: "" for c in cols}, "Código": c, "Descripción": d, "Tipo": "A"} for c, d in filas_aux]
        return ns["validar_puc"](pd.DataFrame(filas))

    return ejecutar(["validar_puc", "_COLS_PUC"], correr)


def _avisos_de_banco(descripcion, codigo="11100501"):
    return [e for e in _validar([(codigo, descripcion)]) if "banc" in str(e[4]).lower() and codigo in str(e[3])]


def _avisos_de_obligacion(descripcion, codigo="21051001"):      # una obligación financiera es una cuenta de PASIVO (clase 2)
    return [e for e in _validar([(codigo, descripcion)]) if "obligación financiera" in str(e[4]).lower() and codigo in str(e[3])]


# ───────────────────────── Lo que la revisión reportó como alerta falsa ─────────────────────────
@pytest.mark.parametrize("codigo,descripcion", CUENTAS_DE_LA_REVISION)
def test_las_cuentas_de_la_revision_ya_no_dan_advertencia(codigo, descripcion):
    """Regresión: estas ocho cuentas ya traían banco y número, y el validador decía que faltaba el número de cuenta."""
    assert _avisos_de_banco(descripcion, codigo) == []


def test_todas_las_cuentas_de_la_revision_juntas_no_dan_ninguna_advertencia_bancaria():
    avisos = [e for e in _validar(CUENTAS_DE_LA_REVISION) if "banc" in str(e[4]).lower()]
    assert avisos == []


# ───────────────────────── Números de cuenta con guiones ─────────────────────────
@pytest.mark.parametrize("descripcion", [
    "BANCOLOMBIA CTA CTE 123456789",                 # formato que ya se aceptaba
    "Banco de Bogotá 123456",                        # justo 6 dígitos seguidos
    "Banco de Bogotá CTA 12-34-56",                  # justo 6 dígitos en grupos
    "Bancolombia CTA CTE 0540 9331 279",             # grupos separados por espacios
    "Banco de Bogotá CTA 12 34 56",                  # justo 6 dígitos en grupos con espacios
    "Banco Popular 110\u00a0063\u00a014406\u00a07",   # espacios duros (los que mete Word o el correo)
    "Bancolombia CTA CTE 00012345",                  # ceros iniciales: son parte del número (8 dígitos)
    "Banco de Bogotá CTA 0000123456",                # ceros iniciales + número
    "Banco de Bogotá CTA 03929 - 4194",              # espacios alrededor del guion
    "Bancolombia CTA CTE 0540 - 9331 - 279",
    "Banco Popular 110 \u2013 063 \u2013 14406 \u2013 7",   # raya corta con espacios
    "Banco de Bogotá CTA 12\u201334\u201356",        # con raya corta (guion largo de Word)
    "Banco de Bogotá CTA 12\u201434\u201456",        # con raya larga
    "Banco Popular: 110-063-14406-7",
])
def test_numeros_de_cuenta_validos(descripcion):
    assert _avisos_de_banco(descripcion) == []


@pytest.mark.parametrize("descripcion", [
    "Bancolombia CTA CTE",                           # sin número
    "Banco de Bogotá CTA: 123-45",                   # solo 5 dígitos
    "Banco de Bogotá CTA: 12-34-5",                  # 5 dígitos en grupos
    "Banco de Bogotá CTA: 12345",                    # 5 dígitos seguidos
    "Banco de Bogotá CTA: 12 34 5",                  # 5 dígitos en grupos con espacios
    "Banco de Bogotá SUC 12 CTA 123",                # números separados por LETRAS no se unen: son dos números cortos
    "Banco Popular 0000",                            # ceros iniciales: 4 dígitos siguen siendo pocos
])
def test_un_numero_de_cuenta_incompleto_sigue_marcandose(descripcion):
    avisos = _avisos_de_banco(descripcion)
    assert len(avisos) == 1 and "el número de cuenta" in avisos[0][3], avisos


def test_una_cuenta_sin_nombre_de_banco_sigue_marcandose():
    avisos = _avisos_de_banco("Cuenta corriente 0540-9331-279")
    assert len(avisos) == 1 and "el nombre del banco" in avisos[0][3] and "el número de cuenta" not in avisos[0][3]


# ───────────────────────── Tarjetas: últimos 4 dígitos ─────────────────────────
@pytest.mark.parametrize("descripcion", [
    "Tarjeta débito Bancolombia: 2251",
    "Tarjeta débito Bancolombia 8963",
    "TARJETA DÉBITO BANCOLOMBIA ****2251",
    "Tarjeta débito Bancolombia 1234567890",         # un número largo también sirve
    "Tarjeta débito Bancolombia 22 51",              # últimos 4 dígitos en dos grupos
    "Tarjeta débito Bancolombia **** 0451",          # ceros iniciales en los últimos 4 dígitos
])
def test_tarjetas_con_banco_y_ultimos_digitos_no_dan_advertencia(descripcion):
    assert _avisos_de_banco(descripcion) == []


@pytest.mark.parametrize("descripcion,falta", [
    ("Tarjeta débito Bancolombia", "los últimos 4 dígitos de la tarjeta"),
    ("Tarjeta débito Bancolombia: 22", "los últimos 4 dígitos de la tarjeta"),
    ("Tarjeta débito Bancolombia: 123", "los últimos 4 dígitos de la tarjeta"),
])
def test_una_tarjeta_sin_sus_ultimos_digitos_sigue_marcandose(descripcion, falta):
    avisos = _avisos_de_banco(descripcion)
    assert len(avisos) == 1 and falta in avisos[0][3] and "el número de cuenta" not in avisos[0][3], avisos
    assert "TARJETA DÉBITO BANCOLOMBIA 2251" in avisos[0][3]          # el ejemplo es de tarjeta, no de cuenta corriente


def test_el_ejemplo_del_aviso_de_cuenta_corriente_no_cambia():
    avisos = _avisos_de_banco("Bancolombia CTA CTE")
    assert 'ej: "BANCOLOMBIA CTA CTE 123456789"' in avisos[0][3]


# ───────────────────────── Obligaciones financieras (comparten el mismo reconocimiento del número; cuentas de pasivo) ─────────────────────────
def test_una_obligacion_financiera_con_numero_con_guiones_no_da_advertencia():
    assert _avisos_de_obligacion("Leasing financiero Bancolombia OBL 456-789-12") == []


def test_una_obligacion_financiera_sin_numero_sigue_marcandose():
    avisos = _avisos_de_obligacion("Leasing financiero Bancolombia")
    assert len(avisos) == 1 and "el número de la obligación/crédito" in avisos[0][3]


# ───────────────────────── Cuentas de impuesto con la palabra BANCO (hallazgo en un PUC real) ─────────────────────────
@pytest.mark.parametrize("codigo,descripcion", [
    ("1355188056", "RETEICA EL BANCO - MAGDALENA"),            # El Banco es un municipio de Magdalena
    ("1355188057", "ReteICA El Banco – Magdalena"),
    ("23680101", "RETEFUENTE BANCO DE LA REPUBLICA"),          # retención: no es una cuenta de banco
])
def test_una_cuenta_de_impuesto_con_la_palabra_banco_no_es_una_cuenta_bancaria(codigo, descripcion):
    """Regresión: «RETEICA EL BANCO - MAGDALENA» (1355188056) daba el aviso de cuenta bancaria sin número."""
    assert _avisos_de_banco(descripcion, codigo) == []


def test_una_cuenta_bancaria_de_verdad_con_la_misma_palabra_sigue_marcandose():
    avisos = _avisos_de_banco("EL BANCO CTA CTE")                # sin tipo de impuesto: sí es una cuenta de banco incompleta
    assert len(avisos) == 1 and "el número de cuenta" in avisos[0][3]
