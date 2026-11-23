import re
import unicodedata
import pandas as pd
import streamlit as st
from utils import sort_camiones, to_excel_bytes


def _norm_text(s: str) -> str:
    s = str(s).upper().strip()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _match_cod_paquete(cod_str: str, q_num: int) -> bool:
    nums = [int(x) for x in re.findall(r"\d+", str(cod_str))]
    if len(nums) >= 2:
        return nums[0] <= q_num <= nums[-1]
    if len(nums) == 1:
        return nums[0] == q_num
    return False


def _reset_filtros():
    st.session_state["q_fz"] = "TODAS"
    st.session_state["q_gt"] = "TODOS"
    st.session_state["q_cam"] = "TODOS"
    st.session_state["q_dia"] = "TODOS"
    st.session_state["q_can"] = "TODOS"
    st.session_state["q_par"] = "TODAS"
    st.session_state["q_busq"] = ""
    st.session_state["q_cda"] = False


def _on_fuerza_change():
    st.session_state["q_gt"] = "TODOS"
    st.session_state["q_cam"] = "TODOS"
    st.session_state["q_can"] = "TODOS"
    st.session_state["q_par"] = "TODAS"
    st.session_state["q_busq"] = ""


def _on_canton_change():
    st.session_state["q_par"] = "TODAS"


def render(df_all: pd.DataFrame):
    col_t, col_btn = st.columns([5, 1.3])
    col_t.subheader("Consulta de Fecha y Horario de Recolección")
    with col_btn:
        st.write("")
        st.button("🧹 Limpiar búsqueda", use_container_width=True, on_click=_reset_filtros)

    c1, c2, c3, c4 = st.columns(4)
    fuerzas_opts = ["TODAS"] + sorted(df_all["FUERZA"].unique().tolist())
    sel_fz = c1.selectbox("Fuerza", fuerzas_opts, key="q_fz", on_change=_on_fuerza_change)

    df_f = df_all if sel_fz == "TODAS" else df_all[df_all["FUERZA"] == sel_fz]

    gt_vals = sorted([x for x in df_f["GT"].unique().tolist() if x])
    gt_opts = ["TODOS"] + gt_vals
    if st.session_state.get("q_gt", "TODOS") not in gt_opts:
        st.session_state["q_gt"] = "TODOS"
    sel_gt = c2.selectbox("GT (Grupo de Tarea)", gt_opts, key="q_gt")
    if sel_gt != "TODOS":
        df_f = df_f[df_f["GT"] == sel_gt]

    cam_vals = sort_camiones(df_f["CAMION"].unique().tolist())
    cam_opts = ["TODOS"] + cam_vals
    if st.session_state.get("q_cam", "TODOS") not in cam_opts:
        st.session_state["q_cam"] = "TODOS"
    sel_cam = c3.selectbox("Camión", cam_opts, key="q_cam")
    if sel_cam != "TODOS":
        df_f = df_f[df_f["CAMION"] == sel_cam]

    dia_vals = ["TODOS"] + sorted(df_f["DIA_ENTREGA"].unique().tolist())
    if st.session_state.get("q_dia", "TODOS") not in dia_vals:
        st.session_state["q_dia"] = "TODOS"
    sel_dia = c4.selectbox("Día de Recolección", dia_vals, key="q_dia")
    if sel_dia != "TODOS":
        df_f = df_f[df_f["DIA_ENTREGA"] == sel_dia]

    c5, c6, c7, c8 = st.columns([1.2, 1.2, 1.8, 0.8])
    can_vals = ["TODOS"] + sorted(df_f["CANTON"].unique().tolist())
    if st.session_state.get("q_can", "TODOS") not in can_vals:
        st.session_state["q_can"] = "TODOS"
    sel_can = c5.selectbox("Cantón", can_vals, key="q_can", on_change=_on_canton_change)
    if sel_can != "TODOS":
        df_f = df_f[df_f["CANTON"] == sel_can]

    par_vals = ["TODAS"] + sorted(df_f["PARROQUIA"].unique().tolist())
    if st.session_state.get("q_par", "TODAS") not in par_vals:
        st.session_state["q_par"] = "TODAS"
    sel_par = c6.selectbox("Parroquia", par_vals, key="q_par")
    if sel_par != "TODAS":
        df_f = df_f[df_f["PARROQUIA"] == sel_par]

    busq = c7.text_input(
        "Buscar Cantón / Parroquia / Recinto / Zona / Código Paquete",
        placeholder="Ej: EL EMPALME, MILAGRO, 900015, KIT-0085...",
        key="q_busq",
    )
    if busq.strip():
        q_raw = busq.strip()
        q = _norm_text(q_raw)
        mask_q = (
            df_f["CANTON"].apply(_norm_text).str.contains(q, na=False, regex=False)
            | df_f["PARROQUIA"].apply(_norm_text).str.contains(q, na=False, regex=False)
            | df_f["ZONA"].apply(_norm_text).str.contains(q, na=False, regex=False)
            | df_f["RECINTO"].apply(_norm_text).str.contains(q, na=False, regex=False)
            | df_f["CODIGO PAQUETES"].apply(_norm_text).str.contains(q, na=False, regex=False)
            | df_f["CODIGO KIT CDA"].apply(_norm_text).str.contains(q, na=False, regex=False)
        )
        if q_raw.isdigit():
            q_num = int(q_raw)
            mask_q = mask_q | df_f["CODIGO PAQUETES"].apply(lambda x: _match_cod_paquete(x, q_num))
        df_f = df_f[mask_q]

    solo_cda = c8.checkbox("Solo CDA", key="q_cda")
    if solo_cda:
        df_f = df_f[df_f["CDA"] == "SÍ"]

    if len(df_f) == 0:
        st.warning("No hay recintos que coincidan con los filtros seleccionados.")
        return

    fechas_u = sorted([x for x in df_f["FECHA_STR"].unique().tolist() if x])
    horas_prog = sorted([h for h in df_f["HORA_STR"].unique().tolist() if h])
    df_pend = df_f[~df_f["ENTREGADO"]]
    horas_est = sorted([h for h in (df_pend if len(df_pend) > 0 else df_f)["HORA_ESTIMADA"].unique().tolist() if h])
    bloques_u = list(dict.fromkeys([b for b in df_f["BLOQUE"].tolist() if b]))

    franja_prog = f"{horas_prog[0]} a {horas_prog[-1]}" if len(horas_prog) > 1 else (horas_prog[0] if horas_prog else "Por definir")
    franja_est = f"{horas_est[0]} a {horas_est[-1]}" if len(horas_est) > 1 else (horas_est[0] if horas_est else franja_prog)
    max_desfase = int(df_f["DESFASE_MIN"].max()) if len(df_f) > 0 else 0
    tiene_demora_viva = df_f["ESTADO_HORARIO"].str.contains("Demora|Reprogramado", na=False).any()

    box_cls = "franja-delay" if (max_desfase > 0 or tiene_demora_viva) else "franja-box"
    desfase_badge = (
        f" ⚠️ (+{max_desfase} min de desfase)"
        if max_desfase > 0
        else (" 🔴 (Turno anterior en demora)" if tiene_demora_viva else " 🟢 (A tiempo)")
    )

    st.markdown(
        f"""
        <div class="{box_cls}">
            <strong>🗓️ Fecha(s):</strong> {' / '.join(fechas_u)} &nbsp;&nbsp;|&nbsp;&nbsp;
            <strong>⏰ Programado:</strong> {franja_prog} &nbsp;&nbsp;|&nbsp;&nbsp;
            <strong>🕒 Estimado Real:</strong> {franja_est}{desfase_badge}<br>
            <strong>📌 Bloque(s):</strong> {', '.join(bloques_u)}
        </div>
        """,
        unsafe_allow_html=True,
    )

    cantones_list = list(dict.fromkeys([x for x in df_f["CANTON"].tolist() if x]))
    camiones_list = sort_camiones([x for x in df_f["CAMION"].unique().tolist() if x and x != "Sin asignar"])
    if "Sin asignar" in df_f["CAMION"].unique().tolist():
        camiones_list.append("Sin asignar")

    cantones_str = ", ".join(cantones_list[:12]) + (f" (+{len(cantones_list)-12} más)" if len(cantones_list) > 12 else "")
    camiones_str = ", ".join(camiones_list[:25]) + (f" (+{len(camiones_list)-25} más)" if len(camiones_list) > 25 else "")

    st.markdown(
        f"""
        <div class="resumen-filtro-box">
            <strong>🏛️ Cantones ({len(cantones_list)}):</strong> {cantones_str}<br>
            <strong>🚚 Camiones ({len(camiones_list)}):</strong> {camiones_str}<br>
            <strong>🏫 Recintos:</strong> {len(df_f):,} recintos asignados en la selección actual.
        </div>
        """,
        unsafe_allow_html=True,
    )

    k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
    kpis = [
        (k1, f"{len(df_f):,}", "Recintos"),
        (k2, f"{int(df_f['NUMERO DE PAQUETES'].sum()):,}", "Paquetes / Kits"),
        (k3, f"{int(df_f['BIOMBOS'].sum()):,}", "Biombos"),
        (k4, f"{int(df_f['BIOMBO MAP'].sum()):,}", "Biombo MAP"),
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
            df_f.groupby(
                ["DIA_ENTREGA", "FECHA_STR", "HORA_STR", "HORA_ESTIMADA", "ESTADO_HORARIO", "BLOQUE", "FUERZA", "GT", "CAMION"],
                sort=False,
            )
            .agg(
                Cantones=("CANTON", lambda s: ", ".join(dict.fromkeys(s))),
                Recintos=("RECINTO", "count"),
                Paquetes=("NUMERO DE PAQUETES", "sum"),
                Biombos=("BIOMBOS", "sum"),
                Biombo_MAP=("BIOMBO MAP", "sum"),
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
                "HORA_STR": "Hora Prog.",
                "HORA_ESTIMADA": "Hora Estimada",
                "ESTADO_HORARIO": "Estado Horario",
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
            "⬇️ Descargar Resumen por Camión",
            data=to_excel_bytes(df_cam, "Resumen_Camiones"),
            file_name="Horarios_Por_Camion_Guayas2026.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        cols_show = [
            "ORDEN", "RECINTO", "CODIGO PAQUETES", "NUMERO DE PAQUETES",
            "HORA_STR", "HORA_ESTIMADA", "ESTADO_HORARIO",
            "FECHA_STR", "CANTON", "PARROQUIA", "ZONA",
            "FUERZA", "GT", "CAMION", "ESTADO",
            "CDA", "KITS CDA", "CODIGO KIT CDA",
            "BIOMBOS", "BIOMBO MAP", "URNAS BLANCAS", "URNAS CAFÉS", "BLOQUE",
        ]
        df_show = df_f[cols_show].rename(
            columns={
                "FECHA_STR": "FECHA RETIRO",
                "HORA_STR": "HORA PROG.",
                "HORA_ESTIMADA": "HORA ESTIMADA",
                "ESTADO_HORARIO": "ESTADO HORARIO",
                "CODIGO PAQUETES": "CÓDIGO PAQUETE ELECTORAL",
                "NUMERO DE PAQUETES": "PAQUETES",
            }
        )
        st.dataframe(
            df_show,
            use_container_width=True,
            hide_index=True,
            height=480,
            column_config={
                "RECINTO": st.column_config.TextColumn("RECINTO", width="large"),
                "CÓDIGO PAQUETE ELECTORAL": st.column_config.TextColumn("CÓDIGO PAQUETE ELECTORAL", width="medium"),
                "HORA ESTIMADA": st.column_config.TextColumn("🕒 HORA ESTIMADA"),
                "ESTADO HORARIO": st.column_config.TextColumn("ESTADO HORARIO", width="medium"),
            },
        )
        st.download_button(
            "⬇️ Descargar Detalle Filtrado",
            data=to_excel_bytes(df_show, "Detalle_Recintos"),
            file_name="Horarios_Recintos_Guayas2026.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
