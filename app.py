import os
from datetime import datetime
from utils import EXCEL_PATH, TZ_EC, USE_SUPABASE, get_merged_df, inject_css, load_base_data, load_status_df
import streamlit as st

st.set_page_config(
    page_title="Control Interno de Bodegas de CNE Guayas — DINDES 2026",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from utils import EXCEL_PATH, TZ_EC, USE_SUPABASE, get_merged_df, inject_css, load_status_df
import tab_comandantes
import tab_control
import tab_avance

inject_css()

if not os.path.exists(EXCEL_PATH):
    st.error(f"No se encontró el archivo base `{EXCEL_PATH}` en la carpeta del aplicativo.")
    st.stop()
    
df_base = load_base_data(EXCEL_PATH, os.path.getmtime(EXCEL_PATH))
tot_recintos = len(df_base)
tot_paquetes = int(df_base["NUMERO DE PAQUETES"].sum())
tot_cantones = int(df_base["CANTON"].nunique())
tot_cda = int(df_base["KITS CDA"].sum())
storage_badge = "☁️ Supabase (Tiempo Real)" if USE_SUPABASE else "💾 SQLite Local"
hora_actual_ec = datetime.now(TZ_EC).strftime("%d/%m/%Y %H:%M")

col_b, col_r = st.columns([5.5, 1.5])
col_b.markdown(
    f"""
    <div class="main-banner">
        <h2>📦 Control Logístico de Material Electoral — DINDES 2026</h2>
        <p>{tot_recintos:,} Recintos · {tot_paquetes:,} Paquetes/Kits · {tot_cantones} Cantones · {tot_cda:,} Kits CDA &nbsp;|🕒 {hora_actual_ec}</p>
    </div>
    """,
    unsafe_allow_html=True,
)
with col_r:
    if st.button("🔄 Actualizar ahora", use_container_width=True, help="Recargar estado y recalcular horarios"):
        load_base_data.clear()
        load_status_df.clear()
        st.rerun()
    auto_ref = st.toggle("Auto-actualizar (60s)", value=False, key="auto_refresh_60s", help="Ideal para pantallas de monitoreo en tiempo real")

pestana = st.radio(
    "Navegación",
    [
        "📅 1. Información de Horarios y Material a Retirar",
        "🔐 2. Control Entregas y Retorno Bodega",
        "📊 3. Control de Avances de Entrega y Recepción",
    ],
    horizontal=True,
    label_visibility="collapsed",
    key="nav_principal",
)


def _render_active_tab():
    df_all = get_merged_df()
    if pestana.startswith("📅"):
        tab_comandantes.render(df_all)
    elif pestana.startswith("🔐"):
        tab_control.render(df_all)
    else:
        tab_avance.render(df_all)


if auto_ref:
    @st.fragment(run_every=60)
    def _live_panel():
        _render_active_tab()
    _live_panel()
else:
    _render_active_tab()



