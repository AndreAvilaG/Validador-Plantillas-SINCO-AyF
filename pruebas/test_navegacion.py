"""Pruebas de la navegación entre etapas y del reinicio de la consulta.

Qué se protege:
  * «Volver al inicio» y «Nueva Consulta» empiezan una consulta LIMPIA (antes, al volver a la Etapa 1 seguían el nombre y el NIT
    de la empresa anterior, y las Etapas 1 a 3 no reiniciaban nada).
  * «Nueva Consulta» existe en las Etapas 1 a 3 (en la 4 ya existía).
  * «← Anterior» (dentro de los asistentes) CONSERVA lo digitado.
  * Hay una sola función de reinicio, y los campos con datos de la consulta llevan el contador de reinicios en su llave.
  * La barra de desplazamiento del menú azul es azul grisácea (no ámbar) y se define en un solo lugar.

Cómo correrlas (desde la raíz del repositorio):  pip install pytest   y luego   pytest pruebas
Los datos son inventados: no se deben agregar archivos de clientes a este repositorio.
"""
import ast
import io
import os
import re

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ETAPA_1 = "Etapa 1 — Maestro de Cuentas, Terceros y C. Costos"
ETAPA_2 = "Etapa 2 — Saldos CxC / CxP"
ETAPA_3 = "Etapa 3 — SI y Movimientos"


def _leer(archivo):
    return open(os.path.join(RAIZ, archivo), encoding="utf-8").read()


def _xlsx_pequeno():
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["dato"])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _app():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(os.path.join(RAIZ, "validador_sinco_ayf.py"), default_timeout=180)
    app.run()
    return app


def _boton(app, texto=None, llave=None):
    return next(b for b in app.button if (texto and b.label == texto) or (llave and b.key == llave))


def _con_llave(elementos, base):
    """El elemento cuya llave es `base` o `base_<contador>` (los campos de una consulta llevan el contador de reinicios)."""
    return next(e for e in elementos if e.key == base or e.key.startswith(base + "_"))


def _entrar(app, etapa):
    if etapa == ETAPA_1:
        _boton(app, "➡️ Iniciar validación").click().run()
        return
    codigo, boton = {ETAPA_2: ("codigo_e2", "➡️ Validar CxC / CxP"), ETAPA_3: ("codigo_e3", "➡️ Validar Saldos")}[etapa]
    _con_llave(app.text_input, codigo).set_value({"codigo_e2": "SINCO2", "codigo_e3": "SINCO3"}[codigo]).run()
    _boton(app, boton).click().run()


# ───────────────────────────── «Volver al inicio» reinicia la consulta ─────────────────────────────
def test_volver_al_inicio_deja_vacios_el_nombre_y_el_nit_de_la_etapa_1():
    """Regresión: el nombre y el NIT no tenían llave y sobrevivían al «Volver al inicio»."""
    app = _app()
    _entrar(app, ETAPA_1)
    _con_llave(app.text_input, "nombre_empresa").set_value("EMPRESA ANTERIOR S.A.S.").run()
    _con_llave(app.text_input, "nit_empresa").set_value("900123456").run()
    _boton(app, "← Volver al inicio").click().run()
    assert app.session_state["etapa_sel"] is None
    _entrar(app, ETAPA_1)
    assert _con_llave(app.text_input, "nombre_empresa").value == ""
    assert _con_llave(app.text_input, "nit_empresa").value == ""


def test_volver_al_inicio_borra_el_estado_de_la_consulta_y_conserva_lo_permanente():
    app = _app()
    _entrar(app, ETAPA_1)
    app.session_state["asistente_cc_datos"] = {"respuesta": "de la consulta anterior"}       # estado propio de un asistente
    app.session_state["e2_validar_click"] = True
    app.session_state["_seg_estado"] = {"pausa_hasta": 123}                                    # control del seguimiento (permanente)
    contador = app.session_state["_upload_counter"] if "_upload_counter" in app.session_state else 0
    _boton(app, "← Volver al inicio").click().run()
    assert "asistente_cc_datos" not in app.session_state
    assert "e2_validar_click" not in app.session_state
    assert app.session_state["_seg_estado"] == {"pausa_hasta": 123}
    assert app.session_state["_upload_counter"] == contador + 1


# ───────────────────────────── «Nueva Consulta» en las Etapas 1, 2 y 3 ─────────────────────────────
@pytest.mark.parametrize("etapa", [ETAPA_1, ETAPA_2, ETAPA_3])
def test_la_nueva_consulta_existe_y_deja_la_misma_etapa(etapa):
    """Regresión: solo la Etapa 4 tenía el botón."""
    app = _app()
    _entrar(app, etapa)
    boton = _boton(app, llave="nueva_consulta_sb")
    assert boton.label == "🔄 Nueva Consulta"                                      # mismo texto que el de la Etapa 4
    boton.click().run()
    assert app.session_state["etapa_sel"] == etapa                                 # no vuelve al inicio: sigue en la etapa
    assert not app.exception, [str(e.value) for e in app.exception]


def test_la_nueva_consulta_de_la_etapa_1_limpia_nombre_nit_y_vuelve_al_modo_inicial():
    app = _app()
    _entrar(app, ETAPA_1)
    _con_llave(app.text_input, "nombre_empresa").set_value("EMPRESA ANTERIOR").run()
    _con_llave(app.text_input, "nit_empresa").set_value("900123456").run()
    _con_llave(app.radio, "e1_modo_sel").set_value([o for o in _con_llave(app.radio, "e1_modo_sel").options if "Centro de Costos" in o][0]).run()
    _boton(app, llave="nueva_consulta_sb").click().run()
    assert _con_llave(app.text_input, "nombre_empresa").value == ""
    assert _con_llave(app.text_input, "nit_empresa").value == ""
    assert "Ya tengo mis plantillas" in _con_llave(app.radio, "e1_modo_sel").value      # el modo vuelve al inicial


def test_la_nueva_consulta_de_la_etapa_3_limpia_cargadores_y_casillas():
    app = _app()
    _entrar(app, ETAPA_3)
    _con_llave(app.file_uploader, "e3_puc_principal").set_value([("a.xlsx", _xlsx_pequeno(), XLSX)]).run()
    _con_llave(app.checkbox, "sb_fiscal").set_value(True).run()
    assert _con_llave(app.file_uploader, "e3_puc_principal").value
    _boton(app, llave="nueva_consulta_sb").click().run()
    assert not any(f.value for f in app.file_uploader)
    assert _con_llave(app.checkbox, "sb_fiscal").value is False


def test_dos_consultas_seguidas_sin_recargar():
    app = _app()
    for i in (1, 2, 3):
        _entrar(app, ETAPA_1)
        _con_llave(app.text_input, "nombre_empresa").set_value(f"EMPRESA {i}").run()
        assert _con_llave(app.text_input, "nombre_empresa").value == f"EMPRESA {i}"
        _boton(app, llave="nueva_consulta_sb").click().run()
        assert _con_llave(app.text_input, "nombre_empresa").value == ""
        _boton(app, "← Volver al inicio").click().run()
    assert app.session_state["_upload_counter"] == 6                               # 3 vueltas × (nueva consulta + volver)


def test_las_llaves_de_los_cargadores_cambian_con_cada_reinicio():
    """Streamlit conserva el valor de un campo mientras su llave no cambie: por eso las llaves llevan el contador."""
    app = _app()
    _entrar(app, ETAPA_1)
    antes = sorted(f.key for f in app.file_uploader)
    _boton(app, llave="nueva_consulta_sb").click().run()
    despues = sorted(f.key for f in app.file_uploader)
    assert antes and despues and not set(antes) & set(despues)


# ───────────────────────────── «← Anterior» conserva lo digitado ─────────────────────────────
def test_anterior_en_el_asistente_conserva_lo_digitado():
    """«Volver» (← Anterior) conserva los datos de la consulta en curso; «Nueva Consulta» es lo que los borra."""
    app = _app()
    _entrar(app, ETAPA_1)
    radio = _con_llave(app.radio, "e1_modo_sel")
    radio.set_value([o for o in radio.options if "Centro de Costos" in o][0]).run()
    next(t for t in app.text_input if t.key == "acc_sucursal_admin").set_value("5").run()
    _boton(app, llave="asistente_cc_next").click().run()
    _boton(app, llave="asistente_cc_prev").click().run()
    assert next(t for t in app.text_input if t.key == "acc_sucursal_admin").value == "5"
    _boton(app, llave="nueva_consulta_sb").click().run()
    radio = _con_llave(app.radio, "e1_modo_sel")
    radio.set_value([o for o in radio.options if "Centro de Costos" in o][0]).run()
    assert next(t for t in app.text_input if t.key == "acc_sucursal_admin").value == "0"      # valor inicial


# ───────────────────────────── Una sola implementación del reinicio ─────────────────────────────
def _funcion(archivo, nombre):
    src = _leer(archivo)
    nodo = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == nombre)
    return ast.get_source_segment(src, nodo)


def test_hay_una_sola_funcion_que_borra_el_estado_de_la_consulta():
    """Antes estaba copiada 4 veces. Ahora vive en _reiniciar_consulta; conciliacion.py solo tiene una red de seguridad
    para cuando se sube con un validador de otra versión."""
    # Reinicio COMPLETO = borrar todas las claves, sin filtro. (Los «Empezar de nuevo» de los asistentes borran solo las claves
    # de ese asistente, por prefijo, y se quedan en él: son otra cosa y no cuentan aquí.)
    borrado_total = r"for (k|key) in list\(st\.session_state\.keys\(\)\):\s*\n\s*del st\.session_state\[\1\]"
    assert len(re.findall(borrado_total, _leer("validador_sinco_ayf.py"))) == 1
    assert len(re.findall(borrado_total, _leer("conciliacion.py"))) == 1
    assert "del st.session_state" in _funcion("validador_sinco_ayf.py", "_reiniciar_consulta")
    assert "del st.session_state" in _funcion("conciliacion.py", "_reinicio_basico")
    assert "_volver_inicio_desde_e4" not in _leer("validador_sinco_ayf.py")


def test_ningun_boton_de_salida_cambia_de_pantalla_sin_reiniciar():
    """«Volver al inicio» y «Cerrar etapa» deben usar _reiniciar_consulta; _cambiar_etapa(None) solo cambiaba de pantalla."""
    src = _leer("validador_sinco_ayf.py")
    assert not re.search(r"_cambiar_etapa,\s*args=\(None,\)", src)
    assert not re.search(r"on_click=_cambiar_etapa,\s*args=\(None,\)", src)


def test_los_botones_de_la_etapa_4_usan_el_reinicio_unico():
    src = _leer("conciliacion.py")
    assert src.count("on_click=_reiniciar, args=(ETAPA4,)") == 2             # «Nueva Consulta» (menú y fin de resultados)
    assert src.count("on_click=_reiniciar, args=(None,)") == 1               # «Volver al inicio»
    assert "reiniciar_consulta=None" in _funcion("conciliacion.py", "render_etapa4").splitlines()[0]
    assert "_reiniciar_consulta" in _leer("validador_sinco_ayf.py")


def test_todo_cargador_y_campo_con_datos_de_la_consulta_lleva_el_contador_en_la_llave():
    src = _leer("validador_sinco_ayf.py")
    # los 22 cargadores del validador
    cargadores = re.findall(r"file_uploader\([^\n]*?key=([^,)\n]+)", src)
    assert len(cargadores) == 22
    assert all(c.startswith("_kup(") for c in cargadores), [c for c in cargadores if not c.startswith("_kup(")]
    for llave in ("nombre_empresa", "nit_empresa", "e1_modo_sel", "e2_fecha_corte", "sb_principal", "sb_fiscal", "sb_nif"):
        assert f"_kup('{llave}')" in src, llave
    # las tres lecturas por llave deben usar la misma llave con contador
    assert "st.session_state.get(_kup(k))" in src
    assert 'st.session_state.get(_kup(f"e3_{p}_{b.lower()}"))' in src


# ───────────────────────────── Barra de desplazamiento del menú azul ─────────────────────────────
def test_la_barra_de_desplazamiento_es_azul_grisacea_y_se_define_en_un_solo_lugar():
    """Regresión: era ámbar (#F5A623). Una sola regla (scrollbar-color) y su respaldo para navegadores antiguos."""
    src = _leer("validador_sinco_ayf.py")
    for ambar in ("F5A623", "FFC857", "0F2347"):
        assert ambar not in src, f"quedó el color anterior {ambar}"
    assert len(re.findall(r"scrollbar-color:", src)) == 2                    # 1 regla real + la consulta @supports
    assert "scrollbar-color:#7E96B8 #142C54" in src                          # indicador azul grisáceo sobre riel más oscuro
    assert src.count("#9AB0CF") == 1                                         # hover (respaldo): un tono más claro
    assert "scrollbar" not in _leer("conciliacion.py")                       # la Etapa 4 hereda la misma barra del menú
