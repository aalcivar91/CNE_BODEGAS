import pandas as pd
import plotly.express as px
import streamlit as st
from utils import to_excel_bytes


def _pct(num, den):
    return (num / den * 100.0) if den > 0 else 0.0


def render(df_all: pd.DataFrame):
    st.subheader("Porcentaje de Avance de Entregas y Retorno a Bodega")

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
        f"{_pct(vie_rec_ok, len(df_vie)):.1f}%",
        f"{vie_rec_ok}/{len(df_vie)} rec. · {vie_paq_ok:,}/{int(df_vie['NUMERO DE PAQUETES'].sum()):,} paq.",
    )
    m2.metric(
        "📅 Sábado 28/11 (Entregado)",
        f"{_pct(sab_rec_ok, len(df_sab)):.1f}%",
        f"{sab_rec_ok}/{len(df_sab)} rec. · {sab_paq_ok:,}/{int(df_sab['NUMERO DE PAQUETES'].sum()):,} paq.",
    )
    m3.metric(
        "🚚 Total Entregado",
        f"{_pct(tot_rec_ok, len(df_all)):.1f}%",
        f"{tot_rec_ok}/{len(df_all)} rec. · {tot_paq_ok:,}/9,466 paq.",
    )
    m4.metric(
        "📦 Recibido a Bodega",
        f"{_pct(ret_rec_ok, len(df_all)):.1f}%",
        f"{ret_rec_ok}/{len(df_all)} rec. · {ret_paq_ok:,}/9,466 paq.",
    )

    st.write("**Progreso Viernes 27/11**")
    st.progress(min(1.0, _pct(vie_rec_ok, len(df_vie)) / 100.0))
    st.write("**Progreso Sábado 28/11**")
    st.progress(min(1.0, _pct(sab_rec_ok, len(df_sab)) / 100.0))
    st.write("**Progreso Retorno a Bodega (Domingo 29/11)**")
    st.progress(min(1.0, _pct(ret_rec_ok, len(df_all)) / 100.0))

    st.divider()

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
    res_gt["% Recibido Bodega"] = (res_gt["Recibidos_BODEGA"] / res_gt["Total_Recintos"] * 100).round(1) if "Recibidos_BODEGA" in res_gt.columns else (res_gt["Recibidos_Bodega"] / res_gt["Total_Recintos"] * 100).round(1)
    st.dataframe(res_gt, use_container_width=True, hide_index=True)

    export_cols = [
        "ORDEN", "ESTADO", "DIA_ENTREGA", "FECHA_STR", "HORA_STR", "BLOQUE",
        "FUERZA", "GT", "CAMION", "CANTON", "PARROQUIA", "ZONA", "RECINTO",
        "NUMERO DE PAQUETES", "CDA", "KITS CDA", "CODIGO KIT CDA",
        "BIOMBOS (Kits x2)", "BIOMBO MAP (Recinto x2)", "URNAS BLANCAS", "URNAS CAFÉS",
        "ENTREGADO", "FECHA_HORA_ENTREGA", "USUARIO_ENTREGA", "OBS_ENTREGA",
        "RECIBIDO_BODEGA", "FECHA Y HORA DE FINALIZACION", "USUARIO_RECEPCION", "OBS_RECEPCION",
    ]
    st.download_button(
        "⬇️ Descargar Reporte General",
        data=to_excel_bytes(df_all[export_cols], "Estado_Logistico"),
        file_name="Reporte_Estado_Despacho_Guayas2026.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
