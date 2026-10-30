"""Pruebas de los ajustes del PUC (Etapa 1) pedidos tras revisar plantillas reales de clientes.

Qué se protege (cada punto con su caso real y con un caso de control que SIGUE avisando):
  1. Tarifas de retención duplicadas: las cuentas de DEVOLUCIÓN («Devolución retención… 2,5%») no se marcan ni cuentan como «ya existente», pero dos cuentas
     de retención normales con la misma tarifa y concepto siguen marcándose.
  2. Cuentas con tarifa sin perfil de impuesto: los impuestos se reconocen por CÓDIGO (grupo 24, 2365/2367/2368, 1355) y por palabras como «Descontable» (el
     caso «24081501 Descontable por servicios 19%»); un gasto cualquiera con tarifa sigue avisando.
  3. Naturaleza Contraria = S: una cuenta de devolución («Devolución en ventas en la retención…») es contraria y no se avisa; una de ventas normal sí.
  5. Retención «por pagar» (Retefuente / ReteIVA / ReteICA por pagar): son cuentas de pago, no se les exige base ni %; si la descripción trae un porcentaje o no
     dice «por pagar», se siguen validando.
  6. Una retención con % en cero da una observación (la tarifa debe ser válida); el IVA al 0% y las cuentas «por pagar» no.
  9. Una cuenta de nivel CLASE (1 dígito) o GRUPO (2 dígitos) marcada como auxiliar es un error: SINCO la rechaza («El nivel de la cuenta no está definido de forma
     correcta»). Caso real: la clase «9 CUENTAS DE ORDEN ACREEDORAS» como A, sin cuentas hijas, mientras las clases 1 a 8 eran M.
  10. Orden y niveles: una cuenta que aparece ANTES que su maestra es un error (la migración va desde la clase hasta las auxiliares y la maestra va primero); una cuenta
     a la que le falta un nivel intermedio entre ella y su maestra es una recomendación, y solo cuando se aparta de la convención del propio plan (un plan 6+3 no es un error).
  8. Tercero y Centro de Costo: obligatorios (error) en cuentas por cobrar y por pagar, recomendados (observación) en el resto de auxiliares; no se piden en bancos,
     inversiones, impuestos como cuentas por cobrar/pagar, ni en cuentas marcadas como inactivas.

Cómo correrlas (desde la raíz del repositorio):  pip install pytest   y luego   pytest pruebas
Los datos son inventados: no se deben agregar archivos de clientes a este repositorio.
"""
import pytest

from _cargador import ejecutar

DUPLICADA = "Tarifa de retención duplicada"
SIN_PERFIL = "Cuenta sin perfil de impuesto pero con tarifa diligenciada"
INCOMPLETA = "Cuenta de impuesto/retención con parámetros incompletos"
NAT_S = "Naturaleza Contraria = S en cuentas que normalmente no la requieren"
CERO = "Retención con tarifa en cero"
CXC_CXP = "Cuenta por cobrar/pagar sin tercero o centro de costo"
NIVEL = "Auxiliar en nivel de clase o grupo"
ANTES = "Cuenta antes de su maestra"
SALTA = "Cuenta que salta un nivel"
LONGITUD = "Longitud de auxiliar distinta al estándar."
AUX_SIN = "Cuenta auxiliar sin tercero o centro de costo"
BASE = dict(cc="S", ter="S", rb="", pct="", bm="", nat="N")


def _puc(auxiliares, maestros=None):
    """Corre validar_puc sobre un PUC mínimo. auxiliares: [(código, descripción, {columnas a cambiar})]; los maestros se generan solos con una descripción neutra
    (se puede dar una distinta con maestros={código: descripción}). Devuelve (lista de errores, {código de auxiliar: fila de Excel})."""
    import pandas as pd
    maestros = maestros or {}

    def correr(ns):
        cols = ns["_COLS_PUC"]
        vacio = {c: "" for c in cols}
        padres = sorted({c[:n] for c, _, _ in auxiliares for n in (1, 2, 4, 6, 8) if n < len(c)}, key=lambda x: (len(x), x))
        filas = [{**vacio, "Código": m, "Descripción": maestros.get(m, f"GRUPO {m}"), "Tipo": "M"} for m in padres]
        posicion = {}
        for codigo, desc, extra in auxiliares:
            v = {**BASE, **extra}
            posicion[codigo] = len(filas) + 2
            filas.append({**vacio, "Código": codigo, "Descripción": desc, "Tipo": "A", "Requiere Centro Costo": v["cc"], "Requiere Tercero": v["ter"],
                          "Requiere Base": v["rb"], "%": v["pct"], "Base Mínima": v["bm"], "Naturaleza Contraria": v["nat"], "Plazo": "0"})
        return ns["validar_puc"](pd.DataFrame(filas)), posicion
    return ejecutar(["validar_puc", "_COLS_PUC"], correr)


def _de(errores, clave, fila=None):
    return [e for e in errores if e[4] == clave and (fila is None or e[0] == fila)]


RET = dict(rb="S", pct="2.5", bm="1")
MAESTRO_RETEFUENTE = {"135515": "RETENCION EN LA FUENTE", "236540": "RETENCION EN LA FUENTE", "236505": "RETENCION EN LA FUENTE"}


# ───────────────────────── 1. Tarifas duplicadas y devoluciones ─────────────────────────
@pytest.mark.parametrize("devolucion", ["Devolución retención en la fuente compras 2,5%", "Devolucion retencion compras 2.5%", "Dev. retención compras 2,5%",
                                         "DEVOL RETENCION COMPRAS 2.5%", "Devoluciones retención compras 2,5%", "Retención compras 2,5% devuelta"])
def test_una_cuenta_de_devolucion_no_se_marca_como_tarifa_duplicada(devolucion):
    """Caso real: 13551502 «Devolución retención en la fuente compras 2,5%» se marcaba como duplicada de 13551501 «Anticipo retención… compras 2,5%»."""
    errores, filas = _puc([("13551501", "Anticipo retención en la fuente compras 2,5%", RET), ("13551502", devolucion, RET)], MAESTRO_RETEFUENTE)
    assert not _de(errores, DUPLICADA, filas["13551502"]) and _de(errores, DUPLICADA) == []


def test_el_caso_real_de_las_dos_cuentas_ya_no_da_duplicada():
    errores, _ = _puc([("13551501", "Anticipo retención en la fuente compras 2,5%", RET), ("13551502", "Devolución retención en la fuente compras 2,5%", RET)], MAESTRO_RETEFUENTE)
    assert _de(errores, DUPLICADA) == []


def test_dos_cuentas_de_retencion_normales_con_la_misma_tarifa_y_concepto_siguen_marcandose():
    """Control: la regla no se apagó: «Retención compras 2,5%» repetida SÍ es duplicada."""
    errores, filas = _puc([("13551501", "Anticipo retención en la fuente compras 2,5%", RET), ("13551503", "Retención en la fuente compras 2,5%", RET)], MAESTRO_RETEFUENTE)
    assert [e[0] for e in _de(errores, DUPLICADA)] == [filas["13551503"]]


def test_una_devolucion_tampoco_cuenta_como_la_cuenta_ya_existente_de_otra():
    """La devolución se ignora por completo: no hace que otra cuenta normal quede como «duplicada de la devolución»."""
    errores, _ = _puc([("13551502", "Devolución retención en la fuente compras 2,5%", RET), ("13551503", "Retención en la fuente compras 2,5%", RET)], MAESTRO_RETEFUENTE)
    assert _de(errores, DUPLICADA) == []


def test_dev_como_parte_de_otra_palabra_no_es_una_devolucion():
    errores, filas = _puc([("13551501", "Anticipo retención en la fuente desarrollo 2,5%", RET), ("13551503", "Retención en la fuente desarrollo 2,5%", RET)], MAESTRO_RETEFUENTE)
    assert [e[0] for e in _de(errores, DUPLICADA)] == [filas["13551503"]]


# ───────────────────────── 3. Naturaleza Contraria en devoluciones ─────────────────────────
def test_una_devolucion_con_naturaleza_contraria_s_no_se_avisa():
    """Caso real: 13551510 «Devolución en ventas en la retención por honorarios 11%» (la palabra «ventas» hacía que se avisara)."""
    errores, _ = _puc([("13551510", "Devolución en ventas en la retención por honorarios 11%", {**RET, "pct": "11", "nat": "S"})], MAESTRO_RETEFUENTE)
    assert _de(errores, NAT_S) == []


@pytest.mark.parametrize("descripcion", ["VENTAS DE MERCANCIAS", "Ventas de servicios", "Ingresos por venta de productos"])
def test_una_cuenta_de_ventas_normal_con_s_sigue_avisando(descripcion):
    errores, filas = _puc([("41350501", descripcion, {"nat": "S"})])
    assert len(_de(errores, NAT_S, filas["41350501"])) == 1


def test_devoluciones_en_ventas_de_ingresos_tampoco_se_avisan():
    errores, _ = _puc([("41750501", "Devoluciones en ventas", {"nat": "S"}), ("41750502", "Dev. ventas de servicios", {"nat": "S"})])
    assert _de(errores, NAT_S) == []


# ───────────────────────── 2. Impuestos reconocidos por código y por palabras ─────────────────────────
def test_el_caso_real_descontable_por_servicios_ya_no_se_marca_sin_perfil():
    """Caso real: 24081501 «Descontable por servicios 19%» tiene base mínima y % diligenciados: es un IVA descontable y eso es correcto."""
    errores, _ = _puc([("24081501", "Descontable por servicios 19%", {"rb": "S", "pct": "19", "bm": "1"})])
    assert _de(errores, SIN_PERFIL) == []


@pytest.mark.parametrize("codigo,descripcion", [("24081501", "Servicios 19%"), ("24081502", "Compras 5%"), ("24041001", "Impuesto de renta 35%"), ("24120501", "Bogotá 0,966%"),
                                                 ("23653501", "Honorarios 11%"), ("23670101", "Servicios 15%"), ("23680101", "Bogotá 0,966%"), ("13551501", "Honorarios 11%")])
def test_las_cuentas_de_los_grupos_de_impuestos_no_se_marcan_sin_perfil_aunque_la_descripcion_no_lo_diga(codigo, descripcion):
    errores, _ = _puc([(codigo, descripcion, {"rb": "S", "pct": "5", "bm": "1"})])
    assert _de(errores, SIN_PERFIL) == []


@pytest.mark.parametrize("descripcion", ["Descontable por compras 19%", "Impoconsumo 8%", "Sobretasa bomberil 3%", "Avisos y tableros 15%", "Predial unificado 1%"])
def test_palabras_de_impuestos_reconocidas_en_cualquier_cuenta(descripcion):
    errores, _ = _puc([("51359501", descripcion, {"rb": "S", "pct": "5", "bm": "1"})])
    assert _de(errores, SIN_PERFIL) == []


@pytest.mark.parametrize("descripcion", ["Servicios técnicos 19%", "Honorarios profesionales", "Arrendamientos 4%"])
def test_una_cuenta_que_no_es_de_impuesto_con_tarifa_sigue_marcandose_sin_perfil(descripcion):
    """Control: un gasto cualquiera con tarifa (y fuera de los grupos de impuestos) SÍ debe avisar."""
    errores, filas = _puc([("51359501", descripcion, {"rb": "S", "pct": "5", "bm": "1"})])
    assert len(_de(errores, SIN_PERFIL, filas["51359501"])) == 1


def test_un_iva_descontable_reconocido_sin_la_palabra_iva_sigue_exigiendo_sus_parametros():
    """Cuándo modificar: «Descontable por servicios» SIN tarifa ni base se reconoce como IVA descontable y se avisa lo que falta."""
    errores, filas = _puc([("24081501", "Descontable por servicios", {})])
    avisos = _de(errores, INCOMPLETA, filas["24081501"])
    assert len(avisos) == 1 and "IVA descontable" in avisos[0][3] and "% (tarifa)" in avisos[0][3]


def test_iva_no_descontable_no_se_toma_como_iva_descontable():
    errores, filas = _puc([("51359501", "IVA no descontable 19%", {"rb": "S", "pct": "19", "bm": "1"}), ("51359502", "IVA NO DESCONTABLE servicios", {})])
    assert _de(errores, INCOMPLETA) == []


# ───────────────────────── 5. Retención «por pagar» ─────────────────────────
@pytest.mark.parametrize("descripcion", ["RETEFUENTE POR PAGAR", "Retefuente x pagar", "RETE IVA POR PAGAR", "RETEIVA A PAGAR", "RETE ICA POR PAGAR", "Reteica por pagar", "Retención en la fuente por pagar",
                                         "PAGO RETEFUENTE"])
def test_las_cuentas_de_retencion_por_pagar_o_de_pago_no_piden_base_ni_porcentaje(descripcion):
    """Pedido de Andrea: estas cuentas se usan para pagar, no para calcular."""
    errores, _ = _puc([("23659501", descripcion, {})])
    assert _de(errores, INCOMPLETA) == []


@pytest.mark.parametrize("descripcion", ["RETEFUENTE POR PAGAR HONORARIOS 11%", "Retefuente x pagar servicios 4%", "RETEFUENTE HONORARIOS", "RETEICA BOGOTA", "RETEIVA SERVICIOS", "Retefuente por cobrar"])
def test_una_retencion_que_calcula_sigue_exigiendo_base_y_porcentaje(descripcion):
    """Control: con porcentaje en la descripción, o sin decir «por pagar», la cuenta calcula y se sigue validando."""
    errores, filas = _puc([("23659501", descripcion, {})])
    assert len(_de(errores, INCOMPLETA, filas["23659501"])) == 1


# ───────────────────────── 6. Retención con tarifa en cero ─────────────────────────
@pytest.mark.parametrize("descripcion", ["RETEFUENTE HONORARIOS", "Retención en la fuente servicios", "RETEICA BOGOTA", "Reteica Medellín", "RETEIVA SERVICIOS", "Retención de IVA"])
@pytest.mark.parametrize("cero", ["0", "0.0", "0,0", 0, 0.0])
def test_una_retencion_con_porcentaje_cero_da_una_observacion(descripcion, cero):
    errores, filas = _puc([("23659501", descripcion, {"rb": "S", "pct": cero, "bm": "1"})])
    avisos = _de(errores, CERO, filas["23659501"])
    assert len(avisos) == 1 and avisos[0][1] == "%" and avisos[0][2] == "advertencia"
    assert "porcentaje válido (mayor que cero)" in avisos[0][3] and "Verifica con el cliente la tarifa que corresponde" in avisos[0][3]


@pytest.mark.parametrize("pct", ["11", "0.5", "0,966", "4"])
def test_una_retencion_con_tarifa_valida_no_da_observacion_de_cero(pct):
    errores, _ = _puc([("23659501", "RETEFUENTE HONORARIOS", {"rb": "S", "pct": pct, "bm": "1"})])
    assert _de(errores, CERO) == []


@pytest.mark.parametrize("codigo,descripcion", [("24081501", "IVA descontable 0%"), ("24081502", "IVA generado excluido"), ("51359501", "Servicios técnicos"), ("23659501", "RETEFUENTE POR PAGAR")])
def test_el_iva_en_cero_y_las_cuentas_por_pagar_no_dan_la_observacion(codigo, descripcion):
    """El IVA al 0% es válido (bienes exentos o excluidos) y las cuentas «por pagar» no llevan tarifa."""
    errores, _ = _puc([(codigo, descripcion, {"rb": "S", "pct": "0", "bm": "1"})])
    assert _de(errores, CERO) == []


def test_sin_porcentaje_no_da_la_observacion_de_cero():
    errores, _ = _puc([("23659501", "RETEFUENTE HONORARIOS", {"rb": "S", "pct": "", "bm": "1"})])
    assert _de(errores, CERO) == []


# ───────────────────────── 8. Tercero y Centro de Costo ─────────────────────────
@pytest.mark.parametrize("codigo,descripcion", [("13050501", "CLIENTES NACIONALES"), ("13251001", "CUENTAS POR COBRAR A SOCIOS"), ("13301001", "ANTICIPOS A PROVEEDORES"), ("13651001", "CUENTAS POR COBRAR A TRABAJADORES"),
                                                 ("22050101", "PROVEEDORES NACIONALES"), ("23352501", "COSTOS Y GASTOS POR PAGAR"), ("23801001", "ACREEDORES VARIOS"),
                                                 ("28050501", "ANTICIPOS DE CLIENTES")])
@pytest.mark.parametrize("columnas,pide", [({"ter": "N"}, "Tercero"), ({"cc": "N"}, "Centro de Costo"), ({"ter": "N", "cc": "N"}, "Centro de Costo ni Tercero"), ({"ter": ""}, "Tercero")])
def test_una_cuenta_por_cobrar_o_por_pagar_sin_tercero_o_centro_de_costo_es_error(codigo, descripcion, columnas, pide):
    errores, filas = _puc([(codigo, descripcion, columnas)])
    avisos = _de(errores, CXC_CXP, filas[codigo])
    assert len(avisos) == 1 and avisos[0][2] == "logica" and f"no requiere {pide}" in avisos[0][3] and "obligatorios" in avisos[0][3]
    assert not _de(errores, AUX_SIN, filas[codigo])                                     # y no se duplica con la recomendación


def test_el_error_nombra_las_columnas_que_hay_que_marcar_para_que_el_excel_las_pinte():
    errores, filas = _puc([("13050501", "CLIENTES", {"ter": "N", "cc": "N"}), ("13050502", "CLIENTES EXTERIOR", {"ter": "N"})])
    assert _de(errores, CXC_CXP, filas["13050501"])[0][1] == "Requiere Centro Costo / Requiere Tercero"
    assert _de(errores, CXC_CXP, filas["13050502"])[0][1] == "Requiere Tercero"


@pytest.mark.parametrize("codigo,descripcion", [("13050501", "CLIENTES NACIONALES"), ("22050101", "PROVEEDORES"), ("51050601", "SALARIOS"), ("11100501", "BANCO"), ("12010501", "ACCIONES")])
def test_con_tercero_y_centro_de_costo_en_s_no_hay_ningun_aviso(codigo, descripcion):
    errores, _ = _puc([(codigo, descripcion, {})])
    assert not _de(errores, CXC_CXP) and not _de(errores, AUX_SIN)


@pytest.mark.parametrize("codigo,descripcion", [("51050601", "SALARIOS"), ("15040501", "TERRENOS"), ("41350501", "VENTAS DE MERCANCIAS"), ("24081501", "IVA GENERADO"), ("23654001", "RETENCION HONORARIOS"),
                                                 ("25050101", "SALARIOS POR PAGAR"), ("13550501", "ANTICIPO DE RENTA"), ("13999501", "DETERIORO DEUDORES")])
def test_las_demas_auxiliares_sin_tercero_o_centro_de_costo_solo_reciben_una_recomendacion(codigo, descripcion):
    """Gasto, activos fijos, ingresos, impuestos, retenciones por pagar, obligaciones laborales y deterioro: se recomienda, no se bloquea."""
    errores, filas = _puc([(codigo, descripcion, {"ter": "N"})])
    avisos = _de(errores, AUX_SIN, filas[codigo])
    assert len(avisos) == 1 and avisos[0][2] == "advertencia" and "Se recomienda que las cuentas auxiliares requieran Centro de Costo y Tercero" in avisos[0][3]
    assert not _de(errores, CXC_CXP)


@pytest.mark.parametrize("codigo,descripcion", [("11100501", "BANCO DE BOGOTA"), ("11050501", "CAJA GENERAL"), ("12010501", "ACCIONES"), ("13050599", "INACTIVA. CLIENTES"), ("13750510", "INACTIVA. CUENTAS POR COBRAR CORRECCIONES"),
                                                 ("51050699", "Inactivo salarios")])
def test_bancos_inversiones_y_cuentas_inactivas_no_reciben_aviso_de_tercero_ni_centro_de_costo(codigo, descripcion):
    errores, _ = _puc([(codigo, descripcion, {"ter": "N", "cc": "N"})])
    assert not _de(errores, CXC_CXP) and not _de(errores, AUX_SIN)


def test_los_maestros_no_reciben_aviso_de_tercero_ni_centro_de_costo():
    """Solo las cuentas auxiliares (Tipo A): un maestro sin S no se avisa."""
    errores, _ = _puc([("13050501", "CLIENTES", {})])
    assert not _de(errores, CXC_CXP) and not _de(errores, AUX_SIN)


def test_el_mensaje_de_tercero_y_centro_de_costo_es_igual_para_todas_las_filas_del_mismo_caso():
    """Para que el reporte las junte en una sola tarjeta y no repita el texto por cada cuenta."""
    errores, _ = _puc([("51050601", "SALARIOS", {"ter": "N"}), ("51050602", "HONORARIOS", {"ter": "N"}), ("51050603", "SERVICIOS", {"ter": "N"})])
    assert len({e[3] for e in _de(errores, AUX_SIN)}) == 1 and len(_de(errores, AUX_SIN)) == 3


def test_las_fichas_del_reporte_de_las_reglas_nuevas_existen():
    from _cargador import cargar
    ns, *_ = cargar(["FRASES_AMIGABLES"])
    for clave in (CERO, CXC_CXP, AUX_SIN, NIVEL, ANTES, SALTA, "Campo obligatorio en cero.", "Teléfono negativo."):
        assert set(ns["FRASES_AMIGABLES"][clave]) >= {"titulo", "ocurre", "accion"}, clave


# ───────────────────────── 9. Auxiliar en nivel de clase o grupo ─────────────────────────
def test_el_caso_real_la_clase_9_marcada_como_auxiliar_es_error():
    """SINCO: «El nivel de la cuenta no está definido de forma correcta» con la cuenta 9. La app solo daba una recomendación de dígitos y el archivo llegaba a «lista para migrar»."""
    errores, filas = _puc([("13050501", "CLIENTES", {}), ("9", "CUENTAS DE ORDEN ACREEDORAS", {})])
    (fila, columna, tipo, mensaje, clave), = _de(errores, NIVEL)
    assert (fila, columna, tipo) == (filas["9"], "Tipo", "logica")
    assert 'La cuenta "9" (CUENTAS DE ORDEN ACREEDORAS) es de nivel Clase (1 dígito) y no puede ser auxiliar' in mensaje
    assert "deben ser Maestras (M)" in mensaje and "elimínala del PUC" in mensaje


def test_un_grupo_de_dos_digitos_marcado_como_auxiliar_tambien_es_error():
    errores, filas = _puc([("13050501", "CLIENTES", {}), ("91", "ACREEDORAS DE CONTROL", {})])
    (fila, _, _, mensaje, _), = _de(errores, NIVEL)
    assert fila == filas["91"] and "nivel Grupo (2 dígitos)" in mensaje


def test_clase_y_grupo_en_el_mismo_archivo_dan_un_error_cada_uno():
    errores, filas = _puc([("13050501", "CLIENTES", {}), ("9", "CLASE", {}), ("91", "GRUPO", {})])
    assert sorted(e[0] for e in _de(errores, NIVEL)) == sorted([filas["9"], filas["91"]])


@pytest.mark.parametrize("codigo", ["1105", "110505", "11050501", "1105050101", "110505010101"])
def test_una_auxiliar_de_cuatro_o_mas_digitos_no_da_este_error(codigo):
    """Solo clase y grupo están probados como inválidos para una auxiliar: el resto sigue como antes (con su recomendación de uniformidad si corresponde)."""
    errores, _ = _puc([("13050501", "CLIENTES", {}), (codigo, "AUXILIAR", {})])
    assert _de(errores, NIVEL) == []


def test_la_clase_9_como_maestra_no_da_este_error_solo_su_recomendacion_de_sin_hijas():
    import pandas as pd

    def correr(ns):
        vacio = {c: "" for c in ns["_COLS_PUC"]}
        filas = [{**vacio, "Código": c, "Descripción": d, "Tipo": "M"} for c, d in (("1", "ACTIVO"), ("13", "DEUDORES"), ("1305", "CLIENTES"), ("130505", "NACIONALES"), ("9", "CUENTAS DE ORDEN ACREEDORAS"))]
        filas.append({**vacio, "Código": "13050501", "Descripción": "CLIENTES NACIONALES", "Tipo": "A", "Requiere Centro Costo": "S", "Requiere Tercero": "S"})
        return ns["validar_puc"](pd.DataFrame(filas))
    errores = ejecutar(["validar_puc", "_COLS_PUC"], correr)
    assert _de(errores, NIVEL) == [] and [e for e in errores if e[4] == "Maestro sin cuentas hijas" and 'maestra "9"' in e[3]]


def test_la_clase_marcada_como_auxiliar_no_repite_la_recomendacion_de_digitos():
    """Ya tiene su error; la recomendación «tiene 1 dígitos pero la mayoría tiene 8» sería ruido. Una auxiliar de 10 dígitos entre auxiliares de 8 SÍ la sigue teniendo."""
    errores, filas = _puc([("13050501", "A", {}), ("13050502", "B", {}), ("13050503", "C", {}), ("9", "CLASE", {}), ("1305050101", "DE 10 DIGITOS", {})])
    largos = _de(errores, LONGITUD)
    assert [e[0] for e in largos] == [filas["1305050101"]]
    assert len(_de(errores, NIVEL)) == 1


def test_una_clase_maestra_con_sus_hijas_es_lo_normal_y_no_da_ningun_aviso_de_nivel():
    import pandas as pd

    def correr(ns):
        vacio = {c: "" for c in ns["_COLS_PUC"]}
        filas = [{**vacio, "Código": c, "Descripción": d, "Tipo": "M"} for c, d in (("9", "ORDEN ACREEDORAS"), ("93", "ACREEDORAS DE CONTROL"), ("9305", "BIENES RECIBIDOS"), ("930505", "EN CUSTODIA"))]
        filas.append({**vacio, "Código": "93050501", "Descripción": "CUSTODIA GENERAL", "Tipo": "A", "Requiere Centro Costo": "S", "Requiere Tercero": "S"})
        return ns["validar_puc"](pd.DataFrame(filas))
    assert _de(ejecutar(["validar_puc", "_COLS_PUC"], correr), NIVEL) == []


# ───────────────────────── 10. Orden de las filas y niveles de la jerarquía ─────────────────────────
def _puc_en_orden(cuentas):
    """Corre validar_puc con las cuentas EXACTAMENTE en el orden dado: [(código, descripción, tipo M/A)]. Devuelve (errores, {código: fila de Excel})."""
    import pandas as pd

    def correr(ns):
        vacio = {c: "" for c in ns["_COLS_PUC"]}
        filas = [{**vacio, "Código": c, "Descripción": d, "Tipo": tp, "Requiere Centro Costo": "S", "Requiere Tercero": "S", "Naturaleza Contraria": "N", "Plazo": "0"} for c, d, tp in cuentas]
        return ns["validar_puc"](pd.DataFrame(filas)), {c: i + 2 for i, (c, _, _) in enumerate(cuentas)}
    return ejecutar(["validar_puc", "_COLS_PUC"], correr)


CADENA = [("1", "ACTIVO", "M"), ("11", "DISPONIBLE", "M"), ("1105", "CAJA", "M"), ("110505", "CAJA GENERAL", "M"), ("11050505", "GENERAL", "A")]


def test_un_puc_en_orden_no_da_error_de_orden_ni_de_salto():
    errores, _ = _puc_en_orden(CADENA)
    assert _de(errores, ANTES) == [] and _de(errores, SALTA) == []


def test_una_hija_antes_que_su_maestra_es_error_en_la_fila_de_la_hija():
    """La auxiliar 11050505 está en una fila anterior a la de su maestra 110505."""
    errores, filas = _puc_en_orden([CADENA[0], CADENA[1], CADENA[2], CADENA[4], CADENA[3]])
    (fila, columna, tipo, mensaje, _), = _de(errores, ANTES)
    assert (fila, columna, tipo) == (5, "Código", "logica")
    assert 'La cuenta "11050505" (GENERAL) está en la fila 5, antes que su maestra "110505" (CAJA GENERAL, fila 6)' in mensaje
    assert "la maestra debe ir antes de sus cuentas hijas" in mensaje and "Ordena la hoja por la columna Código" in mensaje


def test_varias_hijas_antes_de_su_maestra_dan_un_error_cada_una():
    errores, _ = _puc_en_orden([CADENA[0], CADENA[1], CADENA[2], ("11050505", "A", "A"), ("11050506", "B", "A"), ("11050507", "C", "A"), CADENA[3]])
    assert sorted(e[0] for e in _de(errores, ANTES)) == [5, 6, 7]


def test_una_maestra_antes_de_su_propia_maestra_tambien_es_error():
    errores, _ = _puc_en_orden([("1", "ACTIVO", "M"), ("1105", "CAJA", "M"), ("11", "DISPONIBLE", "M"), ("110505", "CAJA GENERAL", "M"), ("11050505", "GENERAL", "A")])
    assert [e[0] for e in _de(errores, ANTES)] == [3]


def test_un_puc_ordenado_al_reves_marca_todas_las_cuentas_que_tienen_maestra():
    errores, _ = _puc_en_orden(list(reversed(CADENA)))
    assert len(_de(errores, ANTES)) == len(CADENA) - 1                        # todas menos la clase, que no tiene maestra


def test_una_cuenta_sin_ninguna_maestra_solo_da_el_error_de_hueco_y_no_el_de_orden():
    errores, _ = _puc_en_orden([("13050501", "CLIENTES", "A")])
    assert _de(errores, ANTES) == [] and len(_de(errores, "Cuenta sin maestro padre (hueco en el árbol)")) == 1


PLAN_ESTANDAR = [("1", "ACTIVO", "M"), ("11", "DISPONIBLE", "M"), ("1105", "CAJA", "M"), ("110505", "CAJA GENERAL", "M"), ("110510", "CAJA MENOR", "M"), ("11050505", "GENERAL", "A"),
                 ("11051001", "OFICINA", "A"), ("2", "PASIVO", "M"), ("21", "OBLIGACIONES", "M")]


def test_una_cuenta_que_salta_un_nivel_en_un_plan_estandar_da_una_recomendacion():
    """11059901 (8 dígitos) cuelga de 1105 (4 dígitos): falta el nivel de 6, y el resto del plan sí lo usa."""
    errores, filas = _puc_en_orden(PLAN_ESTANDAR + [("11059901", "SALTA UN NIVEL", "A")])
    (fila, columna, tipo, mensaje, _), = _de(errores, SALTA)
    assert (fila, columna, tipo) == (filas["11059901"], "Código", "advertencia")
    assert "tiene 8 dígitos, pero su maestra más cercana tiene 4: falta el nivel intermedio de 6 dígitos" in mensaje and "verifica si es intencional" in mensaje


BASE_NIVELES = [("1", "ACTIVO", "M"), ("11", "D", "M"), ("1105", "C", "M"), ("110505", "G", "M"), ("110510", "H", "M"), ("11050505", "A", "M"), ("11051001", "I", "M"),
                ("1105050501", "B", "M"), ("110505050101", "AUX", "A"), ("1105100101", "J", "M"), ("110510010101", "K", "A"), ("1120", "OTRA", "M")]


@pytest.mark.parametrize("rama,hija,que_falta", [([("11209901", "X", "A")], "11209901", "de 6 dígitos"),
                                                  ([("112005", "M", "M"), ("1120059901", "X", "A")], "1120059901", "de 8 dígitos"),
                                                  ([("112005", "M", "M"), ("11200501", "M", "M"), ("112005010101", "X", "A")], "112005010101", "de 10 dígitos")])
def test_cada_salto_de_nivel_se_avisa_con_los_digitos_que_faltan(rama, hija, que_falta):
    """8 bajo una maestra de 4, 10 bajo una de 6 y 12 bajo una de 8: el resto del plan sí usa los niveles intermedios."""
    errores, filas = _puc_en_orden(BASE_NIVELES + rama)
    (fila, _, _, mensaje, _), = _de(errores, SALTA)
    assert fila == filas[hija] and f"falta el nivel intermedio {que_falta}" in mensaje


def test_el_plan_base_de_niveles_no_da_ningun_aviso_de_salto():
    assert _de(_puc_en_orden(BASE_NIVELES)[0], SALTA) == []


def test_una_clase_con_una_hija_de_cuatro_digitos_salta_el_nivel_de_grupo():
    errores, filas = _puc_en_orden(PLAN_ESTANDAR + [("1205", "SALTA EL GRUPO", "M"), ("120505", "X", "M"), ("12050501", "Y", "A")])
    assert [e[0] for e in _de(errores, SALTA)] == [filas["1205"]] and "falta el nivel intermedio de 2 dígitos" in _de(errores, SALTA)[0][3]


def test_un_plan_con_convencion_propia_6_mas_3_no_da_ninguna_recomendacion_de_salto():
    """Caso real: un PUC con 394 auxiliares de 9 dígitos colgando de maestras de 6. Es la convención de ese plan, no un error: no se avisa cuenta por cuenta."""
    cuentas = [("1", "ACTIVO", "M"), ("11", "DISPONIBLE", "M"), ("1105", "CAJA", "M"), ("110505", "CAJA GENERAL", "M")] + [(f"11050500{i}", f"AUX {i}", "A") for i in range(1, 8)]
    errores, _ = _puc_en_orden(cuentas)
    assert _de(errores, SALTA) == [] and _de(errores, ANTES) == []


def test_en_un_plan_6_mas_3_una_auxiliar_que_si_se_aparta_de_la_convencion_se_avisa():
    cuentas = [("1", "ACTIVO", "M"), ("11", "DISPONIBLE", "M"), ("1105", "CAJA", "M"), ("110505", "CAJA GENERAL", "M")] + [(f"11050500{i}", f"AUX {i}", "A") for i in range(1, 8)]
    errores, filas = _puc_en_orden(cuentas + [("1105050501234", "DE 13 DIGITOS", "A")])
    assert [e[0] for e in _de(errores, SALTA)] == [filas["1105050501234"]]


def test_el_salto_de_nivel_es_recomendacion_y_el_orden_es_error():
    errores, _ = _puc_en_orden([CADENA[0], CADENA[1], CADENA[2], CADENA[4], CADENA[3]])
    assert {e[2] for e in _de(errores, ANTES)} == {"logica"}
    errores, _ = _puc_en_orden(PLAN_ESTANDAR + [("11059901", "SALTA", "A")])
    assert {e[2] for e in _de(errores, SALTA)} == {"advertencia"}


def test_dos_cuentas_que_saltan_el_mismo_nivel_tienen_el_mismo_mensaje_para_agruparse_en_el_reporte():
    errores, _ = _puc_en_orden(PLAN_ESTANDAR + [("11059901", "A", "A"), ("11059902", "B", "A")])
    assert len(_de(errores, SALTA)) == 2 and len({e[3] for e in _de(errores, SALTA)}) == 1
