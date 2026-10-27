"""Pruebas del panel de seguimiento para directores.

Qué se protege:
  * La lógica: agrupar por empresa, promediar por etapa, y OCULTAR los rebotes (caídas que se revierten en menos de un minuto; caso real:
    PROMOTORA BELONG, 91,67 → 16,67 → 91,67 en 8 segundos).
  * La seguridad: el código se guarda cifrado, 5 intentos fallidos bloquean 10 minutos, y el público (llave pública) NO puede leer las tablas
    ni llamar a las funciones internas. Estas pruebas necesitan una base PostgreSQL (variable SEGUIMIENTO_PG_DSN y psycopg2); sin ella se omiten.
  * La pantalla: solo se abre con ?panel=1, exige el código, muestra empresas, detalle e historial; y la app normal queda igual.

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


def _iso(d):
    return d.isoformat()


def _fila(nit="901652178", nombre="PROMOTORA BELONG S.A.S.", etapa=4, plantilla="Conciliación Cuentas por Pagar", cumplimiento=91.67,
          estado="requiere_correcciones", error=1, filas=12, adv=0, pendientes=None, hace=timedelta(hours=3)):
    return {"nit": nit, "nombre_cliente": nombre, "etapa": etapa, "plantilla": plantilla, "cumplimiento": cumplimiento, "estado": estado,
            "filas_evaluadas": filas, "filas_con_error": error, "errores_globales": 0, "advertencias": adv, "pendientes": pendientes or [],
            "actualizado_en": _iso(datetime.now(timezone.utc) - hace)}


# ───────────────────────── Ocultar los rebotes ─────────────────────────
def _h(antes, ahora, hora, plantilla="Conciliación Cuentas por Pagar", etapa=4):
    return {"etapa": etapa, "plantilla": plantilla, "cumplimiento_antes": antes, "cumplimiento": ahora, "estado": "requiere_correcciones",
            "registrado_en": f"2026-10-26T{hora}+00:00"}


def test_el_caso_real_de_promotora_belong_deja_solo_el_cambio_verdadero():
    """Las filas 75 a 79 de la base: tres de ellas son el rebote de 8 segundos (Por Pagar) y dos el de Por Cobrar."""
    historial = [
        _h(16.67, 91.67, "14:15:58.841239"),
        _h(84.00, 48.00, "14:52:17.913593", "Conciliación Cuentas por Cobrar"),
        _h(91.67, 16.67, "14:52:18.401816"),
        _h(48.00, 84.00, "14:52:26.694913", "Conciliación Cuentas por Cobrar"),
        _h(16.67, 91.67, "14:52:26.965493"),
    ]
    visibles, ocultas = panel.colapsar_rebotes(historial)
    assert [(f["plantilla"], f["cumplimiento"]) for f in visibles] == [("Conciliación Cuentas por Pagar", 91.67)]
    assert ocultas == 4


def test_un_cambio_que_se_revierte_despues_de_un_minuto_si_cuenta():
    visibles, ocultas = panel.colapsar_rebotes([_h(80, 40, "10:00:00"), _h(40, 80, "10:01:30")])
    assert len(visibles) == 2 and ocultas == 0


def test_un_cambio_que_no_se_revierte_si_cuenta():
    visibles, ocultas = panel.colapsar_rebotes([_h(80, 40, "10:00:00"), _h(40, 55, "10:00:10")])
    assert len(visibles) == 2 and ocultas == 0


def test_los_rebotes_de_plantillas_distintas_no_se_mezclan():
    visibles, ocultas = panel.colapsar_rebotes([_h(80, 40, "10:00:00", "Terceros", 1), _h(40, 80, "10:00:05", "Centros de Costos", 1)])
    assert len(visibles) == 2 and ocultas == 0


def test_tres_cambios_seguidos_dejan_el_ultimo():
    """10→20, 20→10, 10→20 en segundos: el resultado final (20) es el que queda."""
    visibles, ocultas = panel.colapsar_rebotes([_h(10, 20, "10:00:00"), _h(20, 10, "10:00:05"), _h(10, 20, "10:00:10")])
    assert [(f["cumplimiento_antes"], f["cumplimiento"]) for f in visibles] == [(10, 20)] and ocultas == 2


def test_el_historial_sale_de_la_fila_mas_reciente_a_la_mas_antigua_y_tolera_datos_malos():
    visibles, _ = panel.colapsar_rebotes([_h(None, 50, "09:00:00"), _h(50, 70, "11:00:00"), {"registrado_en": "no es fecha"}, {}])
    assert [f["cumplimiento"] for f in visibles] == [70, 50]
    assert panel.colapsar_rebotes(None) == ([], 0)


# ───────────────────────── Agrupar por empresa ─────────────────────────
def test_cada_etapa_es_el_promedio_de_sus_plantillas_y_no_hay_porcentaje_general():
    empresas = panel.agrupar_empresas([
        _fila(etapa=1, plantilla="PUC Principal", cumplimiento=100, estado="completado", error=0),
        _fila(etapa=1, plantilla="Terceros", cumplimiento=50, error=6),
        _fila(etapa=4, plantilla="Conciliación Cuentas por Pagar", cumplimiento=80),
    ])
    assert len(empresas) == 1
    e = empresas[0]
    assert e["etapas"] == {1: 75.0, 2: None, 3: None, 4: 80.0}            # None: la etapa no se ha iniciado
    assert e["plantillas"] == 3 and e["al_dia"] is False
    assert "general" not in " ".join(e)                                    # a propósito: no se sabe cuántas plantillas necesita cada empresa


def test_una_empresa_esta_al_dia_solo_si_todo_lo_validado_esta_completo():
    todas = [_fila(plantilla="A", cumplimiento=100, estado="completado"), _fila(plantilla="B", cumplimiento=100, estado="completado")]
    assert panel.agrupar_empresas(todas)[0]["al_dia"] is True
    assert panel.agrupar_empresas(todas + [_fila(plantilla="C", cumplimiento=99, estado="requiere_correcciones")])[0]["al_dia"] is False


def test_el_nombre_es_el_de_la_validacion_mas_reciente_y_las_empresas_van_de_la_mas_reciente_a_la_mas_antigua():
    empresas = panel.agrupar_empresas([
        _fila(nit="111111", nombre="NOMBRE VIEJO", plantilla="A", hace=timedelta(days=5)),
        _fila(nit="111111", nombre="NOMBRE NUEVO S.A.S.", plantilla="B", hace=timedelta(hours=1)),
        _fila(nit="222222", nombre="OTRA EMPRESA", hace=timedelta(days=2)),
    ])
    assert [(e["nit"], e["nombre"]) for e in empresas] == [("111111", "NOMBRE NUEVO S.A.S."), ("222222", "OTRA EMPRESA")]


def test_filas_sin_nit_se_ignoran_y_los_numeros_como_texto_se_entienden():
    empresas = panel.agrupar_empresas([{"nit": "", "etapa": 1}, _fila(etapa=2, cumplimiento="72.5"), {}])
    assert len(empresas) == 1 and empresas[0]["etapas"][2] == 72.5
    assert panel.agrupar_empresas(None) == []


def test_metricas():
    ahora = datetime.now(timezone.utc)
    empresas = panel.agrupar_empresas([
        _fila(nit="1", nombre="A", cumplimiento=100, estado="completado", hace=timedelta(hours=1)),
        _fila(nit="2", nombre="B", hace=timedelta(hours=5)),
        _fila(nit="3", nombre="C", hace=timedelta(hours=40)),
    ])
    assert panel.metricas(empresas, ahora) == {"empresas": 3, "al_dia": 1, "con_correcciones": 2, "activas_24h": 2}


def test_la_busqueda_encuentra_por_nombre_y_por_nit_con_o_sin_puntos():
    empresas = panel.agrupar_empresas([_fila(nit="901652178", nombre="PROMOTORA BELONG S.A.S."), _fila(nit="830123456", nombre="Operadora Ferrocarril")])
    assert [e["nit"] for e in panel.filtrar_empresas(empresas, "belong")] == ["901652178"]
    assert [e["nit"] for e in panel.filtrar_empresas(empresas, "FERROCARRIL")] == ["830123456"]
    assert [e["nit"] for e in panel.filtrar_empresas(empresas, "901.652.178")] == ["901652178"]
    assert len(panel.filtrar_empresas(empresas, "")) == 2 and panel.filtrar_empresas(empresas, "no existe") == []


def test_los_pendientes_van_de_mas_a_menos_casos_y_ignoran_lo_que_no_es_un_pendiente():
    p = [{"plantilla": "Terceros", "pendientes": [{"categoria": "Banco no válido", "columna": "Banco", "casos": 3}, "basura",
                                                 {"categoria": "Ciudad", "columna": "TerCiudad", "casos": 40}]}]
    assert [f["casos"] for f in panel.pendientes_de(p)] == [40, 3]


def test_porcentaje_en_texto_y_la_primera_validacion_no_tiene_antes():
    assert panel.porcentaje_texto(91.67) == "91.7%" and panel.porcentaje_texto(99.9) == "99.9%" and panel.porcentaje_texto(100) == "100.0%"
    assert panel.porcentaje_texto(None) == "—" and panel.porcentaje_texto("") == "—" and panel.porcentaje_texto("no es número") == "—"


def test_formatos():
    assert panel.hora_colombia(panel.fecha_utc("2026-10-27T00:01:44.060692+00:00")) == datetime(2026, 10, 26, 19, 1, 44, 60692)    # UTC−5
    assert panel.hora_colombia(None) is None and panel.fecha_utc("no es fecha") is None and panel.fecha_utc(None) is None
    assert panel.miles(7822) == "7.822" and panel.miles(12) == "12" and panel.miles(None) == "—"


def test_configuracion():
    assert panel.leer_configuracion({"url": "https://x.supabase.co", "clave_publica": "sb_publishable_x"}) == ("https://x.supabase.co", "sb_publishable_x")
    assert panel.leer_configuracion({"activo": False, "url": "https://x.co", "clave_publica": "k"}) == ("https://x.co", "k")   # no depende de 'activo'
    for malo in (None, {}, {"url": "https://x.co"}, {"clave_publica": "k"}, {"url": "ftp://x.co", "clave_publica": "k"}, {"url": "file:///x", "clave_publica": "k"}):
        assert panel.leer_configuracion(malo) is None


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
    base_falsa.avance = [_fila()]
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
    assert time.time() - t0 < panel.TIMEOUT_SEG + 2 and e.value.tipo == "sin_conexion"
    assert e.value.tipo in panel.MENSAJES_ERROR                                # el usuario ve un mensaje claro, no el error técnico


# ───────────────────────── La base de datos: código, bloqueo y permisos ─────────────────────────
DSN = os.environ.get("SEGUIMIENTO_PG_DSN")
requiere_base = pytest.mark.skipif(not DSN, reason="define SEGUIMIENTO_PG_DSN para probar contra una base PostgreSQL")


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
        ruta = os.path.join(RAIZ, archivo)
        if not os.path.exists(ruta):
            ruta = os.path.join(RAIZ, "..", archivo)
        c.execute(open(ruta, encoding="utf-8").read())
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


def _avance(conexion, nit="901652178", nombre="PROMOTORA BELONG S.A.S.", etapa=4, plantilla="Conciliación Cuentas por Pagar"):
    conexion.cursor().execute(
        """insert into public.avance_actual (nit, etapa, plantilla, nombre_cliente, fuente_nit, filas_evaluadas, filas_con_error, cumplimiento, estado, pendientes)
           values (%s, %s, %s, %s, 'informe', 12, 1, 91.67, 'requiere_correcciones', '[{"categoria": "X", "columna": "Y", "casos": 1}]')""",
        (nit, etapa, plantilla, nombre))


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
    _avance(pg)
    pg.cursor().execute("insert into public.historial_validaciones (nit, etapa, plantilla) values ('SIN-IDENTIFICAR', 1, 'Terceros'), ('SIN-IDENTIFICAR', 1, 'Terceros')")
    r = _resumen(pg, CODIGO)
    assert r["ok"] is True and "generado_en" in r
    assert len(r["avance"]) == 1 and r["avance"][0]["nombre_cliente"] == "PROMOTORA BELONG S.A.S."
    assert r["avance"][0]["pendientes"] == [{"categoria": "X", "columna": "Y", "casos": 1}]
    assert [(s["etapa"], s["plantilla"], s["usos"]) for s in r["sin_identificar"]] == [(1, "Terceros", 2)]


@requiere_base
def test_la_respuesta_solo_trae_las_columnas_esperadas(pg):
    _avance(pg)
    fila = _resumen(pg, CODIGO)["avance"][0]
    assert set(fila) == {"nit", "nombre_cliente", "etapa", "plantilla", "cumplimiento", "estado", "filas_evaluadas", "filas_con_error",
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
def test_el_publico_si_puede_llamar_a_las_dos_lecturas_y_a_nada_mas_de_esta_fase(pg):
    assert _anon(pg, "select public.panel_resumen(%s)", (CODIGO,))[0][0]["ok"] is True
    assert _anon(pg, "select public.panel_historial(%s, %s)", (CODIGO, "901652178"))[0][0]["ok"] is True


@requiere_base
def test_el_historial_de_una_empresa_trae_lo_suyo_y_nada_de_otras(pg):
    c = pg.cursor()
    c.execute("""insert into public.historial_validaciones (nit, nombre_cliente, etapa, plantilla, cumplimiento_antes, cumplimiento, estado)
                 values ('901652178', 'BELONG', 4, 'P', null, 50, 'requiere_correcciones'), ('901652178', 'BELONG', 4, 'P', 50, 80, 'requiere_correcciones'),
                        ('830123456', 'OTRA', 1, 'T', null, 100, 'completado')""")
    r = _anon(pg, "select public.panel_historial(%s, %s)", (CODIGO, "901652178"))[0][0]
    assert r["ok"] and [f["cumplimiento"] for f in r["historial"]] == [80, 50]          # la más reciente primero


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
    ruta = os.path.join(RAIZ, "seguimiento_supabase_fase2_panel.sql")
    if not os.path.exists(ruta):
        ruta = os.path.join(RAIZ, "..", "seguimiento_supabase_fase2_panel.sql")
    pg.cursor().execute(open(ruta, encoding="utf-8").read())
    assert len(_resumen(pg, CODIGO)["avance"]) == 1


# ───────────────────────── La pantalla ─────────────────────────
XLSX_APP = os.path.join(RAIZ, "validador_sinco_ayf.py")


def _demo(base):
    ahora = datetime.now(timezone.utc)
    base.avance = [
        _fila(nit="901652178", nombre="PROMOTORA BELONG S.A.S.", etapa=4, plantilla="Conciliación Cuentas por Pagar", cumplimiento=91.67, hace=timedelta(hours=3),
              pendientes=[{"categoria": "Diferencia de valor", "columna": "Conciliación", "casos": 1}]),
        _fila(nit="901652178", nombre="PROMOTORA BELONG S.A.S.", etapa=4, plantilla="Conciliación Cuentas por Cobrar", cumplimiento=84.0, error=2, hace=timedelta(hours=3)),
        _fila(nit="901938545", nombre="OPERADORA FERROCARRIL CENTRAL S.A.S.", etapa=4, plantilla="Conciliación Cuentas por Cobrar", cumplimiento=0.0, error=12, hace=timedelta(hours=40)),
        _fila(nit="830123456", nombre="Empresa al día S.A.S.", etapa=1, plantilla="Terceros", cumplimiento=100, estado="completado", error=0, filas=7822, hace=timedelta(hours=1)),
        _fila(nit="830123456", nombre="Empresa al día S.A.S.", etapa=1, plantilla="PUC Principal", cumplimiento=100, estado="completado", error=0, hace=timedelta(hours=1)),
    ]
    base.sin = [{"etapa": 1, "plantilla": "Terceros", "usos": 3, "ultimo_uso": _iso(ahora - timedelta(hours=2))}]
    base.historial = {"901652178": [
        _h(16.67, 91.67, "14:15:58.841239"), _h(84.0, 48.0, "14:52:17.913593", "Conciliación Cuentas por Cobrar"), _h(91.67, 16.67, "14:52:18.401816"),
        _h(48.0, 84.0, "14:52:26.694913", "Conciliación Cuentas por Cobrar"), _h(16.67, 91.67, "14:52:26.965493")][::-1]}


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


def _texto(app):
    return " ".join([*(m.value for m in app.markdown), *(e.value for e in app.error), *(w.value for w in app.warning),
                     *(i.value for i in app.info), *(c.value for c in app.caption)])


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
    assert "El código no es correcto" in _texto(app) and not app.dataframe and not app.exception


def test_codigo_vacio_no_consulta_nada(base_falsa):
    app = _entrar(_app(base_falsa), "   ")
    assert "Escribe el código" in _texto(app) and not base_falsa.llamadas


@pytest.mark.parametrize("modo,mensaje", [("bloqueado", "Espera 10 minutos"), ("caido", "No se pudo consultar"), ("basura", "No se pudo consultar")])
def test_los_fallos_se_explican_sin_mostrar_datos_tecnicos(base_falsa, modo, mensaje):
    base_falsa.modo = modo
    app = _entrar(_app(base_falsa))
    assert mensaje in _texto(app) and not app.dataframe and not app.exception
    assert "HTTP" not in _texto(app) and "Traceback" not in _texto(app)


def test_con_el_codigo_correcto_se_ven_las_empresas_y_los_numeros(base_falsa):
    _demo(base_falsa)
    app = _entrar(_app(base_falsa))
    assert not app.exception
    metricas = {m.label: m.value for m in app.metric}
    assert metricas == {"Empresas con actividad": "3", "Al día (todo completado)": "1", "Con correcciones pendientes": "2", "Actividad en las últimas 24 h": "2"}
    tabla = app.dataframe[0].value
    assert list(tabla["Empresa"]) == ["Empresa al día S.A.S.", "PROMOTORA BELONG S.A.S.", "OPERADORA FERROCARRIL CENTRAL S.A.S."]   # la más reciente primero
    belong = tabla[tabla["NIT"] == "901652178"].iloc[0]
    assert belong["Estado"].endswith("Con correcciones") and round(belong["Etapa 4"], 1) == 87.8   # promedio de 91,67 y 84
    import pandas as pd
    assert pd.isna(belong["Etapa 1"]) and pd.isna(belong["Etapa 2"])             # etapas sin iniciar: vacías (no 0)
    assert tabla[tabla["NIT"] == "830123456"].iloc[0]["Etapa 1"] == 100.0       # la empresa al día: su etapa 1 completa
    assert tabla[tabla["NIT"] == "830123456"].iloc[0]["Estado"].endswith("Al día")


def test_el_detalle_muestra_plantillas_pendientes_e_historial_sin_rebotes(base_falsa):
    _demo(base_falsa)
    app = _entrar(_app(base_falsa))
    next(s for s in app.selectbox if s.key == "panel_empresa").select("PROMOTORA BELONG S.A.S. — NIT 901652178").run()
    assert not app.exception
    plantillas = next(d.value for d in app.dataframe if "Filas con error" in d.value.columns)
    assert sorted(plantillas["Plantilla"]) == ["Conciliación Cuentas por Cobrar", "Conciliación Cuentas por Pagar"]
    assert "1 de 12" in list(plantillas["Filas con error"])
    pendientes = next(d.value for d in app.dataframe if "Qué falta" in d.value.columns)
    assert list(pendientes["Qué falta"]) == ["Diferencia de valor"]
    historial = next(d.value for d in app.dataframe if "Antes" in d.value.columns)
    assert len(historial) == 1 and historial.iloc[0]["Ahora"] == "91.7%" and historial.iloc[0]["Antes"] == "16.7%"   # los rebotes de 8 segundos no se ven
    assert "Se ocultaron 4 movimientos" in _texto(app)
    assert any(h[0].endswith("panel_historial") and h[1]["p_nit"] == "901652178" for h in base_falsa.llamadas)


def test_la_busqueda_filtra_la_tabla(base_falsa):
    _demo(base_falsa)
    app = _entrar(_app(base_falsa))
    next(t for t in app.text_input if t.key == "panel_buscar").set_value("ferrocarril").run()
    assert list(app.dataframe[0].value["Empresa"]) == ["OPERADORA FERROCARRIL CENTRAL S.A.S."]
    next(t for t in app.text_input if t.key == "panel_buscar").set_value("zzz").run()
    assert "Ninguna empresa coincide" in _texto(app) and not app.exception


def test_los_usos_sin_empresa_identificada_se_muestran_aparte(base_falsa):
    _demo(base_falsa)
    app = _entrar(_app(base_falsa))
    sin = next(d.value for d in app.dataframe if "Veces" in d.value.columns)
    assert list(sin["Veces"]) == [3] and list(sin["Plantilla"]) == ["Terceros"]
    assert len(app.dataframe[0].value) == 3                                  # y no cuentan como empresa


def test_actualizar_vuelve_a_pedir_los_datos_y_salir_vuelve_a_pedir_el_codigo(base_falsa):
    _demo(base_falsa)
    app = _entrar(_app(base_falsa))
    antes = len([h for h in base_falsa.llamadas if h[0].endswith("panel_resumen")])
    next(b for b in app.button if b.label == "🔄 Actualizar").click().run()
    assert len([h for h in base_falsa.llamadas if h[0].endswith("panel_resumen")]) == antes + 1
    next(b for b in app.button if b.label == "Salir").click().run()
    assert [c for c in app.text_input if (c.key or "") == "panel_codigo"] and not app.dataframe


def test_si_el_codigo_cambia_mientras_se_usa_el_panel_pide_entrar_de_nuevo(base_falsa):
    _demo(base_falsa)
    app = _entrar(_app(base_falsa))
    base_falsa.modo = "bloqueado"
    next(b for b in app.button if b.label == "🔄 Actualizar").click().run()
    assert [c for c in app.text_input if (c.key or "") == "panel_codigo"] and not app.dataframe
    assert "Espera 10 minutos" in _texto(app) and not app.exception


def test_un_nombre_de_empresa_con_html_no_se_inyecta(base_falsa):
    _demo(base_falsa)
    base_falsa.avance[0]["nombre_cliente"] = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
    app = _entrar(_app(base_falsa))
    assert not app.exception
    assert not any("<img" in m.value or "<script" in m.value for m in app.markdown)       # el nombre nunca va dentro de HTML propio


def test_el_codigo_no_queda_escrito_en_ninguna_parte_visible(base_falsa):
    _demo(base_falsa)
    app = _entrar(_app(base_falsa))
    assert CODIGO not in _texto(app)
    assert CODIGO not in " ".join(str(d.value) for d in app.dataframe)


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
