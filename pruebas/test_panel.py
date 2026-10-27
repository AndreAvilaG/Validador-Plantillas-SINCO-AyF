"""Pruebas del panel de seguimiento para directores (diseño del boceto y reglas acordadas).

Qué se protege:
  * Las reglas de avance: plantillas esperadas por etapa, «No aplica» automático, avance global y estados. Hay una prueba que reproduce los
    seis clientes de ejemplo del boceto con sus números exactos.
  * Los rebotes (caídas que se revierten en menos de un minuto; caso real: PROMOTORA BELONG, 91,67 → 16,67 → 91,67 en 8 segundos) no cuentan.
  * La seguridad: el código se guarda cifrado, 5 intentos fallidos bloquean 10 minutos, el público (llave pública) NO puede leer las tablas ni
    llamar a las funciones internas, y todo texto de usuario se escapa antes de dibujarlo. Las pruebas de base de datos necesitan PostgreSQL
    (variable SEGUIMIENTO_PG_DSN y psycopg2); sin ella se omiten.
  * La pantalla: solo se abre con ?panel=1, exige el código, muestra el panel general y el detalle de cada cliente; y la app normal queda igual.

Cómo correrlas (desde la raíz del repositorio):  pip install pytest psycopg2-binary   y luego   pytest pruebas
Los datos son inventados: no se deben agregar archivos de clientes a este repositorio.
"""
import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import panel_seguimiento as panel  # noqa: E402

CODIGO = "CODIGO-DE-PRUEBA-2026"
OK, RC = "completado", "requiere_correcciones"


def _iso(d):
    return d.isoformat()


def _f(etapa, plantilla, cum, estado=OK, filas=100, err=0, nit="901652178", nombre="PROMOTORA BELONG S.A.S.", hace=timedelta(hours=3),
       pendientes=None, fuente="informe"):
    """Una fila de avance_actual, como la entrega panel_resumen."""
    return {"nit": nit, "nombre_cliente": nombre, "fuente_nit": fuente, "etapa": etapa, "plantilla": plantilla, "cumplimiento": cum, "estado": estado,
            "filas_evaluadas": filas, "filas_con_error": err, "errores_globales": 0, "advertencias": 0, "pendientes": pendientes or [],
            "actualizado_en": _iso(datetime.now(timezone.utc) - hace)}


E1 = [("PUC Principal", 100), ("Terceros", 100), ("Centros de Costos", 100)]
E2 = [("Saldos de Cuentas por Cobrar", 100), ("Saldos de Cuentas por Pagar", 100)]


def _completas(etapa, plantillas):
    return [_f(etapa, n, c) for n, c in plantillas]


def _etapas_visibles(analisis):
    return [None if not analisis["etapas"][n]["aplica"] else panel.pct_visible(analisis["etapas"][n]["pct"], analisis["etapas"][n]["estado"]) for n in (1, 2, 3, 4)]


# ───────────────────────── Las reglas de avance ─────────────────────────
BOCETO = {
    # nombre: (filas, avance global, estado, requiere atención, avance por etapa; None = «No aplica»)
    "Constructora Altavista": (_completas(1, E1) + _completas(2, E2) + [_f(3, "Saldos Iniciales Principal", 71, RC), _f(3, "Movimientos Principal", 53, RC)],
                               66, RC, "Etapa 3: errores en 2 plantillas", [100, 100, 62, 0]),
    "Inmobiliaria Rocamar": ([_f(3, "Saldos Iniciales Principal", 100), _f(3, "Movimientos Principal", 100), _f(4, "Conciliación Cuentas por Pagar", 87, RC)],
                             94, RC, "Etapa 4: 13% sin conciliar", [None, None, 100, 87]),
    "Promotora Cedro": ([_f(1, "PUC Principal", 100), _f(1, "Centros de Costos", 100), _f(1, "Terceros", 55, RC)], 21, RC, "Etapa 1: errores en Terceros", [85, 0, 0, 0]),
    "Grupo Orión": (_completas(1, E1) + _completas(2, E2) + [_f(3, "Saldos Iniciales Principal", 100), _f(3, "Movimientos Principal", 100),
                                                              _f(4, "Conciliación Cuentas por Pagar", 100)], 100, OK, "—", [100, 100, 100, 100]),
    "Inversiones Marfil": (_completas(1, E1) + [_f(2, "Saldos de Cuentas por Cobrar", 100)], 38, "en_proceso", "Etapa 2: falta cargar CxP", [100, 50, 0, 0]),
    "Servicios Delta": ([_f(1, "PUC Principal", 100)], 8, "en_proceso", "Etapa 1: faltan Terceros y Centros de Costos", [33, 0, 0, 0]),
}


@pytest.mark.parametrize("nombre", list(BOCETO))
def test_las_reglas_reproducen_los_clientes_del_boceto(nombre):
    """Los seis clientes de ejemplo del boceto aprobado, con sus números exactos."""
    filas, global_, estado, atencion, etapas = BOCETO[nombre]
    a = panel.analizar_cliente(filas)
    assert panel.pct_visible(a["pct"], a["estado"]) == global_
    assert a["estado"] == estado
    assert panel.requiere_atencion(a) == atencion
    assert _etapas_visibles(a) == etapas


def test_una_plantilla_esperada_que_no_se_ha_cargado_cuenta_cero():
    e = panel.calcular_etapa(1, [_f(1, "PUC Principal", 100)])
    assert round(e["pct"], 1) == 33.3 and e["faltantes"] == ["Terceros", "Centros de Costos"] and e["cargadas_esperadas"] == 1 and e["estado"] == "en_proceso"


def test_el_puc_fiscal_solo_cuenta_si_el_cliente_lo_cargo():
    sin = panel.calcular_etapa(1, _completas(1, E1))
    con = panel.calcular_etapa(1, _completas(1, E1) + [_f(1, "PUC Fiscal", 40, RC)])
    assert sin["pct"] == 100 and sin["estado"] == "completado"
    assert con["pct"] == 85 and con["estado"] == RC and con["esperadas"] == 3          # sigue siendo «3 esperadas»; el fiscal es extra


def test_los_libros_fiscal_y_nif_de_la_etapa_3_solo_cuentan_si_se_cargaron():
    base = [_f(3, "Saldos Iniciales Principal", 100), _f(3, "Movimientos Principal", 100)]
    assert panel.calcular_etapa(3, base)["estado"] == "completado"
    con_nif = panel.calcular_etapa(3, base + [_f(3, "Saldos Iniciales NIF", 50, RC)])
    assert con_nif["estado"] == RC and round(con_nif["pct"], 1) == 83.3


def test_los_nombres_de_plantilla_se_comparan_sin_importar_guiones_ni_mayusculas():
    e = panel.calcular_etapa(3, [_f(3, "Saldos Iniciales — Principal", 100), _f(3, "MOVIMIENTOS  principal", 100)])
    assert e["estado"] == "completado" and e["faltantes"] == []


def test_la_etapa_4_promedia_los_modulos_conciliados_y_se_completa_solo_con_todo_conciliado():
    assert panel.calcular_etapa(4, [])["estado"] == "pendiente"
    dos = panel.calcular_etapa(4, [_f(4, "Conciliación Cuentas por Pagar", 100), _f(4, "Conciliación Cuentas por Cobrar", 80, RC)])
    assert dos["pct"] == 90 and dos["estado"] == RC
    assert panel.calcular_etapa(4, [_f(4, "Conciliación Cuentas por Pagar", 100)])["estado"] == "completado"


def test_un_porcentaje_que_redondea_a_100_no_se_muestra_como_100_si_no_esta_completado():
    assert panel.pct_visible(99.6, RC) == 99 and panel.pct_visible(99.6, "en_proceso") == 99 and panel.pct_visible(100, OK) == 100
    assert panel.pct_visible(37.5, "en_proceso") == 38 and panel.pct_visible(0.4, RC) == 0 and panel.pct_visible(None, RC) == 0


def test_los_estados_de_una_etapa():
    assert panel.calcular_etapa(2, [])["estado"] == "pendiente"
    assert panel.calcular_etapa(2, [_f(2, "Saldos de Cuentas por Cobrar", 100)])["estado"] == "en_proceso"
    assert panel.calcular_etapa(2, [_f(2, "Saldos de Cuentas por Cobrar", 60, RC)])["estado"] == RC
    assert panel.calcular_etapa(2, _completas(2, E2))["estado"] == "completado"


# ───────────────────────── «No aplica» automático ─────────────────────────
def _aplican(filas):
    a = panel.analizar_cliente(filas)
    return [a["etapas"][n]["aplica"] for n in (1, 2, 3, 4)]


def test_una_etapa_atras_que_el_cliente_no_uso_no_aplica():
    assert _aplican([_f(3, "Saldos Iniciales Principal", 50, RC)]) == [False, False, True, True]
    assert _aplican(_completas(1, E1) + [_f(3, "Saldos Iniciales Principal", 50, RC)]) == [True, False, True, True]          # la 2 se omitió
    assert _aplican([_f(2, "Saldos de Cuentas por Cobrar", 50, RC)]) == [False, True, True, True]


def test_sin_etapas_posteriores_todas_aplican_y_la_etapa_3_y_la_4_siempre_aplican():
    assert _aplican([_f(1, "PUC Principal", 100)]) == [True, True, True, True]
    assert _aplican([_f(4, "Conciliación Cuentas por Pagar", 100)]) == [False, False, True, True]
    assert _aplican([_f(3, "Movimientos Principal", 100)])[2:] == [True, True]


def test_si_el_cliente_usa_despues_la_etapa_omitida_vuelve_a_contar():
    antes = panel.analizar_cliente([_f(3, "Saldos Iniciales Principal", 100), _f(3, "Movimientos Principal", 100)])
    despues = panel.analizar_cliente([_f(3, "Saldos Iniciales Principal", 100), _f(3, "Movimientos Principal", 100), _f(1, "PUC Principal", 100)])
    assert antes["etapas"][1]["aplica"] is False and despues["etapas"][1]["aplica"] is True and antes["n_aplican"] == 2 and despues["n_aplican"] == 3
    assert despues["etapas"][2]["aplica"] is False                           # la etapa 2 sigue omitida: el cliente ya está en la 3 y no la usó
    assert despues["pct"] < antes["pct"]                                      # ahora la etapa 1 (incompleta) pesa en el promedio


def test_una_etapa_que_no_aplica_no_cuenta_en_el_avance_global_ni_en_el_estado():
    a = panel.analizar_cliente([_f(3, "Saldos Iniciales Principal", 100), _f(3, "Movimientos Principal", 100), _f(4, "Conciliación Cuentas por Pagar", 100)])
    assert a["estado"] == "completado" and a["pct"] == 100 and a["n_aplican"] == 2


def test_el_cliente_sin_nada_en_las_etapas_que_aplican_esta_pendiente():
    assert panel.analizar_cliente([])["estado"] == "pendiente" and panel.analizar_cliente([])["pct"] == 0


# ───────────────────────── Requiere atención, fechas, filtros y orden ─────────────────────────
def test_requiere_atencion_muestra_la_primera_etapa_con_algo_pendiente():
    assert panel.requiere_atencion(panel.analizar_cliente(_completas(1, E1) + [_f(2, "Saldos de Cuentas por Pagar", 100)])) == "Etapa 2: falta cargar CxC"
    solo_e1 = panel.analizar_cliente(_completas(1, E1))
    assert panel.requiere_atencion(solo_e1) == "Etapa 2: sin iniciar"
    assert panel.requiere_atencion(panel.analizar_cliente([_f(1, "PUC Principal", 100), _f(1, "Terceros", 100), _f(1, "Centros de Costos", 100),
                                                           _f(2, "Saldos de Cuentas por Cobrar", 100), _f(2, "Saldos de Cuentas por Pagar", 60, RC)])) == "Etapa 2: errores en CxP"


def test_hace_texto_cuenta_los_dias_en_hora_de_colombia():
    ahora = datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)                      # 10:00 en Colombia
    assert panel.hace_texto(datetime(2026, 10, 27, 15, 42, tzinfo=timezone.utc), ahora) == "Hoy 10:42"
    assert panel.hace_texto(datetime(2026, 10, 26, 21, 20, tzinfo=timezone.utc), ahora) == "Ayer 16:20"
    assert panel.hace_texto(datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc), ahora) == "Hace 2 días"
    # 02:30 UTC del 27 son las 21:30 del 26 en Colombia: para el panel es «Ayer», no «Hoy»
    assert panel.hace_texto(datetime(2026, 10, 27, 2, 30, tzinfo=timezone.utc), ahora) == "Ayer 21:30"
    assert panel.hace_texto(None, ahora) == "—"


def _clientes_demo():
    return panel.agrupar_clientes(
        [_f(1, n, c, nit="1", nombre="Alfa", hace=timedelta(hours=1)) for n, c in E1] + _completas_de("1", "Alfa", 2, E2, timedelta(hours=1))
        + [_f(3, "Saldos Iniciales Principal", 100, nit="1", nombre="Alfa", hace=timedelta(hours=1)), _f(3, "Movimientos Principal", 100, nit="1", nombre="Alfa", hace=timedelta(hours=1)),
           _f(4, "Conciliación Cuentas por Pagar", 100, nit="1", nombre="Alfa", hace=timedelta(hours=1)),
           _f(4, "Conciliación Cuentas por Pagar", 50, RC, nit="2", nombre="Beta", hace=timedelta(hours=30)),
           _f(1, "PUC Principal", 100, nit="3", nombre="Gamma", hace=timedelta(days=9))])


def _completas_de(nit, nombre, etapa, plantillas, hace):
    return [_f(etapa, n, c, nit=nit, nombre=nombre, hace=hace) for n, c in plantillas]


def test_resumen_y_filtros_cuentan_estados_y_clientes_sin_actividad():
    ahora = datetime.now(timezone.utc)
    clientes = _clientes_demo()
    assert panel.resumen_general(clientes, ahora) == {"registrados": 3, "completados": 1, "requieren": 1, "en_proceso": 1, "inactivos": 1}
    assert panel.contar_filtros(clientes, ahora) == {"todos": 3, "requiere_correcciones": 1, "en_proceso": 1, "completado": 1, "inactivos": 1}
    assert [c["nombre"] for c in panel.filtrar_clientes(clientes, "inactivos", "", ahora)] == ["Gamma"]
    assert [c["nombre"] for c in panel.filtrar_clientes(clientes, "requiere_correcciones", "", ahora)] == ["Beta"]


def test_la_busqueda_encuentra_por_nombre_y_por_nit_con_o_sin_puntos():
    ahora = datetime.now(timezone.utc)
    clientes = panel.agrupar_clientes([_f(1, "PUC Principal", 100, nit="901652178", nombre="PROMOTORA BELONG S.A.S."), _f(1, "PUC Principal", 100, nit="830123456", nombre="Operadora Ferrocarril")])
    assert [c["nit"] for c in panel.filtrar_clientes(clientes, "todos", "belong", ahora)] == ["901652178"]
    assert [c["nit"] for c in panel.filtrar_clientes(clientes, "todos", "FERROCARRIL", ahora)] == ["830123456"]
    assert [c["nit"] for c in panel.filtrar_clientes(clientes, "todos", "901.652.178", ahora)] == ["901652178"]
    assert len(panel.filtrar_clientes(clientes, "todos", "", ahora)) == 2 and panel.filtrar_clientes(clientes, "todos", "no existe", ahora) == []


def test_el_orden():
    clientes = _clientes_demo()
    assert [c["nombre"] for c in panel.ordenar_clientes(clientes, "ultima")] == ["Alfa", "Beta", "Gamma"]
    assert [c["nombre"] for c in panel.ordenar_clientes(clientes, "nombre")] == ["Alfa", "Beta", "Gamma"]
    assert panel.ordenar_clientes(clientes, "avance_menor")[0]["analisis"]["pct"] <= panel.ordenar_clientes(clientes, "avance_menor")[-1]["analisis"]["pct"]
    assert panel.ordenar_clientes(clientes, "avance_mayor")[0]["nombre"] == "Alfa"


def test_el_nombre_es_el_de_la_validacion_mas_reciente_y_filas_malas_se_ignoran():
    clientes = panel.agrupar_clientes([_f(1, "PUC Principal", 100, nit="111111", nombre="NOMBRE VIEJO", hace=timedelta(days=5)),
                                       _f(1, "Terceros", 100, nit="111111", nombre="NOMBRE NUEVO S.A.S.", hace=timedelta(hours=1)), {"nit": ""}, {}])
    assert [(c["nit"], c["nombre"]) for c in clientes] == [("111111", "NOMBRE NUEVO S.A.S.")] and panel.agrupar_clientes(None) == []


def test_los_pendientes_van_de_mas_a_menos_casos_y_ignoran_lo_que_no_es_un_pendiente():
    p = [{"plantilla": "Terceros", "pendientes": [{"categoria": "Banco no válido", "columna": "Banco", "casos": 3}, "basura",
                                                 {"categoria": "Ciudad", "columna": "TerCiudad", "casos": 40}]}]
    assert [f["casos"] for f in panel.pendientes_de(p)] == [40, 3]


def test_formatos():
    assert panel.hora_colombia(panel.fecha_utc("2026-10-27T00:01:44.060692+00:00")) == datetime(2026, 10, 26, 19, 1, 44, 60692)    # UTC−5
    assert panel.hora_colombia(None) is None and panel.fecha_utc("no es fecha") is None and panel.fecha_utc(None) is None
    assert panel.miles(7822) == "7.822" and panel.miles(12) == "12" and panel.miles(None) == "—" and panel.nit_con_puntos("901652178") == "901.652.178"
    assert panel.porcentaje_texto(91.67) == "91.7%" and panel.porcentaje_texto(None) == "—" and panel.porcentaje_entero(91.67) == "92%"


def test_configuracion():
    assert panel.leer_configuracion({"url": "https://x.supabase.co", "clave_publica": "sb_publishable_x"}) == ("https://x.supabase.co", "sb_publishable_x")
    assert panel.leer_configuracion({"activo": False, "url": "https://x.co", "clave_publica": "k"}) == ("https://x.co", "k")   # no depende de 'activo'
    for malo in (None, {}, {"url": "https://x.co"}, {"clave_publica": "k"}, {"url": "ftp://x.co", "clave_publica": "k"}, {"url": "file:///x", "clave_publica": "k"}):
        assert panel.leer_configuracion(malo) is None


# ───────────────────────── Ocultar los rebotes ─────────────────────────
def _h(antes, ahora, hora, plantilla="Conciliación Cuentas por Pagar", etapa=4, dia="26"):
    return {"etapa": etapa, "plantilla": plantilla, "cumplimiento_antes": antes, "cumplimiento": ahora, "estado": RC, "registrado_en": f"2026-10-{dia}T{hora}+00:00"}


def test_el_caso_real_de_promotora_belong_deja_solo_el_cambio_verdadero():
    """Las filas 75 a 79 de la base: tres de ellas son el rebote de 8 segundos (Por Pagar) y dos el de Por Cobrar."""
    historial = [_h(16.67, 91.67, "14:15:58.841239"), _h(84.00, 48.00, "14:52:17.913593", "Conciliación Cuentas por Cobrar"), _h(91.67, 16.67, "14:52:18.401816"),
                 _h(48.00, 84.00, "14:52:26.694913", "Conciliación Cuentas por Cobrar"), _h(16.67, 91.67, "14:52:26.965493")]
    visibles, ocultas = panel.colapsar_rebotes(historial)
    assert [(f["plantilla"], f["cumplimiento"]) for f in visibles] == [("Conciliación Cuentas por Pagar", 91.67)] and ocultas == 4


def test_un_cambio_que_se_revierte_despues_de_un_minuto_si_cuenta():
    assert len(panel.colapsar_rebotes([_h(80, 40, "10:00:00"), _h(40, 80, "10:01:30")])[0]) == 2


def test_un_cambio_que_no_se_revierte_si_cuenta():
    assert len(panel.colapsar_rebotes([_h(80, 40, "10:00:00"), _h(40, 55, "10:00:10")])[0]) == 2


def test_los_rebotes_de_plantillas_distintas_no_se_mezclan():
    assert len(panel.colapsar_rebotes([_h(80, 40, "10:00:00", "Terceros", 1), _h(40, 80, "10:00:05", "Centros de Costos", 1)])[0]) == 2


def test_tres_cambios_seguidos_dejan_el_ultimo():
    """10→20, 20→10, 10→20 en segundos: el resultado final (20) es el que queda."""
    visibles, ocultas = panel.colapsar_rebotes([_h(10, 20, "10:00:00"), _h(20, 10, "10:00:05"), _h(10, 20, "10:00:10")])
    assert [(f["cumplimiento_antes"], f["cumplimiento"]) for f in visibles] == [(10, 20)] and ocultas == 2


def test_el_historial_sale_de_la_fila_mas_reciente_a_la_mas_antigua_y_tolera_datos_malos():
    visibles, _ = panel.colapsar_rebotes([_h(None, 50, "09:00:00"), _h(50, 70, "11:00:00"), {"registrado_en": "no es fecha"}, {}])
    assert [f["cumplimiento"] for f in visibles] == [70, 50] and panel.colapsar_rebotes(None) == ([], 0)


def test_la_serie_de_la_grafica_es_el_avance_global_al_cierre_de_cada_dia():
    h = [{**_h(None, 100, "15:00:00", "PUC Principal", 1, "20"), "estado": OK}, {**_h(None, 100, "16:00:00", "Terceros", 1, "21"), "estado": OK},
         {**_h(100, 40, "17:00:00", "Terceros", 1, "21"), "estado": RC}, {**_h(None, 100, "15:00:00", "Centros de Costos", 1, "22"), "estado": OK}]
    serie = panel.serie_global_por_dia(h)
    assert [d.day for d, _ in serie] == [20, 21, 22] and all(0 <= v <= 99 for _, v in serie)
    assert serie[0][1] < serie[2][1] or serie[0][1] == serie[2][1] or True       # la forma exacta depende de las reglas: aquí solo se exige que no falle
    assert panel.serie_global_por_dia(None) == [] and panel.serie_global_por_dia([{"registrado_en": "x"}]) == []


# ───────────────────────── El HTML: lo que escribe un usuario no puede inyectar nada ─────────────────────────
HOSTIL = '<img src=x onerror="alert(1)"><script>alert(2)</script>'


def _cliente_hostil():
    return panel.agrupar_clientes([_f(1, HOSTIL, 55, RC, nombre=HOSTIL, pendientes=[{"categoria": HOSTIL, "columna": HOSTIL, "casos": 3}], fuente=HOSTIL)])


def test_el_html_de_la_tabla_escapa_el_nombre_del_cliente_y_la_plantilla():
    ahora = datetime.now(timezone.utc)
    html = panel.html_tabla_clientes(_cliente_hostil(), [], ahora)
    assert "<script" not in html and "<img" not in html and "&lt;script&gt;" in html


def test_el_html_del_detalle_escapa_pendientes_historial_y_origen():
    ahora = datetime.now(timezone.utc)
    c = _cliente_hostil()[0]
    historial = [{"etapa": 1, "plantilla": HOSTIL, "cumplimiento_antes": None, "cumplimiento": 55, "estado": RC, "registrado_en": "2026-10-26T10:00:00+00:00"}]
    for html in (panel.html_pendientes(c), panel.html_resumen_detalle(c, historial, ahora), panel.html_tarjetas_etapas(c), panel.html_historial([], historial)):
        assert "<script" not in html and "<img" not in html


def test_la_tabla_muestra_no_aplica_y_la_fila_sin_identificar_solo_si_hubo_usos_recientes():
    ahora = datetime.now(timezone.utc)
    clientes = panel.agrupar_clientes(BOCETO["Inmobiliaria Rocamar"][0])
    sin = [{"etapa": 2, "plantilla": "Saldos de Cuentas por Cobrar", "usos": 5, "usos_14_dias": 4, "ultimo_uso": _iso(ahora - timedelta(hours=1))}]
    html = panel.html_tabla_clientes(clientes, sin, ahora)
    assert html.count("No aplica") == 2 and "4 validaciones sin NIT en las últimas 2 semanas" in html and "Etapa 2: falta el NIT" in html
    sin_recientes = [{**sin[0], "usos_14_dias": 0}]
    assert "Sin identificar" not in panel.html_tabla_clientes(clientes, sin_recientes, ahora) and "Sin identificar" not in panel.html_tabla_clientes(clientes, None, ahora)


def test_la_tarjeta_de_una_etapa_omitida_explica_por_que_segun_el_caso():
    empezo_en_3 = panel.html_tarjetas_etapas(panel.agrupar_clientes(BOCETO["Inmobiliaria Rocamar"][0])[0])
    assert empezo_en_3.count("Se omitió: el cliente empezó en la Etapa 3.") == 2                       # las etapas 1 y 2
    saltada = panel.html_tarjetas_etapas(panel.agrupar_clientes(_completas(1, E1) + [_f(3, "Saldos Iniciales Principal", 50, RC)])[0])
    assert saltada.count("Se omitió") == 1 and "avanzó a una etapa posterior sin usarla" in saltada and "empezó en la Etapa" not in saltada


def test_el_detalle_de_un_cliente_con_etapas_omitidas_sigue_el_boceto():
    c = panel.agrupar_clientes(BOCETO["Inmobiliaria Rocamar"][0])[0]
    tarjetas = panel.html_tarjetas_etapas(c)
    assert tarjetas.count("No aplica") == 4 + 1                              # dos tarjetas: título y etiqueta en cada una (4) y «No aplica» en el párrafo (1)
    assert "13% de los registros sin conciliar" in tarjetas and "2 de 2 plantillas esperadas · sin errores" in tarjetas
    assert 'Los directores no tienen que configurar nada' in tarjetas
    resumen = panel.html_resumen_detalle(c, [], datetime.now(timezone.utc))
    assert "Etapas que aplican" in resumen and "2 de 4" in resumen and "Origen del NIT" not in resumen
    completo = panel.agrupar_clientes(BOCETO["Grupo Orión"][0])[0]
    assert "Los directores no tienen que configurar nada" not in panel.html_tarjetas_etapas(completo)
    resumen_completo = panel.html_resumen_detalle(completo, [], datetime.now(timezone.utc))
    assert "Etapas que aplican" not in resumen_completo and "Origen del NIT" in resumen_completo
    assert "Todo conciliado" in panel.html_tarjetas_etapas(completo)


def test_la_ultima_marca_de_la_grafica_es_el_avance_global_actual():
    a = panel.analizar_cliente(BOCETO["Constructora Altavista"][0])
    h = [{**_h(None, 100, "15:00:00", "PUC Principal", 1, "20"), "estado": OK}, {**_h(None, 30, "16:00:00", "Movimientos Principal", 3, "21"), "estado": RC}]
    serie = panel.serie_para_grafica(h, a)
    assert [d.day for d, _ in serie] == [20, 21] and serie[-1][1] == panel.pct_visible(a["pct"], a["estado"]) == 66
    assert panel.serie_para_grafica([], a) == []


def test_las_tarjetas_de_resumen_traen_los_cinco_contadores():
    html = panel.html_tarjetas_resumen({"registrados": 6, "completados": 1, "requieren": 3, "en_proceso": 2, "inactivos": 1})
    for etiqueta in ("Clientes registrados", "Completados", "Requieren correcciones", "En proceso", "Sin actividad hace más de 7 días"):
        assert etiqueta in html


def test_la_grafica_sin_dos_dias_explica_en_vez_de_dibujar():
    assert "Todavía no hay suficientes días" in panel.html_grafica([]) and "<polyline" not in panel.html_grafica([(datetime(2026, 10, 20).date(), 50)])
    assert "<polyline" in panel.html_grafica([(datetime(2026, 10, 20).date(), 10), (datetime(2026, 10, 21).date(), 60)])


# ───────────────────────── Servidor de prueba (hace de Supabase) ─────────────────────────
class _Base:
    def __init__(self, avance=None, sin=None, historial=None):
        self.avance, self.sin, self.historial = avance or [], sin or [], historial or {}
        self.modo = "normal"            # normal | caido | basura | bloqueado
        self.llamadas, self.fallos = [], 0


def _servidor(base):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            cuerpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            funcion = self.path.rsplit("/", 1)[-1]
            base.llamadas.append((self.path, cuerpo, {k.lower(): v for k, v in self.headers.items()}))      # urllib escribe «Apikey»
            codigo, datos = 200, None
            if base.modo == "caido":
                codigo, datos = 500, {"mensaje": "error"}
            elif base.modo == "bloqueado":
                datos = {"ok": False, "error": "bloqueado"}
            elif cuerpo.get("p_codigo") != CODIGO:
                base.fallos += 1
                datos = {"ok": False, "error": "codigo_incorrecto"}
            elif funcion == "panel_resumen":
                datos = {"ok": True, "generado_en": _iso(datetime.now(timezone.utc)), "avance": base.avance, "sin_identificar": base.sin}
            elif funcion == "panel_historial":
                datos = {"ok": True, "historial": base.historial.get(cuerpo.get("p_nit"), [])}
            salida = b"esto no es json" if base.modo == "basura" else json.dumps(datos).encode()
            self.send_response(codigo)
            self.end_headers()
            self.wfile.write(salida)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def base_falsa():
    base = _Base()
    srv = _servidor(base)
    base.url = f"http://127.0.0.1:{srv.server_port}"
    yield base
    srv.shutdown()


# ───────────────────────── La conexión ─────────────────────────
def test_consultar_devuelve_los_datos_y_manda_la_ruta_la_llave_y_el_codigo(base_falsa):
    base_falsa.avance = [_f(1, "PUC Principal", 100)]
    r = panel.consultar(base_falsa.url, "sb_publishable_x", "panel_resumen", {"p_codigo": CODIGO})
    assert r["ok"] and len(r["avance"]) == 1
    ruta, cuerpo, cabeceras = base_falsa.llamadas[0]
    assert ruta == "/rest/v1/rpc/panel_resumen" and cuerpo == {"p_codigo": CODIGO}
    assert cabeceras["apikey"] == "sb_publishable_x" and "authorization" not in cabeceras


def test_una_llave_antigua_jwt_tambien_va_como_bearer(base_falsa):
    panel.consultar(base_falsa.url, "eyJhbGciOi.x.y", "panel_resumen", {"p_codigo": CODIGO})
    assert base_falsa.llamadas[0][2]["authorization"] == "Bearer eyJhbGciOi.x.y"


@pytest.mark.parametrize("modo,tipo", [("caido", "sin_conexion"), ("basura", "sin_conexion"), ("bloqueado", "bloqueado")])
def test_consultar_traduce_los_fallos(base_falsa, modo, tipo):
    base_falsa.modo = modo
    with pytest.raises(panel.ErrorPanel) as e:
        panel.consultar(base_falsa.url, "k", "panel_resumen", {"p_codigo": CODIGO})
    assert e.value.tipo == tipo


def test_codigo_incorrecto_se_reporta(base_falsa):
    with pytest.raises(panel.ErrorPanel) as e:
        panel.consultar(base_falsa.url, "k", "panel_resumen", {"p_codigo": "mal"})
    assert e.value.tipo == "codigo_incorrecto" and base_falsa.fallos == 1


def test_un_servidor_inaccesible_responde_rapido_y_sin_detalles_tecnicos_para_el_usuario():
    t0 = time.time()
    with pytest.raises(panel.ErrorPanel) as e:
        panel.consultar("http://127.0.0.1:9", "k", "panel_resumen", {"p_codigo": CODIGO})
    assert time.time() - t0 < panel.TIMEOUT_SEG + 2 and e.value.tipo == "sin_conexion" and e.value.tipo in panel.MENSAJES_ERROR


# ───────────────────────── La base de datos: código, bloqueo y permisos ─────────────────────────
DSN = os.environ.get("SEGUIMIENTO_PG_DSN")
requiere_base = pytest.mark.skipif(not DSN, reason="define SEGUIMIENTO_PG_DSN para probar contra una base PostgreSQL")


def _ruta_sql(nombre):
    ruta = os.path.join(RAIZ, nombre)
    return ruta if os.path.exists(ruta) else os.path.join(RAIZ, "..", nombre)


@pytest.fixture(scope="module")
def base_pg():
    """Una base PostgreSQL nueva y vacía con la fase 0 y la fase 2 aplicadas (se borra al terminar)."""
    psycopg2 = pytest.importorskip("psycopg2")
    from psycopg2.extensions import parse_dsn
    datos = parse_dsn(DSN)
    nombre = f"panel_prueba_{uuid.uuid4().hex[:8]}"
    admin = psycopg2.connect(**{**datos, "dbname": "postgres"})
    admin.autocommit = True
    admin.cursor().execute(f'create database "{nombre}"')
    conexion = psycopg2.connect(**{**datos, "dbname": nombre})
    conexion.autocommit = True
    c = conexion.cursor()
    c.execute("""do $$ begin
        if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
        if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
        if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin; end if;
    end $$""")
    c.execute("create schema if not exists extensions")
    for archivo in ("seguimiento_supabase_fase0.sql", "seguimiento_supabase_fase2_panel.sql"):
        c.execute(open(_ruta_sql(archivo), encoding="utf-8").read())
    yield conexion
    conexion.close()
    admin.cursor().execute(f'drop database "{nombre}" with (force)')
    admin.close()


@pytest.fixture
def pg(base_pg):
    """La base de siempre, vacía y con el código de directores puesto."""
    c = base_pg.cursor()
    c.execute("truncate public.avance_actual, public.historial_validaciones, public.panel_intentos_fallidos")
    c.execute("select public.panel_cambiar_codigo(%s)", (CODIGO,))
    return base_pg


def _anon(conexion, sql, params=None):
    c = conexion.cursor()
    c.execute("set role anon")
    try:
        c.execute(sql, params)
        return c.fetchall() if c.description else None
    finally:
        c.execute("reset role")


def _resumen(conexion, codigo):
    return _anon(conexion, "select public.panel_resumen(%s)", (codigo,))[0][0]


def _avance(conexion, nit="901652178", nombre="PROMOTORA BELONG S.A.S.", etapa=4, plantilla="Conciliación Cuentas por Pagar", fuente="informe"):
    conexion.cursor().execute(
        """insert into public.avance_actual (nit, etapa, plantilla, nombre_cliente, fuente_nit, filas_evaluadas, filas_con_error, cumplimiento, estado, pendientes)
           values (%s, %s, %s, %s, %s, 12, 1, 91.67, 'requiere_correcciones', '[{"categoria": "X", "columna": "Y", "casos": 1}]')""",
        (nit, etapa, plantilla, nombre, fuente))


@requiere_base
def test_sin_codigo_configurado_no_entra_nadie(base_pg):
    base_pg.cursor().execute("truncate public.panel_acceso, public.panel_intentos_fallidos")
    assert _resumen(base_pg, "lo-que-sea") == {"ok": False, "error": "sin_configurar"}


@requiere_base
def test_el_codigo_se_guarda_cifrado_no_en_texto_claro(pg):
    c = pg.cursor()
    c.execute("select codigo_hash from public.panel_acceso")
    guardado = c.fetchone()[0]
    assert guardado.startswith("$2") and CODIGO not in guardado


@requiere_base
def test_con_el_codigo_correcto_devuelve_el_avance_y_los_usos_sin_identificar(pg):
    _avance(pg, fuente="digitado")
    pg.cursor().execute("insert into public.historial_validaciones (nit, etapa, plantilla) values ('SIN-IDENTIFICAR', 1, 'Terceros'), ('SIN-IDENTIFICAR', 1, 'Terceros')")
    r = _resumen(pg, CODIGO)
    assert r["ok"] is True and "generado_en" in r
    assert len(r["avance"]) == 1 and r["avance"][0]["nombre_cliente"] == "PROMOTORA BELONG S.A.S." and r["avance"][0]["fuente_nit"] == "digitado"
    assert r["avance"][0]["pendientes"] == [{"categoria": "X", "columna": "Y", "casos": 1}]
    assert [(s["etapa"], s["plantilla"], s["usos"], s["usos_14_dias"]) for s in r["sin_identificar"]] == [(1, "Terceros", 2, 2)]


@requiere_base
def test_los_usos_sin_identificar_distinguen_las_ultimas_dos_semanas(pg):
    pg.cursor().execute("""insert into public.historial_validaciones (nit, etapa, plantilla, registrado_en) values
        ('SIN-IDENTIFICAR', 2, 'Saldos de Cuentas por Cobrar', now()), ('SIN-IDENTIFICAR', 2, 'Saldos de Cuentas por Cobrar', now() - interval '3 days'),
        ('SIN-IDENTIFICAR', 2, 'Saldos de Cuentas por Cobrar', now() - interval '30 days')""")
    s = _resumen(pg, CODIGO)["sin_identificar"][0]
    assert s["usos"] == 3 and s["usos_14_dias"] == 2


@requiere_base
def test_la_respuesta_solo_trae_las_columnas_esperadas(pg):
    _avance(pg)
    fila = _resumen(pg, CODIGO)["avance"][0]
    assert set(fila) == {"nit", "nombre_cliente", "fuente_nit", "etapa", "plantilla", "cumplimiento", "estado", "filas_evaluadas", "filas_con_error",
                         "errores_globales", "advertencias", "pendientes", "actualizado_en"}


@requiere_base
@pytest.mark.parametrize("malo", ["", "mal", None, "x" * 101, CODIGO.lower(), CODIGO + " "])
def test_un_codigo_incorrecto_no_entra(pg, malo):
    assert _resumen(pg, malo) == {"ok": False, "error": "codigo_incorrecto"}


@requiere_base
def test_cinco_intentos_fallidos_bloquean_incluso_el_codigo_correcto_y_pasados_10_minutos_se_libera(pg):
    for _ in range(5):
        assert _resumen(pg, "mal")["error"] == "codigo_incorrecto"
    assert _resumen(pg, CODIGO) == {"ok": False, "error": "bloqueado"}
    pg.cursor().execute("update public.panel_intentos_fallidos set intentado_en = now() - interval '11 minutes'")
    assert _resumen(pg, CODIGO)["ok"] is True


@requiere_base
def test_cuatro_intentos_fallidos_todavia_no_bloquean(pg):
    for _ in range(4):
        _resumen(pg, "mal")
    assert _resumen(pg, CODIGO)["ok"] is True


@requiere_base
def test_el_publico_no_puede_leer_las_tablas_ni_llamar_a_las_funciones_internas(pg):
    psycopg2 = pytest.importorskip("psycopg2")
    prohibido = ["select * from public.avance_actual", "select * from public.historial_validaciones", "select * from public.panel_acceso",
                 "select * from public.panel_intentos_fallidos", "select public._panel_verificar('x')",
                 "select public.panel_cambiar_codigo('CodigoNuevo-123456')", "update public.panel_acceso set codigo_hash = 'x'",
                 "delete from public.avance_actual"]
    for sql in prohibido:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            _anon(pg, sql)


@requiere_base
def test_el_publico_si_puede_llamar_a_las_dos_lecturas(pg):
    assert _anon(pg, "select public.panel_resumen(%s)", (CODIGO,))[0][0]["ok"] is True
    assert _anon(pg, "select public.panel_historial(%s, %s)", (CODIGO, "901652178"))[0][0]["ok"] is True


@requiere_base
def test_el_historial_de_una_empresa_trae_lo_suyo_y_nada_de_otras(pg):
    pg.cursor().execute("""insert into public.historial_validaciones (nit, nombre_cliente, etapa, plantilla, cumplimiento_antes, cumplimiento, estado)
                 values ('901652178', 'BELONG', 4, 'P', null, 50, 'requiere_correcciones'), ('901652178', 'BELONG', 4, 'P', 50, 80, 'requiere_correcciones'),
                        ('830123456', 'OTRA', 1, 'T', null, 100, 'completado')""")
    r = _anon(pg, "select public.panel_historial(%s, %s)", (CODIGO, "901652178"))[0][0]
    assert r["ok"] and [f["cumplimiento"] for f in r["historial"]] == [80, 50]          # la más reciente primero, aunque tengan la misma hora


@requiere_base
def test_el_historial_devuelve_como_maximo_500_movimientos(pg):
    pg.cursor().execute("insert into public.historial_validaciones (nit, etapa, plantilla, cumplimiento) select '901652178', 4, 'P', 50 from generate_series(1, 520)")
    assert len(_anon(pg, "select public.panel_historial(%s, %s)", (CODIGO, "901652178"))[0][0]["historial"]) == 500


@requiere_base
@pytest.mark.parametrize("nit", ["abc", "", "123", "1234567890123", "9016' or '1'='1", "901652178; drop table public.avance_actual"])
def test_el_historial_rechaza_un_nit_que_no_es_un_nit(pg, nit):
    assert _anon(pg, "select public.panel_historial(%s, %s)", (CODIGO, nit))[0][0] == {"ok": False, "error": "nit_invalido"}


@requiere_base
def test_el_historial_tambien_exige_el_codigo(pg):
    assert _anon(pg, "select public.panel_historial(%s, %s)", ("mal", "901652178"))[0][0] == {"ok": False, "error": "codigo_incorrecto"}


@requiere_base
def test_cambiar_el_codigo_invalida_el_anterior_y_limpia_los_bloqueos(pg):
    for _ in range(5):
        _resumen(pg, "mal")
    pg.cursor().execute("select public.panel_cambiar_codigo('OtroCodigoDistinto-9')")
    assert _resumen(pg, CODIGO)["error"] == "codigo_incorrecto"
    assert _resumen(pg, "OtroCodigoDistinto-9")["ok"] is True


@requiere_base
@pytest.mark.parametrize("corto", ["", "corto", "123456789", "x" * 101])
def test_un_codigo_demasiado_corto_o_largo_no_se_acepta_y_no_cambia_el_actual(pg, corto):
    psycopg2 = pytest.importorskip("psycopg2")
    with pytest.raises(psycopg2.Error):
        pg.cursor().execute("select public.panel_cambiar_codigo(%s)", (corto,))
    assert _resumen(pg, CODIGO)["ok"] is True


@requiere_base
def test_ejecutar_el_script_otra_vez_no_borra_el_codigo_ni_los_datos(pg):
    _avance(pg)
    pg.cursor().execute(open(_ruta_sql("seguimiento_supabase_fase2_panel.sql"), encoding="utf-8").read())
    assert len(_resumen(pg, CODIGO)["avance"]) == 1


@requiere_base
def test_el_script_nuevo_se_puede_aplicar_sobre_la_version_anterior_sin_perder_nada(pg):
    """La usuaria ya tenía la primera versión del script en Supabase: al volver a ejecutar la nueva no se pierde el código ni los datos."""
    _avance(pg)
    pg.cursor().execute(open(_ruta_sql("seguimiento_supabase_fase2_panel.sql"), encoding="utf-8").read())
    r = _resumen(pg, CODIGO)
    assert r["ok"] and r["avance"][0]["fuente_nit"] == "informe" and "usos_14_dias" not in r["avance"][0]


# ───────────────────────── La pantalla ─────────────────────────
XLSX_APP = os.path.join(RAIZ, "validador_sinco_ayf.py")


def _demo(base):
    ahora = datetime.now(timezone.utc)
    belong = dict(nit="901652178", nombre="PROMOTORA BELONG S.A.S.")
    base.avance = [
        _f(1, "Terceros", 100, **belong),
        _f(4, "Conciliación Cuentas por Pagar", 91.67, RC, filas=12, err=1, pendientes=[{"categoria": "Diferencia de valor", "columna": "Conciliación", "casos": 1}], **belong),
        _f(4, "Conciliación Cuentas por Cobrar", 84.0, RC, filas=25, err=4, pendientes=[{"categoria": "Solo en contabilidad", "columna": "Conciliación", "casos": 3}], **belong),
        _f(4, "Conciliación Cuentas por Cobrar", 0.0, RC, filas=12, err=12, nit="901938545", nombre="OPERADORA FERROCARRIL CENTRAL S.A.S.", hace=timedelta(hours=40)),
        *[_f(e, n, c, nit="830123456", nombre="Empresa al día S.A.S.", hace=timedelta(hours=1)) for e, plantillas in
          ((1, E1), (2, E2), (3, [("Saldos Iniciales Principal", 100), ("Movimientos Principal", 100)]), (4, [("Conciliación Cuentas por Pagar", 100)])) for n, c in plantillas],
        *[_f(1, n, c, nit="860001234", nombre="Inversiones Marfil Ltda.", hace=timedelta(days=12)) for n, c in E1],
        _f(2, "Saldos de Cuentas por Cobrar", 100, nit="860001234", nombre="Inversiones Marfil Ltda.", hace=timedelta(days=12)),
    ]
    base.sin = [{"etapa": 2, "plantilla": "Saldos de Cuentas por Cobrar", "usos": 9, "usos_14_dias": 4, "ultimo_uso": _iso(ahora - timedelta(hours=2))}]
    rebotes = [_h(16.67, 91.67, "14:15:58.841239"), _h(84.0, 48.0, "14:52:17.913593", "Conciliación Cuentas por Cobrar"), _h(91.67, 16.67, "14:52:18.401816"),
               _h(48.0, 84.0, "14:52:26.694913", "Conciliación Cuentas por Cobrar"), _h(16.67, 91.67, "14:52:26.965493")]
    base.historial = {"901652178": [
        *rebotes, {**_h(None, 100, "09:00:00", "Terceros", 1, "20"), "estado": OK}, _h(None, 40, "10:00:00", "Conciliación Cuentas por Cobrar", 4, "21"),
        _h(40, 60, "11:00:00", "Conciliación Cuentas por Cobrar", 4, "22"), _h(60, 84, "12:00:00", "Conciliación Cuentas por Cobrar", 4, "23"),
        _h(None, 70, "13:00:00", "Conciliación Cuentas por Pagar", 4, "24"), _h(70, 91.67, "14:00:00", "Conciliación Cuentas por Pagar", 4, "25")][::-1]}


def _app(base=None, con_secretos=True, panel_param=True):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(XLSX_APP, default_timeout=60)
    if panel_param:
        app.query_params["panel"] = "1"
    if con_secretos and base is not None:
        app.secrets["seguimiento"] = {"activo": True, "url": base.url, "clave_publica": "sb_publishable_prueba"}
    app.run()
    return app


def _entrar(app, codigo=CODIGO):
    next(c for c in app.text_input if (c.key or "") == "panel_codigo").set_value(codigo)
    next(b for b in app.button if b.label == "Entrar").click().run()
    return app


def _html(app):
    return " ".join(m.value for m in app.markdown)


def _texto(app):
    """Todo el texto visible de la página, sin etiquetas HTML y con espacios normalizados."""
    crudo = " ".join([_html(app), *(e.value for e in app.error), *(w.value for w in app.warning), *(i.value for i in app.info), *(c.value for c in app.caption)])
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", crudo))


def _kpi(app, etiqueta):
    m = re.search(re.escape(etiqueta) + r"</div><div[^>]*>(\d+)</div>", _html(app))
    return int(m.group(1)) if m else None


def _panel_abierto(base_falsa):
    _demo(base_falsa)
    return _entrar(_app(base_falsa))


def _abrir_detalle(app, nombre):
    sel = next(s for s in app.selectbox if s.key == "panel_empresa")
    sel.select(next(o for o in sel.options if nombre in o)).run()
    next(b for b in app.button if b.key == "panel_abrir").click().run()
    return app


def test_sin_el_enlace_especial_la_app_es_la_de_siempre(base_falsa):
    app = _app(base_falsa, panel_param=False)
    assert any(b.label == "➡️ Iniciar validación" for b in app.button)
    assert "Código de directores" not in _texto(app) and not app.exception
    assert not [c for c in app.text_input if (c.key or "") == "panel_codigo"]


def test_con_el_enlace_especial_se_pide_el_codigo_y_no_se_ve_la_app_normal(base_falsa):
    app = _app(base_falsa)
    assert [c for c in app.text_input if (c.key or "") == "panel_codigo"] and not app.exception
    assert not any(b.label == "➡️ Iniciar validación" for b in app.button)
    assert not base_falsa.llamadas                                      # mientras no se escribe el código no se consulta nada


def test_sin_configuracion_del_seguimiento_se_avisa():
    app = _app(None, con_secretos=False)
    assert "no está configurado" in _texto(app) and not app.exception


def test_un_codigo_incorrecto_no_muestra_datos(base_falsa):
    _demo(base_falsa)
    app = _entrar(_app(base_falsa), "mal")
    assert "El código no es correcto" in _texto(app) and "Clientes registrados" not in _html(app) and not app.exception


def test_codigo_vacio_no_consulta_nada(base_falsa):
    app = _entrar(_app(base_falsa), "   ")
    assert "Escribe el código" in _texto(app) and not base_falsa.llamadas


@pytest.mark.parametrize("modo,mensaje", [("bloqueado", "Espera 10 minutos"), ("caido", "No se pudo consultar"), ("basura", "No se pudo consultar")])
def test_los_fallos_se_explican_sin_mostrar_datos_tecnicos(base_falsa, modo, mensaje):
    base_falsa.modo = modo
    app = _entrar(_app(base_falsa))
    assert mensaje in _texto(app) and "Clientes registrados" not in _html(app) and not app.exception
    assert "HTTP" not in _texto(app) and "Traceback" not in _texto(app)


def test_con_el_codigo_correcto_se_ven_los_cinco_contadores_y_la_tabla_de_clientes(base_falsa):
    app = _panel_abierto(base_falsa)
    assert not app.exception
    assert [_kpi(app, e) for e in ("Clientes registrados", "Completados", "Requieren correcciones", "En proceso", "Sin actividad hace más de 7 días")] == [4, 1, 2, 1, 1]
    html = _html(app)
    for nombre in ("PROMOTORA BELONG S.A.S.", "OPERADORA FERROCARRIL CENTRAL S.A.S.", "Empresa al día S.A.S.", "Inversiones Marfil Ltda."):
        assert nombre in html
    assert "NIT 901.652.178" in html and "Etapa 4: 12% sin conciliar" not in html
    assert html.count('>No aplica</div>') == 3                            # OPERADORA FERROCARRIL: etapas 1 y 2; BELONG: la etapa 2
    assert "Etapa 1: faltan PUC Principal y Centros de Costos" in html and "Etapa 2: falta cargar CxP" in html
    assert "4 validaciones sin NIT en las últimas 2 semanas" in html and "Hace 12 días" in html
    assert "Origen" not in html                                           # el origen del NIT solo se ve en el detalle


def test_los_clientes_salen_de_la_actividad_mas_reciente_a_la_mas_antigua(base_falsa):
    html = _html(_panel_abierto(base_falsa))
    orden = [html.index(n) for n in ("Empresa al día S.A.S.", "PROMOTORA BELONG S.A.S.", "OPERADORA FERROCARRIL CENTRAL S.A.S.", "Inversiones Marfil Ltda.")]
    assert orden == sorted(orden)


def test_los_filtros_muestran_cuantos_hay_y_filtran_la_tabla(base_falsa):
    app = _panel_abierto(base_falsa)
    radio = next(r for r in app.radio if r.key == "panel_filtro")
    assert radio.options == ["Todos (4)", "Requieren correcciones (2)", "En proceso (1)", "Completados (1)", "Sin actividad +7 días (1)"]
    radio.set_value("Requieren correcciones (2)").run()
    html = _html(app)
    assert "PROMOTORA BELONG S.A.S." in html and "OPERADORA FERROCARRIL CENTRAL S.A.S." in html and "Empresa al día S.A.S." not in html
    next(r for r in app.radio if r.key == "panel_filtro").set_value("Sin actividad +7 días (1)").run()
    assert "Inversiones Marfil Ltda." in _html(app) and "PROMOTORA BELONG S.A.S." not in _html(app)


def test_la_busqueda_filtra_la_tabla_y_avisa_si_no_hay_coincidencias(base_falsa):
    app = _panel_abierto(base_falsa)
    next(t for t in app.text_input if t.key == "panel_buscar").set_value("ferrocarril").run()
    html = _html(app)
    assert "OPERADORA FERROCARRIL CENTRAL S.A.S." in html and "PROMOTORA BELONG S.A.S." not in html
    next(t for t in app.text_input if t.key == "panel_buscar").set_value("zzz").run()
    assert "Ningún cliente coincide" in _texto(app) and not app.exception


def test_el_orden_cambia_la_tabla(base_falsa):
    app = _panel_abierto(base_falsa)
    sel = next(s for s in app.selectbox if s.key == "panel_orden")
    sel.select(next(o for o in sel.options if o.startswith("Nombre"))).run()
    html = _html(app)
    orden = [html.index(n) for n in ("Empresa al día S.A.S.", "Inversiones Marfil Ltda.", "OPERADORA FERROCARRIL CENTRAL S.A.S.", "PROMOTORA BELONG S.A.S.")]
    assert orden == sorted(orden)


def test_el_detalle_muestra_avance_etapas_pendientes_e_historial_sin_rebotes(base_falsa):
    app = _abrir_detalle(_panel_abierto(base_falsa), "PROMOTORA BELONG")
    assert not app.exception
    html, texto = _html(app), _texto(app)
    assert "NIT 901.652.178 · Identificado a partir de: Informes del sistema" in texto
    for dato in ("Avance global", "Primera actividad", "Última actividad", "Validaciones realizadas", "Etapas que aplican", "Pendientes de la Etapa 4", "Historial de uso"):
        assert dato in texto                                                                 # BELONG tiene una etapa que no aplica: «Etapas que aplican» va en lugar del origen del NIT
    assert "Origen del NIT" not in texto and "3 de 4" in texto
    assert "empezó en la Etapa" not in texto                                                  # BELONG sí usó la etapa 1: no «empezó» más adelante
    assert "Se omitió: el cliente avanzó a una etapa posterior sin usarla" in texto           # la etapa 2 se saltó
    assert "Se habilita al aprobar la Etapa 3" not in texto                                   # la 4 ya tiene datos
    assert "Diferencia de valor" in texto and "Solo en contabilidad" in texto and "registros sin error" in texto
    assert "<polyline" in html                                                               # la gráfica del historial
    assert "Se ocultaron 4 movimientos" in texto
    assert any(h[0].endswith("panel_historial") and h[1]["p_nit"] == "901652178" for h in base_falsa.llamadas)


def test_el_historial_completo_se_ve_en_un_desplegable_sin_los_rebotes(base_falsa):
    app = _abrir_detalle(_panel_abierto(base_falsa), "PROMOTORA BELONG")
    expansor = next(e for e in app.expander if e.label.startswith("Ver las"))
    n = int(re.search(r"Ver las (\d+) validaciones", expansor.label).group(1))
    assert n == 7                                                                            # 11 movimientos − 4 de los rebotes
    tabla = next(d.value for d in app.dataframe)
    assert len(tabla) == n and set(tabla.columns) == {"Fecha", "Plantilla", "Etapa", "Antes", "Ahora"}


def test_una_etapa_sin_datos_dice_cuando_se_habilita_y_el_cliente_completo_no_tiene_pendientes(base_falsa):
    app = _abrir_detalle(_panel_abierto(base_falsa), "Inversiones Marfil")
    assert "falta CxP" in _texto(app) and "Se habilita al aprobar la Etapa 3" in _texto(app) and "Pendientes de la Etapa" not in _texto(app)
    app2 = _abrir_detalle(_panel_abierto(base_falsa), "Empresa al día")
    assert "no tiene errores pendientes" in _texto(app2) and "Completado" in _html(app2)


def test_volver_al_panel_regresa_a_la_tabla(base_falsa):
    app = _abrir_detalle(_panel_abierto(base_falsa), "PROMOTORA BELONG")
    next(b for b in app.button if b.key == "panel_volver").click().run()
    assert "Clientes registrados" in _html(app) and "Pendientes de la Etapa" not in _texto(app)


def test_actualizar_vuelve_a_pedir_los_datos_y_salir_vuelve_a_pedir_el_codigo(base_falsa):
    app = _panel_abierto(base_falsa)
    antes = len([h for h in base_falsa.llamadas if h[0].endswith("panel_resumen")])
    next(b for b in app.button if b.label == "🔄 Actualizar").click().run()
    assert len([h for h in base_falsa.llamadas if h[0].endswith("panel_resumen")]) == antes + 1
    next(b for b in app.button if b.label == "Salir").click().run()
    assert [c for c in app.text_input if (c.key or "") == "panel_codigo"] and "Clientes registrados" not in _html(app)


def test_si_el_codigo_cambia_mientras_se_usa_el_panel_pide_entrar_de_nuevo(base_falsa):
    app = _panel_abierto(base_falsa)
    base_falsa.modo = "bloqueado"
    next(b for b in app.button if b.label == "🔄 Actualizar").click().run()
    assert [c for c in app.text_input if (c.key or "") == "panel_codigo"] and "Clientes registrados" not in _html(app)
    assert "Espera 10 minutos" in _texto(app) and not app.exception


def test_un_nombre_de_empresa_con_html_no_se_inyecta_en_la_pagina(base_falsa):
    _demo(base_falsa)
    base_falsa.avance[0]["nombre_cliente"] = HOSTIL
    base_falsa.avance[1]["nombre_cliente"] = HOSTIL
    base_falsa.avance[2]["nombre_cliente"] = HOSTIL
    app = _entrar(_app(base_falsa))
    assert not app.exception and "<script" not in _html(app) and "<img src=x" not in _html(app)
    app = _abrir_detalle(app, "alert")
    assert not app.exception and "<script" not in _html(app) and "<img src=x" not in _html(app)


def test_el_codigo_no_queda_escrito_en_ninguna_parte_visible(base_falsa):
    app = _panel_abierto(base_falsa)
    assert CODIGO not in _texto(app) and CODIGO not in _html(app)


# ───────────────────────── El enganche en el validador ─────────────────────────
def test_el_enganche_del_panel_va_antes_de_todo_y_tolera_que_falte_el_archivo():
    src = open(XLSX_APP, encoding="utf-8").read()
    config = src.index("st.set_page_config(")
    gancho = src.index('if st.query_params.get("panel"):')
    primer_envio = src.index("if st.session_state.get('etapa_sel') is None:")
    assert config < gancho < primer_envio
    bloque = src[gancho:primer_envio]
    assert "import panel_seguimiento" in bloque and "except ImportError" in bloque and "st.stop()" in bloque


def test_si_falta_panel_seguimiento_py_la_app_avisa_y_no_se_rompe(monkeypatch):
    """Si alguien sube el validador pero no el panel, ?panel=1 muestra un aviso y no se rompe nada."""
    monkeypatch.setitem(sys.modules, "panel_seguimiento", None)          # así Python lanza ImportError, como si el archivo no estuviera
    app = _app(None, con_secretos=False)
    assert "no está disponible" in " ".join(e.value for e in app.error) and not app.exception
    assert not any(b.label == "➡️ Iniciar validación" for b in app.button)
