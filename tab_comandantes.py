import pandas as pd
import streamlit as st
from utils import sort_camiones, to_excel_bytes


def render(df_all: pd.DataFrame):
    st.subheader("Consulta de Fecha y Horario de Recolección")

    c1, c2, c3, c4 = st.columns(4)
    fuerzas_opts = ["TODAS"] + sorted(df_all["FUERZA"].unique().tolist())
    sel_fz = c1.selectbox("Fuerza", fuerzas_opts, key="q_fz")

    df_f = df_all if sel_fz == "TODAS" else df_all[df_all["FUERZA"] == sel_fz]

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

    busq = c7.text_input(
        "Buscar Recinto / Zona / Código Paquete",
        placeholder="Ej: MILAGRO, ROCAFUERTE, KIT-0085...",
        key="q_busq",
    )
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

    if len(df_f) > 0:
        fechas_u = sorted(df_f["FECHA_STR"].unique().tolist())
        horas_u = sorted([h for h in df_f["HORA_STR"].unique().tolist() if h])
        bloques_u = list(dict.fromkeys(df_f["BLOQUE"].tolist()))
        franja_txt = f"{horas_u[0]} a {horas_u[-1]}" if len(horas_u) > 1 else (horas_u[0] if horas_u else "Por definir")
        st.markdown(
            f"""
            <div class="franja-box">
                <strong>🗓️ Fecha de Recolección:</strong> {' / '.join(fechas_u)} &nbsp;&nbsp;|&nbsp;&nbsp;
                <strong>⏰ Franja Horaria de Retiro:</strong> {franja_txt} &nbsp;&nbsp;|&nbsp;&nbsp;
                <strong>📌 Bloque:</strong> {', '.join(bloques_u)}
            </div>
            """,
            unsafe_allow_html=True,
        )

    k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
    kpis = [
        (k1, f"{len(df_f):,}", "Recintos"),
        (k2, f"{int(df_f['NUMERO DE PAQUETES'].sum()):,}", "Paquetes / Kits"),
        (k3, f"{int(df_f['BIOMBOS'].sum()):,}", "Biombos"),
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
            "⬇️ Descargar Detalle Filtrado",
            data=to_excel_bytes(df_show, "Detalle_Recintos"),
            file_name="Horarios_Recintos_Guayas2026.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
