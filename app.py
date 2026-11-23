import os
import streamlit as st

st.set_page_config(
    page_title="Control Logístico Electoral — DINDES 2026",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from utils import EXCEL_PATH, USE_SUPABASE, get_merged_df, inject_css, load_status_df
import tab_comandantes
import tab_control
import tab_avance

inject_css()

if not os.path.exists(EXCEL_PATH):
    st.error(f"No se encontró el archivo base `{EXCEL_PATH}` en la carpeta del aplicativo.")
    st.stop()

storage_badge = "☁️ Supabase (Tiempo Real)" if USE_SUPABASE else "💾 SQLite Local"

col_b, col_r = st.columns([6, 1])
col_b.markdown(
    f"""
    <div class="main-banner">
        <h2>📦 Control Logístico de Material Electoral — DINDES 2026</h2>
        <p>584 Recintos · 9,466 Paquetes/Kits · 25 Cantones · 499 Kits CDA &nbsp;|&nbsp;</p>
    </div>
    """,
    unsafe_allow_html=True,
)
with col_r:
    st.write("")
    if st.button("🔄 Actualizar", use_container_width=True, help="Recargar datos desde Supabase"):
        load_status_df.clear()
        st.rerun()

pestana = st.radio(
    "Navegación",
    [
        "📅 1. Consulta de Horarios",
        "🔐 2. Control Interno de Entregas Bodega",
        "📊 3. Avance de Porcentaje Entrega-Recepción",
    ],
    horizontal=True,
    label_visibility="collapsed",
    key="nav_principal",
)

df_all = get_merged_df()

if pestana.startswith("📅"):
    tab_comandantes.render(df_all)
elif pestana.startswith("🔐"):
    tab_control.render(df_all)
else:
    tab_avance.render(df_all)
