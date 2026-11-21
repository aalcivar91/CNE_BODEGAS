import io
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

# ==============================================================================
# CONFIGURACIÓN GENERAL
# ==============================================================================
st.set_page_config(
    page_title="Control Logístico Electoral — Guayas 2026",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

TZ_EC = ZoneInfo("America/Guayaquil")
EXCEL_PATH = "Plan_Entrega_Material_Electoral_Ordenado-v21.xlsx"
SQLITE_PATH = "estado_despacho_guayas.db"


def get_secret(key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(key, default))
    except Exception:
        return os.environ.get(key, default)


ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD", "GUAYAS2026")
SUPABASE_URL = get_secret("SUPABASE_URL", "")
SUPABASE_KEY = get_secret("SUPABASE_KEY", "")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)


# ==============================================================================
# ESTILOS CSS
# ==============================================================================
st.markdown(
    """
    <style>
    .main-banner {
        background: linear-gradient(135deg, #1B365D 0%, #2C4A70 100%);
        color: white;
        padding: 1.1rem 1.4rem;
        border-radius: 12px;
        margin-bottom: 1rem;
    }
    .main-banner h2 { margin: 0; font-size: 1.45rem; color: white; }
    .main-banner p { margin: 0.25rem 0 0 0; opacity: 0.9; font-size: 0.92rem; }
    .franja-box {
        background: #F1F5F9;
        border-left: 5px solid #1B365D;
        padding: 0.85rem 1.1rem;
        border-radius: 8px;
        margin-bottom: 0.9rem;
    }
    .franja-box strong { color: #1B365D; }
    .kpi-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 0.75rem 0.9rem;
        text-align: center;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    .kpi-val { font-size: 1.35rem; font-weight: 700; color: #1B365D; }
    .kpi-lbl { font-size: 0.78rem; color: #475569; margin-top: 2px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ==============================================================================
# CARGA DE BASE DE DATOS EXCEL
# ==============================================================================
@st.cache_data(show_spinner=False)
def load_base_data(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Base de Datos")
    df = df[pd.to_numeric(df["ORDEN"], errors="coerce").notna()].copy().reset_index(drop=True)

    df["ORDEN"] = df["ORDEN"].astype(int)
    df["NUMERO DE PAQUETES"] = pd.to_numeric(df["NUMERO DE PAQUETES"], errors="coerce").fillna(0).astype(int)
    df["KITS CDA"] = pd.to_numeric(df["KITS CDA"], errors="coerce").fillna(0).astype(int)

    # Recalcular columnas de fórmula para garantizar valores exactos siempre
    df["BIOMBOS (Kits x2)"] = df["NUMERO DE PAQUETES"] * 2
    df["BIOMBO MAP (Recinto x2)"] = 2
    df["URNAS BLANCAS"] = df["NUMERO DE PAQUETES"]
    df["URNAS CAFÉS"] = df["NUMERO DE PAQUETES"]

    for col in [
        "BLOQUE", "HORA BLOQUE", "CANTON", "PARROQUIA", "ZONA", "RECINTO",
        "CDA", "CODIGO KIT CDA", "CODIGO PAQUETES", "PERCHA",
        "NIVEL (POR PERCHA)", "FUERZA", "GT", "RESPONSABLE"
    ]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    def fmt_cam(v):
        if pd.isna(v) or str(v).strip() == "":
            return "Sin asignar"
        s = str(v).strip()
        return s[:-2] if s.endswith(".0") else s

    df["CAMION"] = df["CAMION"].apply(fmt_cam)

    # Normalizar fecha y hora de retiro
    df["FECHA_DT"] = pd.to_datetime(df["FECHA RETIRO"], errors="coerce")
    df["FECHA_STR"] = df["FECHA_DT"].dt.strftime("%d/%m/%Y").fillna("")
    df["DIA_ENTREGA"] = df["FECHA_DT"].dt.strftime("%Y-%m-%d").map(
        {
            "2026-11-27": "Viernes 27/11",
            "2026-11-28": "Sábado 28/11",
        }
    ).fillna("Por definir")

    def fmt_hora(v):
        if pd.isna(v) or str(v).strip() == "":
            return ""
        return str(v).strip()[:5]

    df["HORA_STR"] = df["HORA DE RETIRO"].apply(fmt_hora)
    return df


# ==============================================================================
# CAPA DE PERSISTENCIA (SUPABASE EN LA NUBE O SQLITE LOCAL)
# ==============================================================================
def init_sqlite():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS estado_logistico (
            orden INTEGER PRIMARY KEY,
            entregado INTEGER DEFAULT 0,
            fecha_hora_entrega TEXT DEFAULT '',
            usuario_entrega TEXT DEFAULT '',
            obs_entrega TEXT DEFAULT '',
            recibido_bodega INTEGER DEFAULT 0,
            fecha_hora_finalizacion TEXT DEFAULT '',
            usuario_recepcion TEXT DEFAULT '',
            obs_recepcion TEXT DEFAULT ''
        )
        """
    )
    conn.commit()
    conn.close()


@st.cache_resource
def get_supabase_client():
    if not USE_SUPABASE:
        return None
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def load_status_df() -> pd.DataFrame:
    cols = [
        "orden", "entregado", "fecha_hora_entrega", "usuario_entrega", "obs_entrega",
        "recibido_bodega", "fecha_hora_finalizacion", "usuario_recepcion", "obs_recepcion",
    ]
    if USE_SUPABASE:
        sb = get_supabase_client()
        resp = sb.table("estado_logistico").select("*").limit(2000).execute()
        data = resp.data or []
        if not data:
            return pd.DataFrame(columns=cols)
        df_st = pd.DataFrame(data)
        for c in cols:
            if c not in df_st.columns:
                df_st[c] = "" if "fecha" in c or "obs" in c or "usuario" in c else 0
        return df_st[cols]
    else:
        init_sqlite()
        conn = sqlite3.connect(SQLITE_PATH)
        df_st = pd.read_sql_query("SELECT * FROM estado_logistico", conn)
        conn.close()
        return df_st


def upsert_status_records(records: list[dict]):
    if not records:
        return
    if USE_SUPABASE:
        sb = get_supabase_client()
        sb.table("estado_logistico").upsert(records, on_conflict="orden").execute()
    else:
        init_sqlite()
        conn = sqlite3.connect(SQLITE_PATH)
        cur = conn.cursor()
        for r in records:
            cur.execute(
                """
                INSERT INTO estado_logistico (
                    orden, entregado, fecha_hora_entrega, usuario_entrega, obs_entrega,
                    recibido_bodega, fecha_hora_finalizacion, usuario_recepcion, obs_recepcion
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(orden) DO UPDATE SET
                    entregado=excluded.entregado,
                    fecha_hora_entrega=excluded.fecha_hora_entrega,
                    usuario_entrega=excluded.usuario_entrega,
                    obs_entrega=excluded.obs_entrega,
                    recibido_bodega=excluded.recibido_bodega,
                    fecha_hora_finalizacion=excluded.fecha_hora_finalizacion,
                    usuario_recepcion=excluded.usuario_recepcion,
                    obs_recepcion=excluded.obs_recepcion
                """,
                (
                    int(r["orden"]),
                    int(bool(r["entregado"])),
                    str(r.get("fecha_hora_entrega", "")),
                    str(r.get("usuario_entrega", "")),
                    str(r.get("obs_entrega", "")),
                    int(bool(r["recibido_bodega"])),
                    str(r.get("fecha_hora_finalizacion", "")),
                    str(r.get("usuario_recepcion", "")),
                    str(r.get("obs_recepcion", "")),
                ),
            )
        conn.commit()
        conn.close()


def get_merged_df() -> pd.DataFrame:
    base = load_base_data(EXCEL_PATH)
    st_df = load_status_df()
    if len(st_df) == 0:
        base["ENTREGADO"] = False
        base["FECHA_HORA_ENTREGA"] = ""
        base["USUARIO_ENTREGA"] = ""
        base["OBS_ENTREGA"] = ""
        base["RECIBIDO_BODEGA"] = False
        base["FECHA Y HORA DE FINALIZACION"] = ""
        base["USUARIO_RECEPCION"] = ""
        base["OBS_RECEPCION"] = ""
    else:
        st_df = st_df.rename(
            columns={
                "orden": "ORDEN",
                "entregado": "ENTREGADO",
                "fecha_hora_entrega": "FECHA_HORA_ENTREGA",
                "usuario_entrega": "USUARIO_ENTREGA",
                "obs_entrega": "OBS_ENTREGA",
                "recibido_bodega": "RECIBIDO_BODEGA",
                "fecha_hora_finalizacion": "FECHA Y HORA DE FINALIZACION",
                "usuario_recepcion": "USUARIO_RECEPCION",
                "obs_recepcion": "OBS_RECEPCION",
            }
        )
        base = base.merge(st_df, on="ORDEN", how="left")
        base["ENTREGADO"] = base["ENTREGADO"].fillna(0).astype(bool)
        base["RECIBIDO_BODEGA"] = base["RECIBIDO_BODEGA"].fillna(0).astype(bool)
        for c in [
            "FECHA_HORA_ENTREGA", "USUARIO_ENTREGA", "OBS_ENTREGA",
            "FECHA Y HORA DE FINALIZACION", "USUARIO_RECEPCION", "OBS_RECEPCION"
        ]:
            base[c] = base[c].fillna("").astype(str)

    def estado_lbl(row):
        if row["RECIBIDO_BODEGA"]:
            return "📦 Recibido en Bodega"
        if row["ENTREGADO"]:
            return "✅ Entregado"
        return "⏳ Pendiente"

    base["ESTADO"] = base.apply(estado_lbl, axis=1)
    return base


def to_excel_bytes(df_export: pd.DataFrame, sheet_name: str = "Reporte") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_export.to_excel(writer, index=False, sheet_name=sheet_name)
    return buf.getvalue()


def now_ec_str() -> str:
    return datetime.now(TZ_EC).strftime("%d/%m/%Y %H:%M")


def sort_camiones(cam_list):
    def key_fn(x):
        s = str(x)
        return (0, int(s)) if s.isdigit() else (1, s)
    return sorted(cam_list, key=key_fn)


# ==============================================================================
# ENCABEZADO PRINCIPAL
# ==============================================================================
if not os.path.exists(EXCEL_PATH):
    st.error(f"No se encontró el archivo base `{EXCEL_PATH}` en la carpeta del aplicativo.")
    st.stop()

df_all = get_merged_df()
storage_badge = "☁️ Supabase (Tiempo Real)" if USE_SUPABASE else "💾 SQLite Local"

st.markdown(
    f"""
    <div class="main-banner">
        <h2>📦 Control Logístico de Material Electoral — Guayas 2026</h2>
        <p>584 Recintos · 9,466 Paquetes/Kits · 25 Cantones · 499 Kits CDA &nbsp;|&nbsp; Almacenamiento: {storage_badge}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

tab1, tab2, tab3 = st.tabs(
    [
        "📅 1. Consulta Comandantes (Horarios)",
        "🔐 2. Control Entregas y Retorno Bodega",
        "📊 3. Avance (%) Viernes / Sábado / Domingo",
    ]
)

# ==============================================================================
# PESTAÑA 1: CONSULTA PARA COMANDANTES DE FUERZAS
# ==============================================================================
with tab1:
    st.subheader("Consulta de Fecha, Horario de Recolección y Carga")

    c1, c2, c3, c4 = st.columns(4)
    fuerzas_opts = ["TODAS"] + sorted(df_all["FUERZA"].unique().tolist())
    sel_fz = c1.selectbox("Fuerza", fuerzas_opts, key="q_fz")

    df_f = df_all.copy()
    if sel_fz != "TODAS":
        df_f = df_f[df_f["FUERZA"] == sel_fz]

    gt_vals = sorted([x for x in df_f["GT"].unique().tolist() if x])
    sel_gt = c2.selectbox("GT (Grupo de Tarea)", ["TODOS"] + gt_vals, key="q_gt")
    if sel_gt != "TODOS":
        df_f = df_f[df_f["GT"] == sel_gt]

    cam_vals = sort_camiones(df_f["CAMION"].unique().tolist())
    sel_cam = c3.selectbox("Camión", ["TODOS"] + cam_vals, key="q_cam")
    if sel_cam != "TODOS":
        df_f = df_f[df_f["CAMION"] == sel_cam]

    dia_vals = ["TODOS"] + sorted(df_f["DIA_ENTREGA"].unique().tolist())
    sel_dia = c4.selectbox("Día de Recolección", dia_vals, key="q_dia")
    if sel_dia != "TODOS":
        df_f = df_f[df_f["DIA_ENTREGA"] == sel_dia]

    c5, c6, c7, c8 = st.columns([1.2, 1.2, 1.8, 0.8])
    can_vals = ["TODOS"] + sorted(df_f["CANTON"].unique().tolist())
    sel_can = c5.selectbox("Cantón", can_vals, key="q_can")
    if sel_can != "TODOS":
        df_f = df_f[df_f["CANTON"] == sel_can]

    par_vals = ["TODAS"] + sorted(df_f["PARROQUIA"].unique().tolist())
    sel_par = c6.selectbox("Parroquia", par_vals, key="q_par")
    if sel_par != "TODAS":
        df_f = df_f[df_f["PARROQUIA"] == sel_par]

    busq = c7.text_input("Buscar Recinto / Zona / Código Paquete", placeholder="Ej: MILAGRO, ROCAFUERTE, KIT-0085...", key="q_busq")
    if busq.strip():
        q = busq.strip().upper()
        mask_q = (
            df_f["RECINTO"].str.upper().str.contains(q, na=False)
            | df_f["ZONA"].str.upper().str.contains(q, na=False)
            | df_f["CODIGO PAQUETES"].str.upper().str.contains(q, na=False)
            | df_f["CODIGO KIT CDA"].str.upper().str.contains(q, na=False)
        )
        df_f = df_f[mask_q]

    solo_cda = c8.checkbox("Solo CDA", value=False, key="q_cda")
    if solo_cda:
        df_f = df_f[df_f["CDA"] == "SÍ"]

    # Banner de Franja Horaria Dinámica
    if len(df_f) > 0:
        fechas_u = sorted(df_f["FECHA_STR"].unique().tolist())
        horas_u = sorted([h for h in df_f["HORA_STR"].unique().tolist() if h])
        bloques_u = list(dict.fromkeys(df_f["BLOQUE"].tolist()))
        franja_txt = f"{horas_u[0]} a {horas_u[-1]}" if len(horas_u) > 1 else (horas_u[0] if horas_u else "Por definir")
        st.markdown(
            f"""
            <div class="franja-box">
                <strong>🗓️ Fecha(s) de Recolección:</strong> {' / '.join(fechas_u)} &nbsp;&nbsp;|&nbsp;&nbsp;
                <strong>⏰ Franja Horaria de Retiro:</strong> {franja_txt} &nbsp;&nbsp;|&nbsp;&nbsp;
                <strong>📌 Bloque(s):</strong> {', '.join(bloques_u)}
            </div>
            """,
            unsafe_allow_html=True,
        )

    # KPIs
    k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
    kpis = [
        (k1, f"{len(df_f):,}", "Recintos"),
        (k2, f"{int(df_f['NUMERO DE PAQUETES'].sum()):,}", "Paquetes / Kits"),
        (k3, f"{int(df_f['BIOMBOS (Kits x2)'].sum()):,}", "Biombos"),
        (k4, f"{int(df_f['BIOMBO MAP (Recinto x2)'].sum()):,}", "Biombo MAP"),
        (k5, f"{int(df_f['URNAS BLANCAS'].sum()):,}", "Urnas Blancas"),
        (k6, f"{int(df_f['URNAS CAFÉS'].sum()):,}", "Urnas Cafés"),
        (k7, f"{int(df_f['KITS CDA'].sum()):,}", "Kits CDA"),
    ]
    for col_k, val, lbl in kpis:
        col_k.markdown(
            f'<div class="kpi-card"><div class="kpi-val">{val}</div><div class="kpi-lbl">{lbl}</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    vista = st.radio(
        "Modo de visualización:",
        ["📋 Detalle por Recinto", "🚚 Resumen por Camión"],
        horizontal=True,
        key="q_vista",
    )

    if vista == "🚚 Resumen por Camión":
        df_cam = (
            df_f.groupby(["DIA_ENTREGA", "FECHA_STR", "HORA_STR", "BLOQUE", "FUERZA", "GT", "CAMION"], sort=False)
            .agg(
                Cantones=("CANTON", lambda s: ", ".join(dict.fromkeys(s))),
                Recintos=("RECINTO", "count"),
                Paquetes=("NUMERO DE PAQUETES", "sum"),
                Biombos=("BIOMBOS (Kits x2)", "sum"),
                Biombo_MAP=("BIOMBO MAP (Recinto x2)", "sum"),
                Urnas_Blancas=("URNAS BLANCAS", "sum"),
                Urnas_Cafes=("URNAS CAFÉS", "sum"),
                Kits_CDA=("KITS CDA", "sum"),
                Entregados=("ENTREGADO", "sum"),
                Recibidos_Bod=("RECIBIDO_BODEGA", "sum"),
            )
            .reset_index()
        )
        df_cam.rename(
            columns={
                "DIA_ENTREGA": "Día",
                "FECHA_STR": "Fecha",
                "HORA_STR": "Hora Retiro",
                "BLOQUE": "Bloque",
                "FUERZA": "Fuerza",
                "CAMION": "Camión",
                "Biombo_MAP": "Biombo MAP",
                "Urnas_Blancas": "Urnas Blancas",
                "Urnas_Cafes": "Urnas Cafés",
                "Kits_CDA": "Kits CDA",
                "Recibidos_Bod": "Recib. Bodega",
            },
            inplace=True,
        )
        st.dataframe(df_cam, use_container_width=True, hide_index=True, height=480)
        st.download_button(
            "⬇️ Descargar Resumen por Camión (Excel)",
            data=to_excel_bytes(df_cam, "Resumen_Camiones"),
            file_name="Horarios_Por_Camion_Guayas2026.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        cols_show = [
            "ORDEN", "ESTADO", "FECHA_STR", "HORA_STR", "BLOQUE", "FUERZA", "GT", "CAMION",
            "CANTON", "PARROQUIA", "ZONA", "RECINTO", "NUMERO DE PAQUETES",
            "CDA", "KITS CDA", "CODIGO KIT CDA", "BIOMBOS (Kits x2)",
            "BIOMBO MAP (Recinto x2)", "URNAS BLANCAS", "URNAS CAFÉS", "CODIGO PAQUETES",
        ]
        df_show = df_f[cols_show].rename(columns={"FECHA_STR": "FECHA RETIRO", "HORA_STR": "HORA RETIRO"})
        st.dataframe(df_show, use_container_width=True, hide_index=True, height=480)
        st.download_button(
            "⬇️ Descargar Detalle Filtrado (Excel)",
            data=to_excel_bytes(df_show, "Detalle_Recintos"),
            file_name="Horarios_Recintos_Guayas2026.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

# ==============================================================================
# PESTAÑA 2: CONTROL DE ENTREGAS Y RETORNO A BODEGA (CON CLAVE)
# ==============================================================================
with tab2:
    st.subheader("Control Operativo de Bodega — Despacho y Retorno")

    if "auth_ok" not in st.session_state:
        st.session_state["auth_ok"] = False

    if not st.session_state["auth_ok"]:
        st.info("🔒 Esta sección está restringida al personal de control de bodega. Ingrese la clave para registrar entregas y recepciones.")
        col_pw, col_btn = st.columns([2, 1])
        pwd_in = col_pw.text_input("Clave de acceso", type="password", key="pwd_input")
        if col_btn.button("Ingresar", type="primary", use_container_width=True):
            if pwd_in == ADMIN_PASSWORD:
                st.session_state["auth_ok"] = True
                st.rerun()
            else:
                st.error("Clave incorrecta.")
    else:
        top_a, top_b = st.columns([4, 1])
        operador = top_a.text_input("Nombre / Grado del operador que registra", value=st.session_state.get("operador", "Bodega Base Naval Sur"), key="op_name")
        st.session_state["operador"] = operador
        if top_b.button("🔒 Cerrar sesión", use_container_width=True):
            st.session_state["auth_ok"] = False
            st.rerun()

        sub_ent, sub_rec = st.tabs(
            [
                "🚚 Despacho desde Bodega (Viernes / Sábado)",
                "📦 Recibido en Bodega — Post-Elecciones (Domingo)",
            ]
        )

        # --- SUBPESTAÑA A: ENTREGADO (DESPACHO) ---
        with sub_ent:
            fc1, fc2, fc3, fc4 = st.columns(4)
            e_fz = fc1.selectbox("Fuerza", ["TODAS"] + sorted(df_all["FUERZA"].unique().tolist()), key="e_fz")
            df_e = df_all if e_fz == "TODAS" else df_all[df_all["FUERZA"] == e_fz]

            e_gt_opts = ["TODOS"] + sorted([x for x in df_e["GT"].unique().tolist() if x])
            e_gt = fc2.selectbox("GT", e_gt_opts, key="e_gt")
            if e_gt != "TODOS":
                df_e = df_e[df_e["GT"] == e_gt]

            e_cam_opts = ["TODOS"] + sort_camiones(df_e["CAMION"].unique().tolist())
            e_cam = fc3.selectbox("Camión", e_cam_opts, key="e_cam")
            if e_cam != "TODOS":
                df_e = df_e[df_e["CAMION"] == e_cam]

            e_est = fc4.selectbox("Estado Entrega", ["TODOS", "Pendientes", "Entregados"], key="e_est")
            if e_est == "Pendientes":
                df_e = df_e[~df_e["ENTREGADO"]]
            elif e_est == "Entregados":
                df_e = df_e[df_e["ENTREGADO"]]

            # Acción rápida por lote/camión filtrado
            st.markdown("##### ⚡ Acción rápida sobre el filtro actual")
            qa1, qa2, qa3 = st.columns([2, 1.3, 1.3])
            obs_lote = qa1.text_input("Observación de despacho (opcional)", placeholder="Ej: Acta firmada sin novedad", key="obs_ent_lote")

            if qa2.button(f"✅ Marcar {len(df_e)} recinto(s) como ENTREGADO", type="primary", use_container_width=True, disabled=(len(df_e) == 0)):
                ts = now_ec_str()
                recs = []
                for _, r in df_e.iterrows():
                    recs.append(
                        {
                            "orden": int(r["ORDEN"]),
                            "entregado": 1,
                            "fecha_hora_entrega": r["FECHA_HORA_ENTREGA"] if r["ENTREGADO"] and r["FECHA_HORA_ENTREGA"] else ts,
                            "usuario_entrega": operador,
                            "obs_entrega": obs_lote if obs_lote else r["OBS_ENTREGA"],
                            "recibido_bodega": int(bool(r["RECIBIDO_BODEGA"])),
                            "fecha_hora_finalizacion": r["FECHA Y HORA DE FINALIZACION"],
                            "usuario_recepcion": r["USUARIO_RECEPCION"],
                            "obs_recepcion": r["OBS_RECEPCION"],
                        }
                    )
                upsert_status_records(recs)
                st.success(f"Se marcaron {len(recs)} recintos como ENTREGADO ({ts}).")
                st.rerun()

            if qa3.button("↩️ Revertir a PENDIENTE", use_container_width=True, disabled=(len(df_e) == 0)):
                recs = []
                for _, r in df_e.iterrows():
                    recs.append(
                        {
                            "orden": int(r["ORDEN"]),
                            "entregado": 0,
                            "fecha_hora_entrega": "",
                            "usuario_entrega": "",
                            "obs_entrega": "",
                            "recibido_bodega": 0,
                            "fecha_hora_finalizacion": "",
                            "usuario_recepcion": "",
                            "obs_recepcion": "",
                        }
                    )
                upsert_status_records(recs)
                st.warning(f"Se revirtieron {len(recs)} recintos a PENDIENTE.")
                st.rerun()

            st.markdown("##### 📋 Edición individual por recinto (Despacho)")
            edit_cols = [
                "ORDEN", "ENTREGADO", "FECHA_HORA_ENTREGA", "OBS_ENTREGA",
                "DIA_ENTREGA", "HORA_STR", "FUERZA", "GT", "CAMION",
                "CANTON", "ZONA", "RECINTO", "NUMERO DE PAQUETES", "PERCHA",
            ]
            edited_ent = st.data_editor(
                df_e[edit_cols],
                use_container_width=True,
                hide_index=True,
                height=420,
                disabled=[c for c in edit_cols if c not in ("ENTREGADO", "OBS_ENTREGA")],
                column_config={
                    "ENTREGADO": st.column_config.CheckboxColumn("ENTREGADO", default=False),
                    "OBS_ENTREGA": st.column_config.TextColumn("Observación Entrega"),
                    "FECHA_HORA_ENTREGA": st.column_config.TextColumn("Fecha/Hora Entrega"),
                    "HORA_STR": st.column_config.TextColumn("Hora Prog."),
                },
                key="editor_entregas",
            )
            if st.button("💾 Guardar cambios individuales de Entrega", type="primary", key="save_ent_ind"):
                ts = now_ec_str()
                orig_map = df_e.set_index("ORDEN").to_dict("index")
                to_save = []
                for _, row_ed in edited_ent.iterrows():
                    o_id = int(row_ed["ORDEN"])
                    o_prev = orig_map[o_id]
                    new_ent = bool(row_ed["ENTREGADO"])
                    new_obs = str(row_ed["OBS_ENTREGA"] or "")
                    if new_ent != bool(o_prev["ENTREGADO"]) or new_obs != str(o_prev["OBS_ENTREGA"]):
                        to_save.append(
                            {
                                "orden": o_id,
                                "entregado": int(new_ent),
                                "fecha_hora_entrega": (o_prev["FECHA_HORA_ENTREGA"] or ts) if new_ent else "",
                                "usuario_entrega": operador if new_ent else "",
                                "obs_entrega": new_obs if new_ent else "",
                                "recibido_bodega": int(bool(o_prev["RECIBIDO_BODEGA"])) if new_ent else 0,
                                "fecha_hora_finalizacion": o_prev["FECHA Y HORA DE FINALIZACION"] if new_ent else "",
                                "usuario_recepcion": o_prev["USUARIO_RECEPCION"] if new_ent else "",
                                "obs_recepcion": o_prev["OBS_RECEPCION"] if new_ent else "",
                            }
                        )
                if to_save:
                    upsert_status_records(to_save)
                    st.success(f"Guardados {len(to_save)} cambios de entrega.")
                    st.rerun()
                else:
                    st.info("No se detectaron cambios pendientes por guardar.")

        # --- SUBPESTAÑA B: RECIBIDO EN BODEGA (SOLO HABILITADO SI YA FUE ENTREGADO) ---
        with sub_rec:
            df_entregados = df_all[df_all["ENTREGADO"]].copy()
            if len(df_entregados) == 0:
                st.warning(
                    "🔒 Todavía no hay recintos marcados como **ENTREGADO**. "
                    "La recepción en bodega (domingo post-elecciones) se habilita automáticamente únicamente para los recintos que ya fueron entregados."
                )
            else:
                st.caption(
                    f"Habilitados para retorno a bodega: **{len(df_entregados)}** recintos entregados "
                    f"(de {len(df_all)} totales). Los recintos aún no entregados permanecen bloqueados."
                )
                rc1, rc2, rc3, rc4 = st.columns(4)
                r_fz = rc1.selectbox("Fuerza", ["TODAS"] + sorted(df_entregados["FUERZA"].unique().tolist()), key="r_fz")
                df_r = df_entregados if r_fz == "TODAS" else df_entregados[df_entregados["FUERZA"] == r_fz]

                r_gt_opts = ["TODOS"] + sorted([x for x in df_r["GT"].unique().tolist() if x])
                r_gt = rc2.selectbox("GT", r_gt_opts, key="r_gt")
                if r_gt != "TODOS":
                    df_r = df_r[df_r["GT"] == r_gt]

                r_cam_opts = ["TODOS"] + sort_camiones(df_r["CAMION"].unique().tolist())
                r_cam = rc3.selectbox("Camión", r_cam_opts, key="r_cam")
                if r_cam != "TODOS":
                    df_r = df_r[df_r["CAMION"] == r_cam]

                r_est = rc4.selectbox("Estado Retorno", ["TODOS", "Por recibir", "Recibidos en Bodega"], key="r_est")
                if r_est == "Por recibir":
                    df_r = df_r[~df_r["RECIBIDO_BODEGA"]]
                elif r_est == "Recibidos en Bodega":
                    df_r = df_r[df_r["RECIBIDO_BODEGA"]]

                ra1, ra2, ra3 = st.columns([2, 1.4, 1.2])
                obs_rec_lote = ra1.text_input("Novedad / Observación de retorno (opcional)", placeholder="Ej: Retorno completo con actas y urnas", key="obs_rec_lote")

                if ra2.button(f"📦 Marcar {len(df_r)} recinto(s) RECIBIDO EN BODEGA", type="primary", use_container_width=True, disabled=(len(df_r) == 0)):
                    ts = now_ec_str()
                    recs = []
                    for _, r in df_r.iterrows():
                        recs.append(
                            {
                                "orden": int(r["ORDEN"]),
                                "entregado": 1,
                                "fecha_hora_entrega": r["FECHA_HORA_ENTREGA"],
                                "usuario_entrega": r["USUARIO_ENTREGA"],
                                "obs_entrega": r["OBS_ENTREGA"],
                                "recibido_bodega": 1,
                                "fecha_hora_finalizacion": r["FECHA Y HORA DE FINALIZACION"] if r["RECIBIDO_BODEGA"] and r["FECHA Y HORA DE FINALIZACION"] else ts,
                                "usuario_recepcion": operador,
                                "obs_recepcion": obs_rec_lote if obs_rec_lote else r["OBS_RECEPCION"],
                            }
                        )
                    upsert_status_records(recs)
                    st.success(f"Registrados {len(recs)} recintos como RECIBIDO EN BODEGA ({ts}).")
                    st.rerun()

                if ra3.button("↩️ Desmarcar Retorno", use_container_width=True, disabled=(len(df_r) == 0)):
                    recs = []
                    for _, r in df_r.iterrows():
                        recs.append(
                            {
                                "orden": int(r["ORDEN"]),
                                "entregado": 1,
                                "fecha_hora_entrega": r["FECHA_HORA_ENTREGA"],
                                "usuario_entrega": r["USUARIO_ENTREGA"],
                                "obs_entrega": r["OBS_ENTREGA"],
                                "recibido_bodega": 0,
                                "fecha_hora_finalizacion": "",
                                "usuario_recepcion": "",
                                "obs_recepcion": "",
                            }
                        )
                    upsert_status_records(recs)
                    st.warning(f"Se desmarcó el retorno en {len(recs)} recintos.")
                    st.rerun()

                rec_cols = [
                    "ORDEN", "RECIBIDO_BODEGA", "FECHA Y HORA DE FINALIZACION", "OBS_RECEPCION",
                    "FECHA_HORA_ENTREGA", "FUERZA", "GT", "CAMION",
                    "CANTON", "ZONA", "RECINTO", "NUMERO DE PAQUETES",
                ]
                edited_rec = st.data_editor(
                    df_r[rec_cols],
                    use_container_width=True,
                    hide_index=True,
                    height=420,
                    disabled=[c for c in rec_cols if c not in ("RECIBIDO_BODEGA", "OBS_RECEPCION")],
                    column_config={
                        "RECIBIDO_BODEGA": st.column_config.CheckboxColumn("RECIBIDO EN BODEGA", default=False),
                        "OBS_RECEPCION": st.column_config.TextColumn("Observación Retorno"),
                    },
                    key="editor_recepcion",
                )
                if st.button("💾 Guardar cambios individuales de Retorno", type="primary", key="save_rec_ind"):
                    ts = now_ec_str()
                    orig_map = df_r.set_index("ORDEN").to_dict("index")
                    to_save = []
                    for _, row_ed in edited_rec.iterrows():
                        o_id = int(row_ed["ORDEN"])
                        o_prev = orig_map[o_id]
                        new_rec = bool(row_ed["RECIBIDO_BODEGA"])
                        new_obs = str(row_ed["OBS_RECEPCION"] or "")
                        if new_rec != bool(o_prev["RECIBIDO_BODEGA"]) or new_obs != str(o_prev["OBS_RECEPCION"]):
                            to_save.append(
                                {
                                    "orden": o_id,
                                    "entregado": 1,
                                    "fecha_hora_entrega": o_prev["FECHA_HORA_ENTREGA"],
                                    "usuario_entrega": o_prev["USUARIO_ENTREGA"],
                                    "obs_entrega": o_prev["OBS_ENTREGA"],
                                    "recibido_bodega": int(new_rec),
                                    "fecha_hora_finalizacion": (o_prev["FECHA Y HORA DE FINALIZACION"] or ts) if new_rec else "",
                                    "usuario_recepcion": operador if new_rec else "",
                                    "obs_recepcion": new_obs if new_rec else "",
                                }
                            )
                    if to_save:
                        upsert_status_records(to_save)
                        st.success(f"Guardados {len(to_save)} cambios de retorno a bodega.")
                        st.rerun()
                    else:
                        st.info("No se detectaron cambios pendientes.")

# ==============================================================================
# PESTAÑA 3: PORCENTAJE DE AVANCE (VIERNES, SÁBADO Y RETORNO DOMINGO)
# ==============================================================================
with tab3:
    st.subheader("Porcentaje de Avance de Entregas y Retorno a Bodega")

    def pct(num, den):
        return (num / den * 100.0) if den > 0 else 0.0

    df_vie = df_all[df_all["DIA_ENTREGA"] == "Viernes 27/11"]
    df_sab = df_all[df_all["DIA_ENTREGA"] == "Sábado 28/11"]

    vie_rec_ok = int(df_vie["ENTREGADO"].sum())
    vie_paq_ok = int(df_vie.loc[df_vie["ENTREGADO"], "NUMERO DE PAQUETES"].sum())
    sab_rec_ok = int(df_sab["ENTREGADO"].sum())
    sab_paq_ok = int(df_sab.loc[df_sab["ENTREGADO"], "NUMERO DE PAQUETES"].sum())

    tot_rec_ok = int(df_all["ENTREGADO"].sum())
    tot_paq_ok = int(df_all.loc[df_all["ENTREGADO"], "NUMERO DE PAQUETES"].sum())
    ret_rec_ok = int(df_all["RECIBIDO_BODEGA"].sum())
    ret_paq_ok = int(df_all.loc[df_all["RECIBIDO_BODEGA"], "NUMERO DE PAQUETES"].sum())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "📅 Viernes 27/11 (Entregado)",
        f"{pct(vie_rec_ok, len(df_vie)):.1f}%",
        f"{vie_rec_ok}/{len(df_vie)} rec. · {vie_paq_ok:,}/{int(df_vie['NUMERO DE PAQUETES'].sum()):,} paq.",
    )
    m2.metric(
        "📅 Sábado 28/11 (Entregado)",
        f"{pct(sab_rec_ok, len(df_sab)):.1f}%",
        f"{sab_rec_ok}/{len(df_sab)} rec. · {sab_paq_ok:,}/{int(df_sab['NUMERO DE PAQUETES'].sum()):,} paq.",
    )
    m3.metric(
        "🚚 Total Entregado (Vie + Sáb)",
        f"{pct(tot_rec_ok, len(df_all)):.1f}%",
        f"{tot_rec_ok}/{len(df_all)} rec. · {tot_paq_ok:,}/9,466 paq.",
    )
    m4.metric(
        "📦 Domingo 29/11 (Recibido Bodega)",
        f"{pct(ret_rec_ok, len(df_all)):.1f}%",
        f"{ret_rec_ok}/{len(df_all)} rec. · {ret_paq_ok:,}/9,466 paq.",
    )

    st.write("**Progreso Viernes 27/11**")
    st.progress(min(1.0, pct(vie_rec_ok, len(df_vie)) / 100.0))
    st.write("**Progreso Sábado 28/11**")
    st.progress(min(1.0, pct(sab_rec_ok, len(df_sab)) / 100.0))
    st.write("**Progreso Retorno a Bodega (Domingo 29/11)**")
    st.progress(min(1.0, pct(ret_rec_ok, len(df_all)) / 100.0))

    st.divider()

    # Tabla resumen por Día y Bloque
    res_dia = (
        df_all.groupby(["DIA_ENTREGA", "BLOQUE", "FUERZA"], sort=False)
        .agg(
            Total_Recintos=("RECINTO", "count"),
            Entregados=("ENTREGADO", "sum"),
            Total_Paquetes=("NUMERO DE PAQUETES", "sum"),
            Paq_Entregados=("NUMERO DE PAQUETES", lambda s: int(s[df_all.loc[s.index, "ENTREGADO"]].sum())),
            Recibidos_Bodega=("RECIBIDO_BODEGA", "sum"),
        )
        .reset_index()
    )
    res_dia["% Entregado (Rec.)"] = (res_dia["Entregados"] / res_dia["Total_Recintos"] * 100).round(1)
    res_dia["% Entregado (Paq.)"] = (res_dia["Paq_Entregados"] / res_dia["Total_Paquetes"] * 100).round(1)
    res_dia["% Recibido Bodega"] = (res_dia["Recibidos_Bodega"] / res_dia["Total_Recintos"] * 100).round(1)

    g1, g2 = st.columns([1.15, 1])
    with g1:
        st.markdown("##### Avance por Día, Bloque y Fuerza")
        st.dataframe(res_dia, use_container_width=True, hide_index=True)

    with g2:
        fig = px.bar(
            res_dia,
            x="BLOQUE",
            y=["% Entregado (Rec.)", "% Recibido Bodega"],
            barmode="group",
            title="% Avance por Bloque (Entregado vs Recibido en Bodega)",
            labels={"value": "Porcentaje (%)", "variable": "Etapa", "BLOQUE": "Bloque"},
            color_discrete_map={"% Entregado (Rec.)": "#1B365D", "% Recibido Bodega": "#2E7D32"},
        )
        fig.update_layout(yaxis_range=[0, 105], height=340, margin=dict(l=20, r=20, t=45, b=20))
        st.plotly_chart(fig, use_container_width=True)

    # Desglose por GT (Fuerza Naval)
    st.markdown("##### Avance por Grupo de Tarea (Fuerza Naval)")
    df_nav = df_all[df_all["FUERZA"] == "NAVAL"]
    res_gt = (
        df_nav.groupby(["DIA_ENTREGA", "GT"], sort=False)
        .agg(
            Total_Recintos=("RECINTO", "count"),
            Entregados=("ENTREGADO", "sum"),
            Total_Paquetes=("NUMERO DE PAQUETES", "sum"),
            Recibidos_Bodega=("RECIBIDO_BODEGA", "sum"),
        )
        .reset_index()
    )
    res_gt["% Entregado"] = (res_gt["Entregados"] / res_gt["Total_Recintos"] * 100).round(1)
    res_gt["% Recibido Bodega"] = (res_gt["Recibidos_Bodega"] / res_gt["Total_Recintos"] * 100).round(1)
    st.dataframe(res_gt, use_container_width=True, hide_index=True)

    # Descarga de reporte completo con trazabilidad
    export_cols = [
        "ORDEN", "ESTADO", "DIA_ENTREGA", "FECHA_STR", "HORA_STR", "BLOQUE",
        "FUERZA", "GT", "CAMION", "CANTON", "PARROQUIA", "ZONA", "RECINTO",
        "NUMERO DE PAQUETES", "CDA", "KITS CDA", "CODIGO KIT CDA",
        "BIOMBOS (Kits x2)", "BIOMBO MAP (Recinto x2)", "URNAS BLANCAS", "URNAS CAFÉS",
        "ENTREGADO", "FECHA_HORA_ENTREGA", "USUARIO_ENTREGA", "OBS_ENTREGA",
        "RECIBIDO_BODEGA", "FECHA Y HORA DE FINALIZACION", "USUARIO_RECEPCION", "OBS_RECEPCION",
    ]
    st.download_button(
        "⬇️ Descargar Reporte General de Estado y Trazabilidad (Excel)",
        data=to_excel_bytes(df_all[export_cols], "Estado_Logistico"),
        file_name="Reporte_Estado_Despacho_Guayas2026.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
