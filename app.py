import os
from datetime import datetime
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

storage_badge = "☁️ Supabase (Tiempo Real)" if USE_SUPABASE else "💾 SQLite Local"
hora_actual_ec = datetime.now(TZ_EC).strftime("%d/%m/%Y %H:%M")

col_b, col_r = st.columns([5.5, 1.5])
col_b.markdown(
    f"""
    <div class="main-banner">
        <h2>📦 Control Logístico de Material Electoral — DINDES 2026</h2>
        <p>584 Recintos · 9,466 Paquetes/Kits · 25 Cantones · 499 Kits CDA &nbsp;|&nbsp; {storage_badge} &nbsp;|&nbsp; 🕒 {hora_actual_ec}</p>
    </div>
    """,
    unsafe_allow_html=True,
)
with col_r:
    if st.button("🔄 Actualizar ahora", use_container_width=True, help="Recargar estado y recalcular horarios"):
        load_status_df.clear()
        st.rerun()
    auto_ref = st.toggle("Auto-actualizar (60s)", value=False, key="auto_refresh_60s", help="Ideal para pantallas de monitoreo en tiempo real")

pestana = st.radio(
    "Navegación",
    [
        "📅 1. Información de Horarios y Material a Retirar",
        "🔐 2. Control Entregas y Retorno Bodega",
        "📊 3. Control de Avances de Entrega y Recepción,
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
