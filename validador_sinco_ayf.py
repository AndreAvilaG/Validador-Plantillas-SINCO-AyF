import streamlit as st
import pandas as pd
import re
from io import BytesIO
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Validador de Plantillas | SINCO A&F",
    page_icon="✅", layout="wide",
    initial_sidebar_state="expanded"
)

C_DARK   = "#1B3A6B"; C_MID = "#4A7FB5"; C_LIGHT = "#6B8FA8"
C_GREEN  = "#16A34A"; C_RED = "#DC2626"; C_ORANGE = "#D97706"
C_BG     = "#EFF6FF"; C_GRAY = "#F8FAFC"
C_YELLOW = "#CA8A04"; C_PURPLE = "#7C3AED"

st.markdown(f"""<style>
html,body,[class*="css"]{{font-family:'Segoe UI',sans-serif;}}
.main{{background:{C_GRAY};}}
[data-testid="stSidebar"]{{background:{C_DARK}!important;}}
[data-testid="stSidebar"] *{{color:white!important;}}
[data-testid="stSidebar"] label{{color:white!important;font-weight:600;font-size:13px;}}
[data-testid="stSidebar"] .stFileUploader{{background:transparent!important;border:none!important;padding:0!important;margin-bottom:12px!important;}}
[data-testid="stSidebar"] .stFileUploader section{{background:transparent!important;border:none!important;padding:0!important;}}
[data-testid="stSidebar"] .stFileUploader [data-testid="stFileUploaderDropzone"]{{
    background:white!important;border:2px solid {C_MID}!important;border-radius:10px!important;
    min-height:48px!important;max-height:48px!important;display:flex!important;
    align-items:center!important;justify-content:center!important;
    cursor:pointer!important;transition:all 0.2s ease!important;padding:0 16px!important;}}
[data-testid="stSidebar"] .stFileUploader [data-testid="stFileUploaderDropzone"]:hover{{
    background:{C_BG}!important;border-color:{C_DARK}!important;box-shadow:0 2px 8px rgba(27,58,107,0.2)!important;}}
[data-testid="stSidebar"] .stFileUploader [data-testid="stFileUploaderDropzoneInstructions"] span{{
    color:{C_DARK}!important;font-size:13px!important;font-weight:700!important;}}
[data-testid="stSidebar"] .stFileUploader [data-testid="stFileUploaderDropzoneInstructions"] small{{display:none!important;}}
[data-testid="stSidebar"] .stFileUploader svg{{fill:{C_MID}!important;color:{C_MID}!important;width:18px!important;height:18px!important;}}
[data-testid="stSidebar"] .stFileUploader [data-testid="stFileUploaderDropzone"] button{{display:none!important;}}
[data-testid="stSidebar"] .stFileUploader [data-testid="stFileUploaderFileData"]{{
    background:#F0FDF4!important;border:1.5px solid #16A34A!important;border-radius:10px!important;padding:8px 12px!important;}}
[data-testid="stSidebar"] .stFileUploader [data-testid="stFileUploaderFileData"] span{{color:#14532D!important;font-size:12px!important;font-weight:600!important;}}
[data-testid="stSidebar"] hr{{border-color:rgba(255,255,255,0.15)!important;}}
[data-testid="stSidebar"] h3{{color:#93C5FD!important;font-size:11px!important;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px!important;}}
[data-testid="stSidebar"] .stCheckbox label{{color:white!important;font-size:13px!important;}}
[data-testid="stSidebar"] .stSelectbox label{{color:white!important;}}
.header-box{{background:linear-gradient(135deg,{C_DARK} 0%,{C_MID} 100%);padding:20px 28px;border-radius:14px;margin-bottom:22px;display:flex;align-items:center;gap:20px;box-shadow:0 6px 24px rgba(27,58,107,0.3);}}
.header-box h1{{color:white;font-size:22px;font-weight:700;margin:0;}}
.header-box p{{color:#BFDBFE;font-size:12px;margin:4px 0 0 0;}}
.logo-divider{{width:1px;height:44px;background:rgba(255,255,255,0.25);margin:0 4px;}}
.seccion{{font-size:17px;font-weight:700;color:{C_DARK};border-left:6px solid {C_MID};padding:12px 18px;background:{C_BG};border-radius:0 10px 10px 0;margin:28px 0 16px 0;box-shadow:0 2px 8px rgba(74,127,181,0.12);}}
.card{{background:white;border-radius:12px;padding:18px 16px;box-shadow:0 2px 10px rgba(0,0,0,0.06);border-top:4px solid {C_MID};margin-bottom:12px;}}
.card.green{{border-top-color:{C_GREEN};}} .card.red{{border-top-color:{C_RED};}}
.card.orange{{border-top-color:{C_ORANGE};}} .card.blue{{border-top-color:{C_MID};}}
.card-label{{font-size:10px;color:#64748B;font-weight:700;text-transform:uppercase;letter-spacing:.8px;}}
.card-value{{font-size:24px;font-weight:700;color:#1E293B;margin:6px 0 2px 0;}}
.card-sub{{font-size:11px;color:#94A3B8;}}
.ok-box{{background:#F0FDF4;border:1px solid #BBF7D0;border-left:4px solid {C_GREEN};border-radius:8px;padding:13px 16px;margin:5px 0;font-size:13px;color:#14532D;line-height:1.5;}}
.err-box{{background:#FEF2F2;border:1px solid #FECACA;border-left:4px solid {C_RED};border-radius:8px;padding:10px 14px;margin:4px 0;font-size:13px;color:#7F1D1D;}}
.warn-box{{background:#FFFBEB;border:1px solid #FDE68A;border-left:4px solid {C_ORANGE};border-radius:8px;padding:11px 15px;margin:5px 0;font-size:13px;color:#78350F;}}
.info-box{{background:{C_BG};border:1px solid #BFDBFE;border-left:4px solid {C_MID};border-radius:8px;padding:13px 16px;margin:5px 0;font-size:13px;color:{C_DARK};line-height:1.6;}}
.inst{{background:{C_BG};border-left:4px solid {C_MID};border-radius:8px;padding:15px 18px;margin:14px 0;color:{C_DARK};font-size:13px;line-height:1.7;}}
.libro-badge{{display:inline-block;background:{C_MID};color:white;padding:3px 12px;border-radius:20px;font-size:11px;font-weight:700;margin-right:6px;}}
.libro-badge.fiscal{{background:{C_ORANGE};}}
.libro-badge.nif{{background:{C_PURPLE};}}
.paso-badge{{background:{C_DARK};color:white;border-radius:50%;width:28px;height:28px;display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;margin-right:10px;}}
.error-tag-formato{{background:#FEF9C3;color:{C_YELLOW};border:1px solid #FDE047;border-radius:4px;padding:1px 7px;font-size:10px;font-weight:700;}}
.error-tag-logica{{background:#F0FDF4;color:{C_GREEN};border:1px solid #86EFAC;border-radius:4px;padding:1px 7px;font-size:10px;font-weight:700;}}
.error-tag-general{{background:#F5F3FF;color:{C_PURPLE};border:1px solid #C4B5FD;border-radius:4px;padding:1px 7px;font-size:10px;font-weight:700;}}
.error-row{{background:white;border:1px solid #E2E8F0;border-radius:8px;padding:10px 14px;margin:4px 0;display:flex;gap:10px;align-items:flex-start;box-shadow:0 1px 4px rgba(0,0,0,0.05);}}
.stDownloadButton>button{{background:linear-gradient(135deg,{C_DARK},{C_MID})!important;color:white!important;border:none!important;border-radius:10px!important;padding:12px 24px!important;font-weight:600!important;width:100%!important;font-size:14px!important;box-shadow:0 4px 14px rgba(27,58,107,0.3)!important;}}
</style>""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def tiene_caracteres_especiales(v):
    return bool(re.search(r'[^0-9\s]', str(v).strip())) if str(v).strip() not in ('', 'nan', 'None') else False

def es_numerico(v):
    try: float(str(v).replace(',', '').strip()); return True
    except: return False

def es_fecha_valida(v):
    s = str(v).strip()
    if s in ('', 'nan', 'None'): return False
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%Y/%m/%d'):
        try: datetime.strptime(s.split(' ')[0], fmt); return True
        except: pass
    return False

def limpiar_nit(v):
    try: return str(int(float(str(v).replace(',','').strip().lstrip("'"))))
    except: return str(v).strip().lstrip("'")

def fmt_num(v):
    try: return f"{float(v):,.2f}"
    except: return str(v)

# ─────────────────────────────────────────────────────────────────────────────
# VALIDADORES
# ─────────────────────────────────────────────────────────────────────────────
def validar_saldos_iniciales(df, nits_validos=None):
    """Retorna lista de errores con (fila, columna, tipo, mensaje_simple, mensaje_tecnico)"""
    errores = []
    total_deb = 0.0
    total_cre = 0.0

    for idx, row in df.iterrows():
        fila = idx + 2  # +2 porque fila 1 es encabezado
        cuenta  = str(row.get('Cuenta Contable', '')).strip().lstrip("'")
        nit     = str(row.get('NIT', '')).strip().lstrip("'")
        cc      = str(row.get('Centro Costos', '')).strip().lstrip("'")
        debito  = row.get('Débito', '')
        credito = row.get('Crédito', '')

        # Saltar filas sin cuenta ni NIT (filas de totales o vacías)
        if cuenta in ('', 'nan', 'None') and nit in ('', 'nan', 'None'):
            continue

        # ── Cuenta Contable ──
        if cuenta in ('', 'nan', 'None'):
            errores.append((fila, 'Cuenta Contable', 'formato',
                '❌ La columna Cuenta Contable está vacía.',
                'Campo vacío — se espera código de cuenta auxiliar.'))
        elif tiene_caracteres_especiales(cuenta):
            errores.append((fila, 'Cuenta Contable', 'formato',
                f'❌ La Cuenta Contable "{cuenta}" tiene letras o símbolos. Solo se permiten números.',
                'Contiene caracteres especiales.'))
        elif not es_numerico(cuenta):
            errores.append((fila, 'Cuenta Contable', 'formato',
                f'❌ La Cuenta Contable "{cuenta}" no es un número válido.',
                'No numérico.'))

        # ── NIT ──
        if nit not in ('', 'nan', 'None') and nits_validos is not None:
            nit_limpio = limpiar_nit(nit)
            if nit_limpio not in nits_validos:
                errores.append((fila, 'NIT', 'logica',
                    f'⚠️ El NIT "{nit}" no está en el maestro de terceros. Verifique que esté bien escrito.',
                    'Tercero no registrado en el sistema.'))

        # ── Centro de Costos ──
        if cc not in ('', 'nan', 'None') and tiene_caracteres_especiales(cc):
            errores.append((fila, 'Centro Costos', 'formato',
                f'❌ El Centro de Costos "{cc}" tiene letras o símbolos. Solo se permiten números.',
                'Contiene caracteres especiales.'))

        # ── Débito ──
        deb_val = pd.to_numeric(str(debito).replace(',',''), errors='coerce')
        if pd.isna(deb_val):
            if str(debito).strip() in ('', 'nan', 'None'):
                errores.append((fila, 'Débito', 'formato',
                    '❌ La columna Débito está vacía. Ingrese 0 si no tiene valor.',
                    'Campo vacío — requerido.'))
            else:
                errores.append((fila, 'Débito', 'formato',
                    f'❌ El valor de Débito "{debito}" no es un número válido.',
                    'No es un valor decimal.'))
        else:
            total_deb += deb_val

        # ── Crédito ──
        cre_val = pd.to_numeric(str(credito).replace(',',''), errors='coerce')
        if pd.isna(cre_val):
            if str(credito).strip() in ('', 'nan', 'None'):
                errores.append((fila, 'Crédito', 'formato',
                    '❌ La columna Crédito está vacía. Ingrese 0 si no tiene valor.',
                    'Campo vacío — requerido.'))
            else:
                errores.append((fila, 'Crédito', 'formato',
                    f'❌ El valor de Crédito "{credito}" no es un número válido.',
                    'No es un valor decimal.'))
        else:
            total_cre += cre_val

    # ── Validación de balance Débitos = Créditos ──
    diferencia = round(total_deb - total_cre, 2)
    if abs(diferencia) > 0.01:
        errores.append((None, 'Balance', 'general',
            f'❌ La suma de Débitos (${fmt_num(total_deb)}) es diferente a la suma de Créditos (${fmt_num(total_cre)}). '
            f'La diferencia es ${fmt_num(diferencia)}. Revise los valores ingresados.',
            f'Sumatoria Débitos ≠ Créditos. Diferencia: {diferencia:,.2f}'))

    return errores, total_deb, total_cre


def validar_movimientos(df, nits_validos=None):
    errores = []
    consecutivos_vistos = {}

    for idx, row in df.iterrows():
        fila = idx + 2
        cuenta  = str(row.get('Cuenta Contable', '')).strip().lstrip("'")
        nit     = str(row.get('NIT', '')).strip().lstrip("'")
        cc      = str(row.get('Centro Costos', '')).strip().lstrip("'")
        fecha   = row.get('Fecha del documento', '')
        tipo_doc= str(row.get('Tipo documento', '')).strip()
        consec  = str(row.get('Consecutivo', '')).strip()
        debito  = row.get('Débito', '')
        credito = row.get('Crédito', '')
        sucursal= str(row.get('Sucursal', '')).strip()
        tasa    = row.get('Tasa de cambio', '')

        # Saltar filas sin cuenta (vacías o totales)
        if cuenta in ('', 'nan', 'None'):
            continue

        # ── Cuenta Contable ──
        if cuenta in ('', 'nan', 'None'):
            errores.append((fila, 'Cuenta Contable', 'formato',
                '❌ La columna Cuenta Contable está vacía.',
                'Campo vacío.'))
        elif tiene_caracteres_especiales(cuenta):
            errores.append((fila, 'Cuenta Contable', 'formato',
                f'❌ La Cuenta Contable "{cuenta}" tiene letras o símbolos. Solo se permiten números.',
                'Contiene caracteres especiales.'))
        elif not es_numerico(cuenta):
            errores.append((fila, 'Cuenta Contable', 'formato',
                f'❌ La Cuenta Contable "{cuenta}" no es un número válido.',
                'No numérico.'))

        # ── NIT ──
        if nit not in ('', 'nan', 'None') and nits_validos is not None:
            nit_limpio = limpiar_nit(nit)
            if nit_limpio not in nits_validos:
                errores.append((fila, 'NIT', 'logica',
                    f'⚠️ El NIT "{nit}" no está en el maestro de terceros.',
                    'Tercero no registrado.'))

        # ── Centro de Costos ──
        if cc not in ('', 'nan', 'None') and tiene_caracteres_especiales(cc):
            errores.append((fila, 'Centro Costos', 'formato',
                f'❌ El Centro de Costos "{cc}" tiene caracteres no permitidos.',
                'Contiene caracteres especiales.'))

        # ── Fecha ──
        if str(fecha).strip() in ('', 'nan', 'None'):
            errores.append((fila, 'Fecha del documento', 'formato',
                '❌ La Fecha del documento está vacía. Use el formato dd/mm/aaaa.',
                'Campo vacío.'))
        elif not es_fecha_valida(fecha):
            errores.append((fila, 'Fecha del documento', 'formato',
                f'❌ La fecha "{fecha}" no tiene el formato correcto. Use dd/mm/aaaa.',
                'Formato de fecha inválido.'))

        # ── Tipo documento ──
        if tipo_doc in ('', 'nan', 'None'):
            errores.append((fila, 'Tipo documento', 'formato',
                '❌ El Tipo de documento está vacío.',
                'Campo vacío.'))

        # ── Consecutivo ──
        if consec in ('', 'nan', 'None'):
            errores.append((fila, 'Consecutivo', 'formato',
                '❌ El Consecutivo está vacío.',
                'Campo vacío.'))
        else:
            try:
                c_int = int(float(consec))
                if c_int < 1 or c_int > 2147000000:
                    errores.append((fila, 'Consecutivo', 'formato',
                        f'❌ El Consecutivo {c_int} está fuera del rango permitido (1 a 2,147,000,000).',
                        'Fuera del rango 1 a 2147000000.'))
                elif str(consec).strip().startswith('0'):
                    errores.append((fila, 'Consecutivo', 'formato',
                        f'❌ El Consecutivo "{consec}" no puede empezar por 0.',
                        'Inicia con dígito 0.'))
                else:
                    clave = f"{tipo_doc}_{consec}"
                    if clave in consecutivos_vistos:
                        errores.append((fila, 'Consecutivo', 'formato',
                            f'❌ El Consecutivo {consec} para el tipo "{tipo_doc}" está repetido '
                            f'(también aparece en la fila {consecutivos_vistos[clave]}).',
                            'Consecutivo duplicado.'))
                    else:
                        consecutivos_vistos[clave] = fila
            except:
                errores.append((fila, 'Consecutivo', 'formato',
                    f'❌ El Consecutivo "{consec}" no es un número válido.',
                    'No es entero válido.'))

        # ── Débito ──
        deb_val = pd.to_numeric(str(debito).replace(',',''), errors='coerce')
        if pd.isna(deb_val):
            errores.append((fila, 'Débito', 'formato',
                '❌ El valor de Débito está vacío o no es un número.',
                'Campo vacío o no decimal.'))

        # ── Crédito ──
        cre_val = pd.to_numeric(str(credito).replace(',',''), errors='coerce')
        if pd.isna(cre_val):
            errores.append((fila, 'Crédito', 'formato',
                '❌ El valor de Crédito está vacío o no es un número.',
                'Campo vacío o no decimal.'))

        # ── Sucursal ──
        if sucursal in ('', 'nan', 'None'):
            errores.append((fila, 'Sucursal', 'formato',
                '❌ La Sucursal está vacía. Si no sabe cuál es, use 0 (principal).',
                'Campo vacío.'))
        elif tiene_caracteres_especiales(sucursal):
            errores.append((fila, 'Sucursal', 'formato',
                f'❌ La Sucursal "{sucursal}" tiene caracteres no permitidos. Solo se permiten números.',
                'Contiene caracteres especiales.'))
        elif not es_numerico(sucursal):
            errores.append((fila, 'Sucursal', 'formato',
                f'❌ La Sucursal "{sucursal}" no es un número válido.',
                'No numérico.'))

        # ── Tasa de cambio ──
        if str(tasa).strip() not in ('', 'nan', 'None', '0'):
            tasa_val = pd.to_numeric(str(tasa).replace(',',''), errors='coerce')
            if pd.isna(tasa_val):
                errores.append((fila, 'Tasa de cambio', 'formato',
                    f'❌ La Tasa de cambio "{tasa}" no es un número válido.',
                    'No es un valor decimal.'))

    # Advertencias del sistema
    advertencias = [
        '⚠️ El sistema verificará al importar: que el Tipo de documento esté registrado.',
        '⚠️ El sistema verificará al importar: que la Cuenta Contable sea tipo auxiliar.',
        '⚠️ El sistema verificará al importar: que los Consecutivos no estén ya registrados.',
        '⚠️ El sistema verificará al importar: que la Sucursal sea administrativa.',
    ]

    return errores, advertencias


def leer_plantilla(archivo, tipo):
    """Lee plantilla y retorna DataFrame o error."""
    try:
        df = pd.read_excel(archivo, sheet_name='MIGRACION', header=0, engine='openpyxl',
                           keep_default_na=False, na_values=[''])
        if tipo == 'si':
            cols_req = ['Cuenta Contable', 'NIT', 'Centro Costos', 'Débito', 'Crédito']
        else:
            cols_req = ['Fecha del documento', 'Tipo documento', 'Consecutivo',
                        'Cuenta Contable', 'Centro Costos', 'NIT', 'Débito', 'Crédito', 'Sucursal']
        faltantes = [c for c in cols_req if c not in df.columns]
        if faltantes:
            return None, f"Faltan columnas obligatorias: {', '.join(faltantes)}"
        # Filtrar filas completamente vacías
        df = df.dropna(how='all').reset_index(drop=True)
        return df, None
    except Exception as e:
        return None, f"Error al leer el archivo: {str(e)}"


def render_resultado(errores, nombre_libro, tipo, total_deb=None, total_cre=None, advertencias=None):
    """Renderiza el resultado de validación de una plantilla."""
    errores_reales = [e for e in errores if e[0] is not None or e[1] == 'Balance']
    balance_err    = [e for e in errores if e[1] == 'Balance']
    fila_errs      = [e for e in errores if e[0] is not None]

    total = len(fila_errs) + len(balance_err)

    if total == 0:
        st.markdown(f'<div class="ok-box">✅ <b>¡Plantilla {nombre_libro} lista!</b> No se encontraron errores. Puede continuar con la importación.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="err-box">❌ Se encontraron <b>{total} problema(s)</b> en la plantilla <b>{nombre_libro}</b> que deben corregirse antes de importar.</div>', unsafe_allow_html=True)

    # Métricas rápidas
    if tipo == 'si' and total_deb is not None:
        c1, c2, c3 = st.columns(3)
        with c1:
            color = 'green' if abs(total_deb - total_cre) < 0.01 else 'red'
            st.markdown(f'<div class="card {color}"><div class="card-label">SUMA DÉBITOS</div><div class="card-value">${fmt_num(total_deb)}</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="card {color}"><div class="card-label">SUMA CRÉDITOS</div><div class="card-value">${fmt_num(total_cre)}</div></div>', unsafe_allow_html=True)
        with c3:
            dif = total_deb - total_cre
            st.markdown(f'<div class="card {color}"><div class="card-label">DIFERENCIA</div><div class="card-value">${fmt_num(dif)}</div><div class="card-sub">{"✅ Cuadra" if abs(dif) < 0.01 else "❌ No cuadra"}</div></div>', unsafe_allow_html=True)

    if total == 0:
        return

    # Agrupar errores por columna
    st.markdown("#### 📋 Detalle de errores")

    # Error de balance primero (es general)
    for e in balance_err:
        st.markdown(f'''<div class="error-row">
            <span class="error-tag-general">BALANCE</span>
            <div><b>Toda la plantilla</b><br><span style="color:#374151;font-size:13px">{e[3]}</span></div>
        </div>''', unsafe_allow_html=True)

    # Errores por fila agrupados
    if fila_errs:
        cols_con_errores = sorted(set(e[1] for e in fila_errs))
        for col in cols_con_errores:
            errs_col = [e for e in fila_errs if e[1] == col]
            with st.expander(f"📌 {col} — {len(errs_col)} error(es)", expanded=len(errs_col) <= 5):
                for e in errs_col:
                    tag_tipo = e[2]
                    tag_html = {
                        'formato': '<span class="error-tag-formato">FORMATO</span>',
                        'logica':  '<span class="error-tag-logica">LÓGICA</span>',
                        'general': '<span class="error-tag-general">GENERAL</span>',
                    }.get(tag_tipo, '')
                    fila_txt = f'Fila {e[0]}' if e[0] else 'General'
                    st.markdown(f'''<div class="error-row">
                        {tag_html}
                        <div><b style="color:{C_MID}">{fila_txt}</b> &nbsp;
                        <span style="color:#374151;font-size:13px">{e[3]}</span></div>
                    </div>''', unsafe_allow_html=True)

    # Advertencias del sistema
    if advertencias:
        st.markdown("#### ℹ️ Validaciones que confirma el sistema al importar")
        for adv in advertencias:
            st.markdown(f'<div class="warn-box">{adv}</div>', unsafe_allow_html=True)


def exportar_excel_errores(plantillas_resultados):
    """Genera Excel con todos los errores para que el cliente corrija."""
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        for nombre, errores, df_orig in plantillas_resultados:
            rows = []
            for e in errores:
                rows.append({
                    'Fila en plantilla': e[0] if e[0] else 'General',
                    'Columna': e[1],
                    'Tipo': e[2].capitalize(),
                    'Qué debe corregir': e[3].replace('❌','').replace('⚠️','').strip(),
                })
            if rows:
                df_err = pd.DataFrame(rows)
                sheet = nombre[:31]
                df_err.to_excel(writer, sheet_name=sheet, index=False)
                ws = writer.sheets[sheet]
                ws.column_dimensions['A'].width = 18
                ws.column_dimensions['B'].width = 22
                ws.column_dimensions['C'].width = 12
                ws.column_dimensions['D'].width = 80
    return out.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🏢 INFORMACIÓN DEL CLIENTE")
    nombre_cliente = st.text_input("Nombre del cliente", placeholder="Ej: Empresa XYZ S.A.S.")
    nit_cliente    = st.text_input("NIT del cliente", placeholder="Ej: 900123456")
    
    st.markdown("---")
    st.markdown("### 📚 LIBROS A VALIDAR")
    st.markdown('<div style="font-size:12px;color:#93C5FD;margin-bottom:8px">Seleccione los libros que aplican para este cliente</div>', unsafe_allow_html=True)
    
    tiene_principal = st.checkbox("📘 Principal", value=True)
    tiene_fiscal    = st.checkbox("📙 Fiscal")
    tiene_nif       = st.checkbox("📗 NIF")

    st.markdown("---")
    st.markdown("### 📂 PLANTILLAS DE SALDOS INICIALES")

    archivos_si = {}
    if tiene_principal:
        archivos_si['Principal'] = st.file_uploader("Saldos Iniciales — Principal", type=['xlsx'], key='si_principal')
    if tiene_fiscal:
        archivos_si['Fiscal'] = st.file_uploader("Saldos Iniciales — Fiscal", type=['xlsx'], key='si_fiscal')
    if tiene_nif:
        archivos_si['NIF'] = st.file_uploader("Saldos Iniciales — NIF", type=['xlsx'], key='si_nif')

    st.markdown("---")
    st.markdown("### 📂 PLANTILLAS DE MOVIMIENTOS")

    archivos_mov = {}
    if tiene_principal:
        archivos_mov['Principal'] = st.file_uploader("Movimientos — Principal", type=['xlsx'], key='mov_principal')
    if tiene_fiscal:
        archivos_mov['Fiscal'] = st.file_uploader("Movimientos — Fiscal", type=['xlsx'], key='mov_fiscal')
    if tiene_nif:
        archivos_mov['NIF'] = st.file_uploader("Movimientos — NIF", type=['xlsx'], key='mov_nif')

    st.markdown("---")
    st.markdown("### 👥 MAESTRO DE TERCEROS")
    archivo_terceros = st.file_uploader("Maestro de Terceros (opcional)", type=['xlsx'], key='terceros',
                                        help="Si lo carga, validamos que los NITs existan")

# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f'''<div class="header-box">
    <div>
        <div style="font-size:28px;font-weight:900;color:white;letter-spacing:-0.5px">SINCO</div>
        <div style="font-size:10px;color:#93C5FD;font-weight:600;letter-spacing:2px">ERP</div>
    </div>
    <div class="logo-divider"></div>
    <div style="background:rgba(255,255,255,0.15);border-radius:10px;padding:6px 14px;font-size:13px;font-weight:800;color:white;letter-spacing:1px">A&F</div>
    <div class="logo-divider"></div>
    <div>
        <h1>Validador de Plantillas — Saldos Iniciales y Movimientos</h1>
        <p>Validación previa a la importación en SINCO ERP · Módulo A&F</p>
    </div>
</div>''', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# ESTADO INICIAL
# ─────────────────────────────────────────────────────────────────────────────
archivos_si_cargados  = {k: v for k, v in archivos_si.items()  if v is not None}
archivos_mov_cargados = {k: v for k, v in archivos_mov.items() if v is not None}
hay_archivos = len(archivos_si_cargados) > 0 or len(archivos_mov_cargados) > 0

if not hay_archivos:
    libros_sel = []
    if tiene_principal: libros_sel.append("📘 Principal")
    if tiene_fiscal:    libros_sel.append("📙 Fiscal")
    if tiene_nif:       libros_sel.append("📗 NIF")

    st.markdown(f'''<div class="inst">
    <b>👋 Bienvenido al Validador de Plantillas SINCO A&F</b><br><br>
    Este validador revisa sus plantillas <b>antes de importarlas al sistema</b>, 
    para que pueda corregir cualquier error con tiempo.<br><br>
    <b>¿Cómo usarlo?</b><br>
    1. En el menú de la izquierda, seleccione los <b>libros</b> que aplican para su empresa.<br>
    2. Cargue las plantillas de <b>Saldos Iniciales</b> y/o <b>Movimientos</b> para cada libro.<br>
    3. El validador le mostrará exactamente <b>qué debe corregir y en qué fila</b>.<br>
    4. Corrija los errores en su archivo de Excel y vuelva a cargarlo.<br>
    5. Cuando todo esté ✅, su plantilla está lista para enviársela al consultor.<br><br>
    📚 <b>Libros seleccionados:</b> {" · ".join(libros_sel) if libros_sel else "Ninguno — seleccione al menos uno en el menú izquierdo"}
    </div>''', unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1: st.markdown(f'<div class="card blue"><div class="card-label">📋 Qué valida</div><div class="card-value">+20</div><div class="card-sub">Reglas de formato y estructura</div></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div class="card green"><div class="card-label">📌 Dónde está el error</div><div class="card-value">Fila exacta</div><div class="card-sub">Columna y descripción clara</div></div>', unsafe_allow_html=True)
    with c3: st.markdown(f'<div class="card orange"><div class="card-label">📥 Reporte</div><div class="card-value">Excel</div><div class="card-sub">Descargue el listado de correcciones</div></div>', unsafe_allow_html=True)
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# CARGAR MAESTRO DE TERCEROS
# ─────────────────────────────────────────────────────────────────────────────
nits_validos = None
if archivo_terceros:
    try:
        df_ter = pd.read_excel(archivo_terceros, engine='openpyxl')
        # Buscar columna de NIT
        col_nit = next((c for c in df_ter.columns if 'nit' in c.lower() or 'identificacion' in c.lower() or 'ruc' in c.lower()), None)
        if col_nit:
            nits_validos = set(df_ter[col_nit].apply(limpiar_nit).tolist())
    except: pass

# ─────────────────────────────────────────────────────────────────────────────
# INFO CLIENTE
# ─────────────────────────────────────────────────────────────────────────────
if nombre_cliente or nit_cliente:
    st.markdown(f'''<div style="background:white;border-radius:12px;padding:14px 22px;margin-bottom:18px;border-left:5px solid {C_MID};box-shadow:0 2px 10px rgba(0,0,0,0.06);display:flex;align-items:center;gap:12px">
        <span style="font-size:18px;font-weight:700;color:{C_DARK}">{nombre_cliente or "Cliente"}</span>
        {f'<span style="background:{C_MID};color:white;padding:3px 12px;border-radius:20px;font-size:11px;font-weight:600">NIT {nit_cliente}</span>' if nit_cliente else ""}
    </div>''', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# PROCESAMIENTO Y RESULTADOS
# ─────────────────────────────────────────────────────────────────────────────
plantillas_resultados_export = []
total_errores_global = 0
total_plantillas = 0

# ── SALDOS INICIALES ──
if archivos_si_cargados:
    st.markdown('<div class="seccion">📋 Saldos Iniciales</div>', unsafe_allow_html=True)
    for libro, archivo in archivos_si_cargados.items():
        badge_color = {'Principal':'', 'Fiscal':' fiscal', 'NIF':' nif'}.get(libro, '')
        st.markdown(f'<div style="margin-bottom:8px"><span class="libro-badge{badge_color}">{libro}</span><b style="color:{C_DARK}">{archivo.name}</b></div>', unsafe_allow_html=True)
        
        df, error_lectura = leer_plantilla(archivo, 'si')
        if error_lectura:
            st.markdown(f'<div class="err-box">❌ No se pudo leer el archivo: <b>{error_lectura}</b></div>', unsafe_allow_html=True)
            continue

        errores, total_deb, total_cre = validar_saldos_iniciales(df, nits_validos)
        render_resultado(errores, f"Saldos Iniciales {libro}", 'si', total_deb, total_cre)
        plantillas_resultados_export.append((f"SI {libro}", errores, df))
        total_errores_global += len(errores)
        total_plantillas += 1

# ── MOVIMIENTOS ──
if archivos_mov_cargados:
    st.markdown('<div class="seccion">📊 Movimientos</div>', unsafe_allow_html=True)
    for libro, archivo in archivos_mov_cargados.items():
        badge_color = {'Principal':'', 'Fiscal':' fiscal', 'NIF':' nif'}.get(libro, '')
        st.markdown(f'<div style="margin-bottom:8px"><span class="libro-badge{badge_color}">{libro}</span><b style="color:{C_DARK}">{archivo.name}</b></div>', unsafe_allow_html=True)

        df, error_lectura = leer_plantilla(archivo, 'mov')
        if error_lectura:
            st.markdown(f'<div class="err-box">❌ No se pudo leer el archivo: <b>{error_lectura}</b></div>', unsafe_allow_html=True)
            continue

        errores, advertencias = validar_movimientos(df, nits_validos)
        render_resultado(errores, f"Movimientos {libro}", 'mov', advertencias=advertencias)
        plantillas_resultados_export.append((f"MOV {libro}", errores, df))
        total_errores_global += len(errores)
        total_plantillas += 1

# ─────────────────────────────────────────────────────────────────────────────
# RESUMEN FINAL
# ─────────────────────────────────────────────────────────────────────────────
if total_plantillas > 0:
    st.markdown('<div class="seccion">📊 Resumen</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f'<div class="card blue"><div class="card-label">PLANTILLAS REVISADAS</div><div class="card-value">{total_plantillas}</div></div>', unsafe_allow_html=True)
    with c2:
        color = 'green' if total_errores_global == 0 else 'red'
        st.markdown(f'<div class="card {color}"><div class="card-label">ERRORES ENCONTRADOS</div><div class="card-value">{total_errores_global}</div><div class="card-sub">{"✅ Listo para importar" if total_errores_global == 0 else "❌ Corrija antes de importar"}</div></div>', unsafe_allow_html=True)
    with c3:
        estado = "✅ Sin errores" if total_errores_global == 0 else f"❌ {total_errores_global} error(es)"
        st.markdown(f'<div class="card {"green" if total_errores_global == 0 else "red"}"><div class="card-label">ESTADO GENERAL</div><div class="card-value" style="font-size:16px">{estado}</div></div>', unsafe_allow_html=True)

    if total_errores_global == 0:
        st.markdown(f'''<div class="ok-box" style="text-align:center;padding:20px">
            ✅ <b>¡Todas las plantillas están correctas!</b><br>
            <span style="font-size:12px;color:#166534">Puede enviarlas al consultor para proceder con la importación.</span>
        </div>''', unsafe_allow_html=True)
    else:
        # Exportar errores
        hay_errores_reales = any(len(e[1]) > 0 for e in plantillas_resultados_export)
        if hay_errores_reales:
            excel_bytes = exportar_excel_errores(plantillas_resultados_export)
            st.download_button(
                label="📥 Descargar listado de errores en Excel",
                data=excel_bytes,
                file_name=f"Errores_Plantillas_{nombre_cliente or 'Cliente'}_{datetime.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            st.markdown(f'<div class="warn-box">💡 <b>¿Cómo corregir?</b> Descargue el archivo de errores, abra su plantilla en Excel, vaya a cada fila indicada y corrija el valor. Luego vuelva a cargar la plantilla aquí para verificar.</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# LEYENDA
# ─────────────────────────────────────────────────────────────────────────────
with st.expander("📖 ¿Qué significan los colores de los errores?"):
    st.markdown(f'''
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:8px">
        <div><span class="error-tag-formato">FORMATO</span> &nbsp; Errores de escritura: el valor está vacío, tiene letras donde van números, etc.</div>
        <div><span class="error-tag-logica">LÓGICA</span> &nbsp; El valor existe pero no coincide con los catálogos (ej: NIT no registrado).</div>
        <div><span class="error-tag-general">BALANCE</span> &nbsp; La suma de Débitos no es igual a la suma de Créditos en toda la plantilla.</div>
    </div>''', unsafe_allow_html=True)
